"""Hardened streaming extractor for .tar / .tar.gz / .tgz / .gz / .zip get_logs bundles.

Defends against: Zip Slip & path traversal, absolute paths, NUL bytes, symlink / hardlink / device
entries, decompression bombs (size, ratio, file-count, nesting depth), extension spoofing (magic-byte
validation), duplicate members and over-long paths.  Extraction is *selective*: only members
relevant to the health check are materialised (see ``classify``); everything else is catalogued in
the manifest so very large (>10 GB) bundles are processed in a single streaming pass.
"""
from __future__ import annotations

import gzip
import io
import os
import posixpath
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from app.core.config import Settings, get_settings
from app.ingestion.classify import ARCHIVE_RE, classify, member_cap


class ArchiveSecurityError(Exception):
    """Archive violates a hard security limit – ingestion must abort."""


class UnsupportedArchiveError(Exception):
    pass


@dataclass
class ExtractedFile:
    rel_path: str       # path relative to extraction root (posix)
    size: int
    category: str
    truncated: bool = False
    origin: str = ""    # nested archive chain


@dataclass
class ExtractionResult:
    root: Path
    files: list[ExtractedFile] = field(default_factory=list)
    manifest: list[dict] = field(default_factory=list)       # every member seen
    warnings: list[str] = field(default_factory=list)
    security_events: list[dict] = field(default_factory=list)
    total_members: int = 0
    total_bytes_extracted: int = 0
    total_bytes_seen: int = 0


# ---------------------------------------------------------------------------
# Format sniffing
# ---------------------------------------------------------------------------
def sniff(path: Path) -> str:
    """Return one of: zip, tar.gz, tar, gz, unknown – based on magic bytes, not extension."""
    with open(path, "rb") as fh:
        head = fh.read(512)
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if head[:2] == b"\x1f\x8b":
        try:
            with gzip.open(path, "rb") as g:
                inner = g.read(512)
        except (OSError, EOFError) as e:
            raise UnsupportedArchiveError(f"Corrupt gzip stream: {e}") from e
        return "tar.gz" if _looks_like_tar(inner) else "gz"
    if _looks_like_tar(head):
        return "tar"
    return "unknown"


def _looks_like_tar(block: bytes) -> bool:
    return len(block) >= 262 and block[257:262] == b"ustar"


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------
def sanitize_member_path(name: str, max_len: int = 1024) -> str:
    """Return a safe relative posix path or raise ArchiveSecurityError."""
    if "\x00" in name:
        raise ArchiveSecurityError("NUL byte in member name")
    n = name.replace("\\", "/")
    if len(n) > max_len or any(len(part) > 255 for part in n.split("/")):
        raise ArchiveSecurityError("Member path too long")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        raise ArchiveSecurityError(f"Absolute path in archive: {name!r}")
    norm = posixpath.normpath(n)
    if norm in ("", "."):
        raise ArchiveSecurityError("Empty member name")
    parts = norm.split("/")
    if ".." in parts or norm.startswith("../"):
        raise ArchiveSecurityError(f"Path traversal attempt: {name!r}")
    if any(ord(c) < 32 for c in norm):
        raise ArchiveSecurityError("Control characters in member name")
    return norm


