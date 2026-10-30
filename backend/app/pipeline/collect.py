"""Collector: maps extracted files to hosts and parses per-host system / sar / process data."""
from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.parsers import system as sysp
from app.parsers.common import IP_RE, read_text, size_to_bytes
from app.parsers.sar import parse_sar

_MARKERS = {"hostname", "uname", "df", "free", "ifconfig", "uptime", "lscpu", "meminfo", "cpuinfo", "top", "sar", "sysstat"}
_HOSTDIR_RE = re.compile(r"(?P<name>[A-Za-z0-9._\-]*?)[-_]?(?P<ip>(?:\d{1,3}\.){3}\d{1,3})")


def _base(p: str) -> str:
    return posixpath.basename(p).lower().split(".")[0]


class FileIndex:
    def __init__(self, root: Path, files: list[dict[str, Any]]) -> None:
        self.root = root
        self.files = [f for f in files if f.get("extracted")]
        self.by_cat: dict[str, list[str]] = defaultdict(list)
        for f in self.files:
            self.by_cat[f["category"]].append(f["path"])
        self.host_roots = self._detect_host_roots()

    # ------------------------------------------------------------------
    def _detect_host_roots(self) -> list[str]:
        marker_dirs: set[str] = set()
        ip_dirs: set[str] = set()
        for f in self.files:
            d = posixpath.dirname(f["path"])
            if _base(f["path"]) in _MARKERS:
                marker_dirs.add(d)
            for i, part in enumerate(f["path"].split("/")[:-1]):
                if IP_RE.search(part):
                    ip_dirs.add("/".join(f["path"].split("/")[: i + 1]))
        roots = set(ip_dirs)
        for d in sorted(marker_dirs, key=lambda x: x.count("/")):
            if not any(d == r or d.startswith(r + "/") for r in roots):
                roots.add(d)
        return sorted(roots, key=lambda x: -len(x))   # longest first for matching

    def host_of(self, path: str) -> str | None:
        for r in self.host_roots:
            if path == r or path.startswith(r + "/") or posixpath.dirname(path) == r:
                return r
        return None

    def read(self, rel: str, max_bytes: int = 64 * 1024 * 1024) -> str:
        return read_text(self.root / rel, max_bytes)

    def find(self, pattern: str, cat: str | None = None) -> list[str]:
        rx = re.compile(pattern, re.I)
        pool = self.by_cat.get(cat, []) if cat else [f["path"] for f in self.files]
        return [p for p in pool if rx.search(p)]


def host_identity(idx: FileIndex, root: str | None, files: list[str]) -> dict[str, Any]:
    name, ip = None, None
    for p in files:
        if _base(p) == "hostname":
            t = idx.read(p, 4096).strip().splitlines()
            if t:
                name = t[0].strip().split(".")[0]
    if root:
        m = _HOSTDIR_RE.search(posixpath.basename(root))
        if m:
            ip = m.group("ip")
            name = name or (m.group("name") or None)
        name = name or posixpath.basename(root)
    for p in files:
        if _base(p) in ("ifconfig", "ip") or "ip_addr" in p.lower() or "ipaddr" in p.lower():
            t = idx.read(p, 256 * 1024)
            m = re.search(r"inet (?:addr:)?((?:\d{1,3}\.){3}\d{1,3})(?![\d/]*\s*scope host)", t)
            ips = [x for x in re.findall(r"inet (?:addr:)?((?:\d{1,3}\.){3}\d{1,3})", t) if not x.startswith("127.")]
            if ips and not ip:
                ip = ips[0]
    return {"hostname": name, "ip": ip}


def collect_host_perf(idx: FileIndex) -> dict[str, dict[str, Any]]:
    """Return {normalised host/ip: perf dict}."""
    groups: dict[str | None, list[str]] = defaultdict(list)
    for f in idx.files:
        if f["category"] in ("system", "sar", "config", "hostcontext"):
            groups[idx.host_of(f["path"])].append(f["path"])
    out: dict[str, dict[str, Any]] = {}
    for root, files in groups.items():
        ident = host_identity(idx, root, files)
        perf = _parse_host_files(idx, files)
        perf["key"] = root or "global"
        perf["identity"] = ident
        if not any(perf.get(k) for k in ("sar", "df", "memory", "top", "ps", "uptime")):
            continue
        keys = {(ident["ip"] or "").lower(), (ident["hostname"] or "").lower(), (root or "").lower()} - {""}
        for k in keys:
            out[k] = perf
        out.setdefault("__all__", {})
        out["__all__"][root or "global"] = perf
    return out


