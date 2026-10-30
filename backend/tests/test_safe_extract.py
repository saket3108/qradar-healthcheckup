import gzip
import io
import tarfile
import zipfile
from pathlib import Path

import pytest

from app.core.config import Settings
from app.ingestion.safe_extract import (ArchiveSecurityError, SafeExtractor, UnsupportedArchiveError, sanitize_member_path, sniff)


def mk_tar(path: Path, members: dict, gz=True, extra=None):
    with tarfile.open(path, "w:gz" if gz else "w") as tf:
        for n, d in members.items():
            ti = tarfile.TarInfo(n)
            ti.size = len(d)
            tf.addfile(ti, io.BytesIO(d))
        for ti in extra or []:
            tf.addfile(ti)


def settings(**kw) -> Settings:
    return Settings(**kw)


def test_extracts_relevant_and_catalogues_irrelevant(tmp_path):
    a = tmp_path / "a.tar.gz"
    mk_tar(a, {"x/deployment.xml": b"<deployment/>", "x/random/video.bin": b"0" * 100, "x/h/df": b"Filesystem Size\n"})
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    paths = {f.rel_path for f in res.files}
    assert "x/deployment.xml" in paths and "x/h/df" in paths
    assert res.total_members == 3
    assert any(m["path"] == "x/random/video.bin" and not m["extracted"] for m in res.manifest)


@pytest.mark.parametrize("bad", ["../evil.xml", "a/../../evil.xml", "/etc/passwd", "C:/Windows/x", "a\\..\\..\\x", "x\x00y"])
def test_path_traversal_rejected(bad):
    with pytest.raises(ArchiveSecurityError):
        sanitize_member_path(bad)


def test_tar_zip_slip_aborts(tmp_path):
    a = tmp_path / "evil.tar.gz"
    mk_tar(a, {"../../outside.xml": b"x"})
    with pytest.raises(ArchiveSecurityError):
        SafeExtractor(tmp_path / "o", settings()).extract(a)
    assert not (tmp_path / "outside.xml").exists()


def test_zip_slip_aborts(tmp_path):
    z = tmp_path / "e.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../outside.xml", "x")
    with pytest.raises(ArchiveSecurityError):
        SafeExtractor(tmp_path / "o", settings()).extract(z)


def test_symlinks_skipped_and_logged(tmp_path):
    a = tmp_path / "l.tar"
    ti = tarfile.TarInfo("link")
    ti.type, ti.linkname = tarfile.SYMTYPE, "/etc/passwd"
    mk_tar(a, {"ok/deployment.xml": b"<d/>"}, gz=False, extra=[ti])
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    kinds = {e["type"] for e in res.security_events}
    assert {"link_skipped", "malicious_link"} <= kinds
    assert not (tmp_path / "o" / "link").exists()


def test_device_files_skipped(tmp_path):
    a = tmp_path / "d.tar"
    ti = tarfile.TarInfo("dev")
    ti.type = tarfile.CHRTYPE
    mk_tar(a, {"ok/deployment.xml": b"<d/>"}, gz=False, extra=[ti])
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    assert any(e["type"] == "special_file_skipped" for e in res.security_events)


def test_member_size_limit_enforced(tmp_path):
    a = tmp_path / "big.tar.gz"
    mk_tar(a, {"x/h/df": b"A" * 5000})
    with pytest.raises(ArchiveSecurityError):
        SafeExtractor(tmp_path / "o", settings(max_extracted_member_bytes=1000)).extract(a)


def test_file_count_limit(tmp_path):
    a = tmp_path / "many.tar.gz"
    mk_tar(a, {f"f{i}.txt": b"x" for i in range(20)})
    with pytest.raises(ArchiveSecurityError):
        SafeExtractor(tmp_path / "o", settings(max_archive_files=10)).extract(a)


def test_decompression_bomb_ratio(tmp_path):
    a = tmp_path / "bomb.tar.gz"
    mk_tar(a, {"x/h/sar/sar_01": b"0" * (3 * 1024 * 1024)})
    s = settings(ratio_check_threshold_bytes=1024 * 1024, max_compression_ratio=50)
    with pytest.raises(ArchiveSecurityError, match="ratio"):
        SafeExtractor(tmp_path / "o", s).extract(a)


def test_total_size_limit(tmp_path):
    a = tmp_path / "t.tar.gz"
    mk_tar(a, {"a/h/df": b"1" * 800, "b/h/df": b"2" * 800})
    with pytest.raises(ArchiveSecurityError, match="Total"):
        SafeExtractor(tmp_path / "o", settings(max_total_extracted_bytes=1000, ratio_check_threshold_bytes=10**12)).extract(a)


