"""Parsers for system command outputs (df, free, top, ps, lscpu, meminfo, uptime, os release)."""
from __future__ import annotations

import re
from typing import Any

from app.parsers.common import size_to_bytes, to_float, to_int

GB = 1024**3


def parse_df(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    lines = [l for l in text.splitlines() if l.strip()]
    pending = ""
    for l in lines:
        if l.lower().startswith("filesystem"):
            continue
        parts = (pending + " " + l).split() if pending else l.split()
        if len(parts) == 1:           # long device names wrap onto next line
            pending = parts[0]
            continue
        pending = ""
        if len(parts) < 6:
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)%$", parts[-2])
        if not m:
            continue
        size = size_to_bytes(parts[-5]) if not parts[-5].isdigit() else int(parts[-5]) * 1024
        used = size_to_bytes(parts[-4]) if not parts[-4].isdigit() else int(parts[-4]) * 1024
        avail = size_to_bytes(parts[-3]) if not parts[-3].isdigit() else int(parts[-3]) * 1024
        out.append({"filesystem": parts[0], "mount": parts[-1], "size_bytes": size, "used_bytes": used,
                    "avail_bytes": avail, "use_pct": float(m.group(1))})
    return out


def parse_free(text: str) -> dict[str, Any]:
    mem: dict[str, Any] = {}
    unit = 1024
    if re.search(r"\bfree\b.*-m|mega", text[:200], re.I):
        unit = 1024**2
    for l in text.splitlines():
        p = l.split()
        if not p:
            continue
        if p[0].lower() == "mem:" and len(p) >= 4:
            vals = [to_int(x) or 0 for x in p[1:]]
            mem.update(total=vals[0] * unit, used=vals[1] * unit, free=vals[2] * unit)
            if len(vals) >= 6:
                mem["available"] = vals[5] * unit
            elif len(vals) >= 4:
                mem["available"] = (vals[2] + vals[-1] if len(vals) > 4 else vals[2]) * unit
        elif p[0].lower() == "swap:" and len(p) >= 4:
            vals = [to_int(x) or 0 for x in p[1:4]]
            mem.update(swap_total=vals[0] * unit, swap_used=vals[1] * unit, swap_free=vals[2] * unit)
    return mem


def parse_meminfo(text: str) -> dict[str, Any]:
    kv = {}
    for l in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)\s*kB", l)
        if m:
            kv[m.group(1)] = int(m.group(2)) * 1024
    if "MemTotal" not in kv:
        return {}
    avail = kv.get("MemAvailable", kv.get("MemFree", 0) + kv.get("Buffers", 0) + kv.get("Cached", 0))
    return {"total": kv["MemTotal"], "free": kv.get("MemFree", 0), "available": avail,
            "used": kv["MemTotal"] - avail, "swap_total": kv.get("SwapTotal", 0),
            "swap_used": kv.get("SwapTotal", 0) - kv.get("SwapFree", 0)}