def _resolve_inside(root: Path, rel: str) -> Path:
    target = (root / rel).resolve()
    root_r = root.resolve()
    if target != root_r and root_r not in target.parents:
        raise ArchiveSecurityError(f"Resolved path escapes extraction root: {rel!r}")
    return target


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------
class SafeExtractor:
    def __init__(self, dest: Path, settings: Settings | None = None, progress=None) -> None:
        self.s = settings or get_settings()
        self.dest = dest
        self.dest.mkdir(parents=True, exist_ok=True)
        self.result = ExtractionResult(root=dest)
        self.progress = progress
        self._seen: set[str] = set()
        self._compressed_total = 0

    # -- public ------------------------------------------------------------
    def extract(self, archive: Path, display_name: str | None = None) -> ExtractionResult:
        size = archive.stat().st_size
        self._compressed_total = max(size, 1)
        self._extract_archive(archive, prefix="", depth=0, display_name=display_name or archive.name)
        return self.result

    # -- internals ---------------------------------------------------------
    def _extract_archive(self, archive: Path, prefix: str, depth: int, display_name: str) -> None:
        if depth > self.s.max_nested_depth:
            raise ArchiveSecurityError(f"Archive nesting deeper than {self.s.max_nested_depth}")
        kind = sniff(archive)
        if kind == "unknown":
            raise UnsupportedArchiveError(
                f"{display_name}: not a recognised .tar/.tar.gz/.gz/.zip archive (magic-byte check failed)")
        if kind == "zip":
            self._extract_zip(archive, prefix, depth)
        elif kind in ("tar", "tar.gz"):
            self._extract_tar(archive, prefix, depth)
        else:
            self._extract_plain_gz(archive, prefix, depth, display_name)

    # ---- generic accounting ---------------------------------------------
    def _account_member(self, rel: str, declared: int) -> None:
        r = self.result
        r.total_members += 1
        r.total_bytes_seen += max(declared, 0)
        if r.total_members > self.s.max_archive_files:
            raise ArchiveSecurityError(f"Archive has more than {self.s.max_archive_files} members")

    def _check_ratio(self) -> None:
        r = self.result
        if r.total_bytes_extracted > self.s.ratio_check_threshold_bytes:
            ratio = r.total_bytes_extracted / self._compressed_total
            if ratio > self.s.max_compression_ratio:
                raise ArchiveSecurityError(f"Suspicious compression ratio {ratio:.0f}:1 (possible decompression bomb)")
        if r.total_bytes_extracted > self.s.max_total_extracted_bytes:
            raise ArchiveSecurityError("Total extracted size limit exceeded")

    def _event(self, kind: str, member: str, detail: str) -> None:
        self.result.security_events.append({"type": kind, "member": member[:300], "detail": detail})

    def _unique(self, rel: str) -> str:
        if rel not in self._seen:
            self._seen.add(rel)
            return rel
        base, ext = posixpath.splitext(rel)
        i = 1
        while f"{base}.dup{i}{ext}" in self._seen:
            i += 1
        new = f"{base}.dup{i}{ext}"
        self._seen.add(new)
        self._event("duplicate_member", rel, f"renamed to {new}")
        return new

    def _write_stream(self, src: BinaryIO, rel: str, cap: int) -> tuple[int, bool, Path]:
        """Copy ``src`` to dest/rel, hard-limited to ``cap`` bytes. Returns (written, truncated, path)."""
        target = _resolve_inside(self.dest, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        written, truncated = 0, False
        chunk = 1024 * 1024
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(target, flags, 0o600)   # never executable, never follows an existing symlink
        with os.fdopen(fd, "wb") as out:
            while True:
                buf = src.read(min(chunk, cap - written + 1))
                if not buf:
                    break
                if written + len(buf) > cap:
                    keep = cap - written
                    if keep > 0:
                        out.write(buf[:keep])
                        written += keep
                    truncated = True
                    break
                out.write(buf)
                written += len(buf)
        return written, truncated, target

    # ---- handle one logical member ----------------------------------------
    def _handle_member(self, raw_name: str, declared: int, opener, prefix: str, depth: int) -> None:
        try:
            rel = sanitize_member_path(raw_name, self.s.max_path_length)
        except ArchiveSecurityError as e:
            self._event("unsafe_path", raw_name, str(e))
            raise
        full = f"{prefix}{rel}"
        self._account_member(full, declared)
        cat = classify(full)
        low = rel.lower()
        entry = {"path": full, "size": declared, "category": cat, "extracted": False}
        cap = member_cap(cat, self.s.max_extracted_member_bytes, self.s.max_text_member_bytes)

        is_nested = low.endswith((".tar", ".tar.gz", ".tgz", ".zip"))
        is_gz = low.endswith(".gz") and not low.endswith(".tar.gz")
        wanted = cat not in ("other", "log") or (cat == "log" and not is_gz and declared <= cap)

        if not (is_nested or wanted):
            # catalogue only – unread members are skipped by the streaming readers
            self.result.manifest.append(entry)
            return

        with opener() as src:
            if is_nested:
                self._extract_nested(src, rel, prefix, depth)
                entry["nested"] = True
            elif is_gz:
                self._extract_gz_member(src, rel, full, cat, cap, entry)
            else:
                rel_u = self._unique(full)
                written, trunc, _ = self._write_stream(src, rel_u, cap)
                self.result.total_bytes_extracted += written
                self._check_ratio()
                entry.update(extracted=True, size=written, truncated=trunc, path=rel_u)
                self.result.files.append(ExtractedFile(rel_u, written, cat, trunc, prefix))
        self.result.manifest.append(entry)

    def _extract_gz_member(self, src: BinaryIO, rel: str, full: str, cat: str, cap: int, entry: dict) -> None:
        name = full[:-3]
        with gzip.GzipFile(fileobj=src) as gz:
            head = gz.read(512)
            if _looks_like_tar(head):
                tmp = self.dest / f".nested_{len(self._seen)}.tar"
                with open(tmp, "wb") as fh:
                    fh.write(head)
                    shutil.copyfileobj(gz, fh, 1024 * 1024)
                try:
                    self._extract_tar(tmp, name.rsplit("/", 1)[0] + "/" if "/" in name else "", 1)
                finally:
                    tmp.unlink(missing_ok=True)
                entry["nested"] = True
                return
            class _Prefixed(io.RawIOBase):
                def __init__(self, first, rest):
                    self.first, self.rest = first, rest
                def readable(self): return True
                def readinto(self, b):
                    if self.first:
                        n = min(len(b), len(self.first)); b[:n] = self.first[:n]; self.first = self.first[n:]; return n
                    d = self.rest.read(len(b)); b[:len(d)] = d; return len(d)
            stream = io.BufferedReader(_Prefixed(head, gz))
            rel_u = self._unique(name)
            written, trunc, _ = self._write_stream(stream, rel_u, cap)
        self.result.total_bytes_extracted += written
        self._check_ratio()
        entry.update(extracted=True, size=written, truncated=trunc, path=rel_u)
        self.result.files.append(ExtractedFile(rel_u, written, cat, trunc))

    def _extract_nested(self, src: BinaryIO, rel: str, prefix: str, depth: int) -> None:
        if depth + 1 > self.s.max_nested_depth:
            raise ArchiveSecurityError(f"Archive nesting deeper than {self.s.max_nested_depth}")
        tmp = self.dest / f".nested_{depth}_{len(self._seen)}"
        written, trunc, _ = (0, False, tmp)
        try:
            with open(tmp, "wb") as fh:
                shutil.copyfileobj(src, fh, 1024 * 1024)
            sub_prefix = posixpath.join(prefix, posixpath.splitext(posixpath.basename(rel))[0].replace(".tar", "")) + "/"
            self._extract_archive(tmp, sub_prefix, depth + 1, rel)
        finally:
            tmp.unlink(missing_ok=True)

    # ---- tar ---------------------------------------------------------------
    def _extract_tar(self, archive: Path, prefix: str, depth: int) -> None:
        with tarfile.open(archive, mode="r|*") as tf:
            for ti in tf:
                if ti.isdir():
                    continue
                if ti.issym() or ti.islnk():
                    self._event("link_skipped", ti.name, f"{'symlink' if ti.issym() else 'hardlink'} -> {ti.linkname}")
                    self._link_check(ti.name, ti.linkname)
                    continue
                if not ti.isreg():
                    self._event("special_file_skipped", ti.name, f"type={ti.type!r}")
                    continue
                if ti.size > self.s.max_extracted_member_bytes and classify(ti.name) != "other":
                    raise ArchiveSecurityError(f"Member {ti.name!r} exceeds size limit ({ti.size} bytes)")
                self._handle_member(ti.name, ti.size, lambda ti=ti, tf=tf: _CtxFile(tf.extractfile(ti)), prefix, depth)
                if self.progress:
                    self.progress(self.result.total_members, self.result.total_bytes_seen)

    def _link_check(self, name: str, linkname: str) -> None:
        ln = linkname.replace("\\", "/")
        if ln.startswith("/") or ".." in ln.split("/"):
            self._event("malicious_link", name, f"link target escapes root: {linkname!r}")

    # ---- zip ---------------------------------------------------------------
    def _extract_zip(self, archive: Path, prefix: str, depth: int) -> None:
        with zipfile.ZipFile(archive) as zf:
            infos = zf.infolist()
            if len(infos) > self.s.max_archive_files:
                raise ArchiveSecurityError("Too many members in zip")
            for zi in infos:
                if zi.is_dir():
                    continue
                mode = (zi.external_attr >> 16) & 0o170000
                if mode == 0o120000:   # symlink
                    self._event("link_skipped", zi.filename, "symlink")
                    continue
                if zi.flag_bits & 0x1:
                    raise UnsupportedArchiveError("Encrypted zip members are not supported")
                if zi.file_size > self.s.max_extracted_member_bytes and classify(zi.filename) != "other":
                    raise ArchiveSecurityError(f"Member {zi.filename!r} exceeds size limit")
                if zi.compress_size and zi.file_size / max(zi.compress_size, 1) > self.s.max_compression_ratio \
                        and zi.file_size > 100 * 1024 * 1024:
                    raise ArchiveSecurityError(f"Suspicious compression ratio on {zi.filename!r}")
                self._handle_member(zi.filename, zi.file_size, lambda zi=zi, zf=zf: _CtxFile(zf.open(zi)), prefix, depth)
                if self.progress:
                    self.progress(self.result.total_members, self.result.total_bytes_seen)

    # ---- plain gz ----------------------------------------------------------
    def _extract_plain_gz(self, archive: Path, prefix: str, depth: int, display_name: str) -> None:
        name = display_name[:-3] if display_name.lower().endswith(".gz") else display_name + ".out"
        name = posixpath.basename(name.replace("\\", "/")) or "payload"
        with open(archive, "rb") as raw:
            self._handle_member(name, 0, lambda: _CtxFile(gzip.GzipFile(fileobj=raw)), prefix, depth)


class _CtxFile:
    """Context-manager wrapper; does not close the underlying shared tar stream."""

    def __init__(self, fh) -> None:
        self.fh = fh

    def __enter__(self):
        return self.fh

    def __exit__(self, *a):
        try:
            self.fh.close()
        except Exception:  # pragma: no cover
            pass
        return False