def test_nested_depth_limit(tmp_path):
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w") as tf:
        ti = tarfile.TarInfo("deployment.xml"); ti.size = 4; tf.addfile(ti, io.BytesIO(b"<d/>"))
    data = inner.getvalue()
    for i in range(4):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            ti = tarfile.TarInfo(f"n{i}.tar"); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
        data = buf.getvalue()
    p = tmp_path / "deep.tar"
    p.write_bytes(data)
    with pytest.raises(ArchiveSecurityError, match="nesting"):
        SafeExtractor(tmp_path / "o", settings(max_nested_depth=2)).extract(p)


def test_nested_tar_within_tar_extracted(tmp_path):
    inner = io.BytesIO()
    with tarfile.open(fileobj=inner, mode="w:gz") as tf:
        ti = tarfile.TarInfo("h/deployment.xml"); ti.size = 4; tf.addfile(ti, io.BytesIO(b"<d/>"))
    a = tmp_path / "outer.tar"
    mk_tar(a, {"logs/inner.tar.gz": inner.getvalue()}, gz=False)
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    assert any(f.rel_path.endswith("deployment.xml") for f in res.files)


def test_gz_member_decompressed(tmp_path):
    a = tmp_path / "g.tar"
    mk_tar(a, {"h/sar/sar_01.gz": gzip.compress(b"Linux 4.18 (h)\n")}, gz=False)
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    assert any(f.rel_path == "h/sar/sar_01" for f in res.files)


def test_plain_gz_file(tmp_path):
    p = tmp_path / "deployment.xml.gz"
    p.write_bytes(gzip.compress(b"<deployment/>"))
    res = SafeExtractor(tmp_path / "o", settings()).extract(p)
    assert res.files and res.files[0].category == "deployment"


def test_zip_extracts(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("get_logs/deployment.xml", "<deployment/>")
        zf.writestr("get_logs/host/df", "Filesystem Size\n")
    res = SafeExtractor(tmp_path / "o", settings()).extract(z)
    assert len(res.files) == 2


def test_zip_symlink_skipped(tmp_path):
    z = tmp_path / "s.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zi = zipfile.ZipInfo("lnk"); zi.external_attr = (0o120777 << 16)
        zf.writestr(zi, "/etc/passwd")
        zf.writestr("ok/deployment.xml", "<d/>")
    res = SafeExtractor(tmp_path / "o", settings()).extract(z)
    assert any(e["type"] == "link_skipped" for e in res.security_events)


def test_encrypted_zip_unsupported(tmp_path):
    z = tmp_path / "enc.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.xml", "x")
    raw = bytearray(z.read_bytes())
    # set encryption flag bit in local + central headers
    for sig in (b"PK\x03\x04", b"PK\x01\x02"):
        i = raw.find(sig)
        off = i + (6 if sig == b"PK\x03\x04" else 8)
        raw[off] |= 1
    z.write_bytes(bytes(raw))
    with pytest.raises(UnsupportedArchiveError):
        SafeExtractor(tmp_path / "o", settings()).extract(z)


def test_extension_spoofing_rejected(tmp_path):
    p = tmp_path / "fake.tar.gz"
    p.write_bytes(b"MZ\x90\x00 this is an exe")
    with pytest.raises(UnsupportedArchiveError):
        SafeExtractor(tmp_path / "o", settings()).extract(p)


def test_corrupt_gzip(tmp_path):
    p = tmp_path / "c.gz"
    p.write_bytes(b"\x1f\x8b\x08\x00garbage")
    with pytest.raises(Exception):
        SafeExtractor(tmp_path / "o", settings()).extract(p)


def test_sniff_kinds(tmp_path):
    t = tmp_path / "a.tar"; mk_tar(t, {"a": b"b"}, gz=False)
    tg = tmp_path / "a.tgz"; mk_tar(tg, {"a": b"b"})
    g = tmp_path / "a.gz"; g.write_bytes(gzip.compress(b"hello"))
    z = tmp_path / "a.zip"; zipfile.ZipFile(z, "w").close()
    assert (sniff(t), sniff(tg), sniff(g)) == ("tar", "tar.gz", "gz")
    z.write_bytes(b"PK\x03\x04" + b"\x00" * 30)
    assert sniff(z) == "zip"


def test_duplicate_members_renamed(tmp_path):
    a = tmp_path / "dup.tar"
    with tarfile.open(a, "w") as tf:
        for c in (b"one", b"two"):
            ti = tarfile.TarInfo("h/df"); ti.size = 3; tf.addfile(ti, io.BytesIO(c))
    res = SafeExtractor(tmp_path / "o", settings()).extract(a)
    assert len(res.files) == 2 and any(e["type"] == "duplicate_member" for e in res.security_events)


def test_path_too_long():
    with pytest.raises(ArchiveSecurityError):
        sanitize_member_path("a/" + "b" * 300)