def parse_lscpu(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for l in text.splitlines():
        if ":" not in l:
            continue
        k, _, v = l.partition(":")
        k, v = k.strip(), v.strip()
        if k == "CPU(s)":
            out["cpus"] = to_int(v)
        elif k == "Model name":
            out["model"] = v
        elif k == "Thread(s) per core":
            out["threads_per_core"] = to_int(v)
        elif k == "Core(s) per socket":
            out["cores_per_socket"] = to_int(v)
        elif k == "Socket(s)":
            out["sockets"] = to_int(v)
    return out


def parse_cpuinfo(text: str) -> dict[str, Any]:
    n = len(re.findall(r"^processor\s*:", text, re.M))
    m = re.search(r"^model name\s*:\s*(.+)$", text, re.M)
    return {"cpus": n or None, "model": m.group(1).strip() if m else None}


def parse_uptime(text: str) -> dict[str, Any]:
    m = re.search(r"load average[s]?:\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)", text)
    up = re.search(r"up\s+(.+?),\s+\d+\s+user", text)
    return {"load": [float(m.group(i)) for i in (1, 2, 3)] if m else None, "uptime": up.group(1).strip() if up else None}


def parse_top(text: str) -> dict[str, Any]:
    """Parse the first (or last) iteration of ``top -b`` output."""
    out: dict[str, Any] = {"processes": []}
    blocks = re.split(r"(?m)^top - ", text)
    block = blocks[-1] if len(blocks) > 1 else text
    m = re.search(r"load average[s]?:\s*([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)", block)
    if m:
        out["load"] = [float(m.group(i)) for i in (1, 2, 3)]
    m = re.search(r"%?Cpu\(s\):\s*([\d.]+)\s*us,\s*([\d.]+)\s*sy,.*?([\d.]+)\s*id,\s*([\d.]+)\s*wa", block)
    if m:
        out["cpu"] = {"user": float(m.group(1)), "system": float(m.group(2)), "idle": float(m.group(3)), "iowait": float(m.group(4))}
    header = None
    for l in block.splitlines():
        if re.match(r"^\s*PID\s+USER", l):
            header = l.split()
            continue
        if header and l.strip() and re.match(r"^\s*\d+\s", l):
            p = l.split(None, len(header) - 1)
            if len(p) < len(header):
                continue
            rec = dict(zip(header, p))
            out["processes"].append({
                "pid": to_int(rec.get("PID")), "user": rec.get("USER"),
                "cpu": to_float(rec.get("%CPU"), 0.0), "mem": to_float(rec.get("%MEM"), 0.0),
                "res_kb": _top_mem(rec.get("RES")), "command": (rec.get("COMMAND") or "").strip()})
    return out


def _top_mem(v: str | None) -> int | None:
    if not v:
        return None
    m = re.match(r"^([\d.]+)([kmgt]?)$", v.strip(), re.I)
    if not m:
        return to_int(v)
    mult = {"": 1, "k": 1, "m": 1024, "g": 1024**2, "t": 1024**3}[m.group(2).lower()]
    return int(float(m.group(1)) * mult)


def parse_ps(text: str) -> dict[str, Any]:
    """Parse ``ps aux`` / ``ps -ef`` style output."""
    procs: list[dict[str, Any]] = []
    header = None
    for l in text.splitlines():
        if re.match(r"^\s*USER\s+PID", l):
            header = l.split()
            continue
        if not header or not l.strip():
            continue
        p = l.split(None, len(header) - 1)
        if len(p) < len(header):
            continue
        rec = dict(zip(header, p))
        procs.append({"user": rec.get("USER"), "pid": to_int(rec.get("PID")), "cpu": to_float(rec.get("%CPU"), 0.0),
                      "mem": to_float(rec.get("%MEM"), 0.0), "rss_kb": to_int(rec.get("RSS")),
                      "command": rec.get("COMMAND", "").strip(), "stat": rec.get("STAT", ""), "start": rec.get("START")})
    httpd = sum(1 for p in procs if re.search(r"\bhttpd\b", p["command"]))
    zombies = sum(1 for p in procs if p["stat"].startswith("Z"))
    return {"processes": procs, "httpd_count": httpd, "zombies": zombies}


_VER_RE = re.compile(r"\b(7\.[2-9]\.\d+)(?:[.\-_ ]?(\d{8,14}))?")


def find_version_info(text: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    m = re.search(r"(?:qradar|version|release)[^\n]{0,40}?\b(7\.\d\.\d+)(?:\.(\d{8,14}))?", text, re.I) or _VER_RE.search(text)
    if m:
        info["version"] = m.group(1)
        if m.lastindex and m.lastindex >= 2 and m.group(2):
            info["build"] = m.group(2)
    fp = re.search(r"\b(?:Update\s*Package|UP|Fix\s*Pack|FP)\s*[-_ ]?(\d+)(?:\s*(?:IF|Interim\s*Fix)\s*[-_ ]?(\d+))?", text, re.I)
    if fp:
        info["fix_pack"] = f"{m.group(1)} UP{fp.group(1)}" if m else f"UP{fp.group(1)}"
        if fp.group(2):
            info["fix_pack"] += f" IF{fp.group(2)}"
    inst = re.search(r"\b(ISO|RPM|appliance|software\s+install|virtual|VMware|AWS|Azure|IBM\s+Cloud)\b", text, re.I)
    if inst:
        info["install_hint"] = inst.group(1)
    return info


def parse_os_release(text: str) -> str | None:
    m = re.search(r'PRETTY_NAME="?([^"\n]+)"?', text)
    if m:
        return m.group(1)
    m = re.search(r"(Red Hat Enterprise Linux[^\n]*|CentOS[^\n]*)", text)
    return m.group(1) if m else None