def _parse_host_files(idx: FileIndex, files: list[str]) -> dict[str, Any]:
    perf: dict[str, Any] = {"df": [], "memory": {}, "hardware": {}, "sources": []}
    sar_texts: list[str] = []
    for p in files:
        try:
            text = idx.read(p, 128 * 1024 * 1024 if _looks_sar_name(p) else 16 * 1024 * 1024)
        except OSError:
            continue
        if not text.strip():
            continue
        used = False
        if re.search(r"%idle|kbmemfree|kbmemused|ldavg-1|\bawait\b.*%util|rxpck/s", text):
            sar_texts.append(text)
            used = True
        df = sysp.parse_df(text) if re.search(r"^\s*Filesystem\s", text, re.M | re.I) else []
        if df:
            perf["df"] = _merge_df(perf["df"], df)
            used = True
        if re.search(r"^\s*Mem:", text, re.M):
            perf["memory"] = {**perf["memory"], **sysp.parse_free(text)}
            used = True
        if re.search(r"^MemTotal:", text, re.M):
            perf["memory"] = {**perf["memory"], **sysp.parse_meminfo(text)}
            used = True
        if re.search(r"^CPU\(s\):", text, re.M):
            perf["hardware"].update({k: v for k, v in sysp.parse_lscpu(text).items() if v})
            used = True
        if re.search(r"^processor\s*:", text, re.M):
            ci = sysp.parse_cpuinfo(text)
            perf["hardware"].setdefault("cpus", ci["cpus"])
            perf["hardware"].setdefault("model", ci["model"])
            used = True
        if re.search(r"load average", text):
            if re.search(r"^\s*PID\s+USER", text, re.M):
                perf["top"] = sysp.parse_top(text)
            else:
                perf["uptime"] = sysp.parse_uptime(text)
            used = True
        if re.search(r"^\s*USER\s+PID\s+%CPU", text, re.M) and "top" not in perf:
            ps = sysp.parse_ps(text)
            perf["ps"] = ps
            perf["httpd_count"] = ps["httpd_count"]
            used = True
        elif re.search(r"^\s*USER\s+PID\s+%CPU", text, re.M):
            ps = sysp.parse_ps(text)
            perf["ps"] = ps
            perf["httpd_count"] = ps["httpd_count"]
        osr = sysp.parse_os_release(text)
        if osr:
            perf["hardware"].setdefault("os", osr)
            used = True
        vi = sysp.find_version_info(text) if re.search(r"(^|/)(version|qradar[_-]?version|build)", p, re.I) else {}
        if vi:
            perf["version_info"] = vi
            perf["version"] = vi.get("version")
        prod = re.search(r"Product Name:\s*(.+)", text)
        if prod:
            perf["hardware"]["model"] = perf["hardware"].get("model_hw") or prod.group(1).strip()
            perf["hardware"]["platform"] = prod.group(1).strip()
        if used:
            perf["sources"].append(p)
    if sar_texts:
        merged = _merge_sar([parse_sar(t) for t in sar_texts])
        perf["sar"] = merged
        perf["hardware"].setdefault("cpus", merged.get("cpus"))
    mem = perf["memory"]
    if mem.get("total"):
        perf["hardware"]["memory_bytes"] = mem["total"]
    perf["hardware"]["disk_bytes"] = sum(f["size_bytes"] or 0 for f in perf["df"] if f["mount"] in ("/store", "/", "/storetmp", "/transient")) or None
    perf["hardware"]["swap_bytes"] = mem.get("swap_total")
    return perf


def _looks_sar_name(p: str) -> bool:
    return bool(re.search(r"sar|sysstat|sa\d{2}", p, re.I))


def _merge_df(a: list[dict], b: list[dict]) -> list[dict]:
    seen = {f["mount"] for f in a}
    return a + [f for f in b if f["mount"] not in seen]


def _merge_sar(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if len(parts) == 1:
        return parts[0]
    base = max(parts, key=lambda p: sum(p.get("samples", {}).values()))
    for p in parts:
        if p is base:
            continue
        for k in ("series", "summary", "disks", "interfaces"):
            for kk, vv in p.get(k, {}).items():
                base[k].setdefault(kk, vv)
        base["cpus"] = base.get("cpus") or p.get("cpus")
    return base


def collect_misc(idx: FileIndex) -> dict[str, Any]:
    """Version info, masterlist, tunnel errors, install type from anywhere in the bundle."""
    info: dict[str, Any] = {}
    candidates = idx.find(r"(^|/)(VERSION|version|qradar_version|build_info|qradar-release|system_info)[^/]*$") + \
        idx.find(r"/opt/qradar/conf/.*\.(properties|conf)$")
    for p in candidates[:40]:
        try:
            t = idx.read(p, 512 * 1024)
        except OSError:
            continue
        vi = sysp.find_version_info(t)
        for k, v in vi.items():
            info.setdefault(k, v)
    ml = idx.find(r"masterlist", None)
    if ml:
        t = idx.read(ml[0], 1024 * 1024)
        info["masterlist"] = sorted(set(IP_RE.findall(t)))
    tunnel_err = 0
    for p in idx.find(r"(tunnel|autossh|ssh).*log|qradar\.(error|log)|hostcontext", "log")[:20] + idx.by_cat.get("hostcontext", [])[:20]:
        try:
            t = idx.read(p, 8 * 1024 * 1024)
        except OSError:
            continue
        tunnel_err += len(re.findall(r"(tunnel|autossh|ssh).{0,80}(fail|refused|timed? ?out|down|error)", t, re.I))
    info["tunnel_errors"] = tunnel_err
    hw_text = ""
    for p in idx.find(r"dmidecode|hardware|lshw|system[_-]?info", None)[:6]:
        hw_text += idx.read(p, 512 * 1024)
    if hw_text:
        if re.search(r"VMware|KVM|Xen|Hyper-V|VirtualBox|Amazon EC2|Microsoft Corporation.*Virtual", hw_text, re.I):
            info["install_type"] = "Virtual appliance"
        elif re.search(r"IBM|Lenovo|Dell|HP|Hewlett|Supermicro", hw_text, re.I):
            info["install_type"] = "Physical appliance / hardware"
        pn = re.search(r"Product Name:\s*(.+)", hw_text)
        if pn:
            info["platform"] = pn.group(1).strip()
        mf = re.search(r"Manufacturer:\s*(.+)", hw_text)
        if mf:
            info["manufacturer"] = mf.group(1).strip()
    return info
