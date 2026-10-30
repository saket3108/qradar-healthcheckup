"""sysstat ``sar`` text report parser (sar -A / -u -r -q -n DEV -n EDEV -d -S -b ...).

Handles 12h/24h clocks, multi-day concatenated reports, ``Average:`` rows, ISO dates and legacy
(`sar -d` sectors vs. newer kB) disk column sets.  Returns time series plus summary statistics.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from app.parsers.common import downsample, mean, percentile, to_float

_TIME_RE = re.compile(r"^(\d{1,2}:\d{2}:\d{2})(?:\s+([AP]M))?\s+(.*)$")
_DATE_RES = [
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "ymd"),
    (re.compile(r"\b(\d{2})/(\d{2})/(\d{2,4})\b"), "mdy"),
]
_NUMERIC = re.compile(r"^-?[\d.]+$")


def _parse_date(line: str) -> datetime | None:
    for rx, kind in _DATE_RES:
        m = rx.search(line)
        if not m:
            continue
        try:
            if kind == "ymd":
                return datetime(int(m[1]), int(m[2]), int(m[3]))
            a, b, y = int(m[1]), int(m[2]), int(m[3])
            y += 2000 if y < 100 else 0
            if a > 12:
                return datetime(y, b, a)
            return datetime(y, a, b)
        except ValueError:
            continue
    return None


def _clock(t: str, ampm: str | None) -> tuple[int, int, int]:
    h, m, s = (int(x) for x in t.split(":"))
    if ampm:
        h = h % 12 + (12 if ampm.upper() == "PM" else 0)
    return h, m, s


def _kind(cols: list[str]) -> str | None:
    c = set(cols)
    if "%user" in c and "%idle" in c:
        return "cpu"
    if "kbmemfree" in c or "kbmemused" in c:
        return "memory"
    if "kbswpfree" in c or "%swpused" in c:
        return "swap"
    if "ldavg-1" in c:
        return "load"
    if "IFACE" in c and ("rxpck/s" in c):
        return "net"
    if "IFACE" in c and ("rxerr/s" in c or "rxdrop/s" in c):
        return "neterr"
    if "DEV" in c and ("await" in c or "r_await" in c or "%util" in c):
        return "disk"
    if "pgpgin/s" in c or "pswpin/s" in c:
        return "paging"
    if "tps" in c and "rtps" in c:
        return "io"
    return None


def parse_sar(text: str) -> dict[str, Any]:
    series: dict[str, list[dict[str, Any]]] = {k: [] for k in ("cpu", "memory", "swap", "load", "net", "neterr", "disk", "paging", "io")}
    cur_date = _parse_date(text[:2000])
    cpus = None
    m = re.search(r"\((\d+)\s+CPU\)", text[:2000])
    if m:
        cpus = int(m.group(1))
    last_clock: tuple[int, int, int] | None = None
    day_offset = 0
    base_date = cur_date

    kind: str | None = None
    cols: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            kind = None
            continue
        if line.startswith("Linux "):
            d = _parse_date(line)
            if d:
                base_date, day_offset, last_clock = d, 0, None
            mm = re.search(r"\((\d+)\s+CPU\)", line)
            if mm:
                cpus = int(mm.group(1))
            kind = None
            continue
        if line.startswith(("Average:", "Summary:")):
            continue
        tm = _TIME_RE.match(line)
        if not tm:
            continue
        clock = _clock(tm.group(1), tm.group(2))
        rest = tm.group(3).split()
        if rest and not all(_NUMERIC.match(x) or x in ("all",) for x in rest[:1]) and any(x.startswith(("%", "kb", "rx", "tx", "ldavg", "runq", "DEV", "IFACE", "CPU", "tps", "pgp", "psw")) for x in rest):
            cols = rest
            kind = _kind(cols)
            continue
        if kind is None or not cols:
            continue
        if last_clock and clock < last_clock and (last_clock[0] - clock[0]) >= 12:
            day_offset += 1
        last_clock = clock
        if base_date is None:
            base_date = datetime(2000, 1, 1)
        ts = base_date + timedelta(days=day_offset, hours=clock[0], minutes=clock[1], seconds=clock[2])
        vals = rest
        # CPU / DEV / IFACE rows carry a leading label column
        rec: dict[str, Any] = {"ts": ts.isoformat()}
        if len(vals) != len(cols):
            continue
        for c, v in zip(cols, vals):
            rec[c] = to_float(v) if _NUMERIC.match(v) else v
        series[kind].append(rec)

    return _summarise(series, cpus)


def _col(rows: list[dict], *names: str) -> list[float]:
    out = []
    for r in rows:
        for n in names:
            if n in r and isinstance(r[n], (int, float)):
                out.append(float(r[n]))
                break
    return out


def _summarise(series: dict[str, list[dict]], cpus: int | None) -> dict[str, Any]:
    out: dict[str, Any] = {"cpus": cpus, "series": {}, "summary": {}, "disks": {}, "interfaces": {}}
    # --- CPU ---
    cpu_rows = [r for r in series["cpu"] if r.get("CPU") in ("all", None, -1.0)]
    if cpu_rows:
        used = [100.0 - r["%idle"] for r in cpu_rows if "%idle" in r]
        out["series"]["cpu"] = downsample([{"ts": r["ts"], "user": r.get("%user"), "system": r.get("%system"),
                                            "iowait": r.get("%iowait"), "steal": r.get("%steal"),
                                            "used": 100.0 - r.get("%idle", 100.0)} for r in cpu_rows])
        out["summary"]["cpu"] = {"avg": mean(used), "max": max(used), "p95": percentile(used, 0.95),
                                 "iowait_avg": mean(_col(cpu_rows, "%iowait")), "iowait_max": max(_col(cpu_rows, "%iowait") or [0]),
                                 "steal_avg": mean(_col(cpu_rows, "%steal")),
                                 "saturation_pct": 100.0 * sum(1 for u in used if u >= 90) / len(used)}
    # --- memory ---
    if series["memory"]:
        rows = series["memory"]
        pts, usedp = [], []
        for r in rows:
            if "%memused" in r:
                u = r["%memused"]
            else:
                tot = (r.get("kbmemfree", 0) + r.get("kbmemused", 0))
                u = 100.0 * r.get("kbmemused", 0) / tot if tot else 0
            if "kbavail" in r and (r.get("kbmemfree", 0) + r.get("kbmemused", 0)):
                tot = r.get("kbmemfree", 0) + r.get("kbmemused", 0)
                u = 100.0 * (tot - r["kbavail"]) / tot
            usedp.append(u)
            pts.append({"ts": r["ts"], "used_pct": u, "free_kb": r.get("kbmemfree"), "cached_kb": r.get("kbcached"),
                        "buffers_kb": r.get("kbbuffers"), "avail_kb": r.get("kbavail")})
        out["series"]["memory"] = downsample(pts)
        out["summary"]["memory"] = {"avg": mean(usedp), "max": max(usedp), "p95": percentile(usedp, 0.95),
                                    "min_avail_kb": min([p["avail_kb"] for p in pts if p["avail_kb"] is not None] or [0]) or None}
    # --- swap ---
    if series["swap"]:
        pts = [{"ts": r["ts"], "used_pct": r.get("%swpused", 0.0), "used_kb": r.get("kbswpused")} for r in series["swap"]]
        out["series"]["swap"] = downsample(pts)
        out["summary"]["swap"] = {"avg": mean(p["used_pct"] for p in pts), "max": max(p["used_pct"] for p in pts)}
    # --- load ---
    if series["load"]:
        pts = [{"ts": r["ts"], "l1": r.get("ldavg-1"), "l5": r.get("ldavg-5"), "l15": r.get("ldavg-15"),
                "runq": r.get("runq-sz"), "tasks": r.get("plist-sz")} for r in series["load"]]
        out["series"]["load"] = downsample(pts)
        out["summary"]["load"] = {"avg1": mean(p["l1"] for p in pts), "max1": max(p["l1"] or 0 for p in pts),
                                  "avg5": mean(p["l5"] for p in pts), "max5": max(p["l5"] or 0 for p in pts),
                                  "max_runq": max(p["runq"] or 0 for p in pts)}
    # --- paging ---
    if series["paging"]:
        out["summary"]["paging"] = {"swapin_max": max(_col(series["paging"], "pswpin/s") or [0]),
                                    "swapout_max": max(_col(series["paging"], "pswpout/s") or [0]),
                                    "majflt_max": max(_col(series["paging"], "majflt/s") or [0])}
    # --- network ---
    by_if: dict[str, dict[str, list]] = {}
    for r in series["net"]:
        iface = str(r.get("IFACE"))
        if iface in ("lo",):
            continue
        by_if.setdefault(iface, {"net": [], "err": []})["net"].append(r)
    for r in series["neterr"]:
        iface = str(r.get("IFACE"))
        if iface in ("lo",):
            continue
        by_if.setdefault(iface, {"net": [], "err": []})["err"].append(r)
    for iface, d in by_if.items():
        net, err = d["net"], d["err"]
        in_kb = _col(net, "rxkB/s", "rxbyt/s")
        out_kb = _col(net, "txkB/s", "txbyt/s")
        if net and "rxbyt/s" in net[0] and "rxkB/s" not in net[0]:
            in_kb = [x / 1024 for x in in_kb]
            out_kb = [x / 1024 for x in out_kb]
        out["interfaces"][iface] = {
            "rx_kBps_avg": mean(in_kb), "rx_kBps_max": max(in_kb or [0]),
            "tx_kBps_avg": mean(out_kb), "tx_kBps_max": max(out_kb or [0]),
            "rx_pps_avg": mean(_col(net, "rxpck/s")), "tx_pps_avg": mean(_col(net, "txpck/s")),
            "rx_err_max": max(_col(err, "rxerr/s") or [0]), "tx_err_max": max(_col(err, "txerr/s") or [0]),
            "rx_drop_max": max(_col(err, "rxdrop/s") or [0]), "tx_drop_max": max(_col(err, "txdrop/s") or [0]),
            "coll_max": max(_col(err, "coll/s") or [0]),
            "series": downsample([{"ts": r["ts"], "rx_kBps": (r.get("rxkB/s") if "rxkB/s" in r else (r.get("rxbyt/s", 0) / 1024)),
                                   "tx_kBps": (r.get("txkB/s") if "txkB/s" in r else (r.get("txbyt/s", 0) / 1024)),
                                   "rx_pps": r.get("rxpck/s"), "tx_pps": r.get("txpck/s")} for r in net], 144),
        }
    if out["interfaces"]:
        out["summary"]["network"] = {
            "rx_kBps_avg": sum(v["rx_kBps_avg"] or 0 for v in out["interfaces"].values()),
            "tx_kBps_avg": sum(v["tx_kBps_avg"] or 0 for v in out["interfaces"].values()),
            "errors_max": max(max(v["rx_err_max"], v["tx_err_max"]) for v in out["interfaces"].values()),
            "drops_max": max(max(v["rx_drop_max"], v["tx_drop_max"]) for v in out["interfaces"].values()),
        }
        top_if = max(out["interfaces"].items(), key=lambda kv: (kv[1]["rx_kBps_avg"] or 0) + (kv[1]["tx_kBps_avg"] or 0))[0]
        out["series"]["network"] = out["interfaces"][top_if]["series"]
        out["summary"]["network"]["primary_iface"] = top_if
    # --- disk ---
    by_dev: dict[str, list[dict]] = {}
    for r in series["disk"]:
        by_dev.setdefault(str(r.get("DEV")), []).append(r)
    for dev, rows in by_dev.items():
        sec = "rd_sec/s" in rows[0]
        rd = _col(rows, "rkB/s") or [x / 2 for x in _col(rows, "rd_sec/s")]
        wr = _col(rows, "wkB/s") or [x / 2 for x in _col(rows, "wr_sec/s")]
        out["disks"][dev] = {
            "tps_avg": mean(_col(rows, "tps")), "read_kBps_avg": mean(rd), "write_kBps_avg": mean(wr),
            "read_kBps_max": max(rd or [0]), "write_kBps_max": max(wr or [0]),
            "avgrq_sz": mean(_col(rows, "avgrq-sz", "areq-sz")), "avgqu_sz": mean(_col(rows, "avgqu-sz", "aqu-sz")),
            "avgqu_sz_max": max(_col(rows, "avgqu-sz", "aqu-sz") or [0]),
            "await_avg": mean(_col(rows, "await")), "await_max": max(_col(rows, "await") or [0]),
            "await_p95": percentile(_col(rows, "await"), 0.95),
            "r_await_avg": mean(_col(rows, "r_await")), "w_await_avg": mean(_col(rows, "w_await")),
            "r_await_max": max(_col(rows, "r_await") or [0]), "w_await_max": max(_col(rows, "w_await") or [0]),
            "svctm_avg": mean(_col(rows, "svctm")), "util_avg": mean(_col(rows, "%util")),
            "util_max": max(_col(rows, "%util") or [0]), "legacy_sectors": sec,
            "series": downsample([{"ts": r["ts"], "await": r.get("await"), "util": r.get("%util"),
                                   "read_kBps": (r["rkB/s"] if "rkB/s" in r else r.get("rd_sec/s", 0) / 2),
                                   "write_kBps": (r["wkB/s"] if "wkB/s" in r else r.get("wr_sec/s", 0) / 2),
                                   "queue": r.get("avgqu-sz", r.get("aqu-sz"))} for r in rows], 144),
        }
    if out["disks"]:
        worst = max(out["disks"].items(), key=lambda kv: kv[1]["await_avg"] or 0)
        out["summary"]["disk"] = {"worst_device": worst[0], "await_avg": worst[1]["await_avg"], "await_max": worst[1]["await_max"],
                                  "util_max": max(d["util_max"] for d in out["disks"].values()),
                                  "devices": len(out["disks"])}
        out["series"]["disk"] = worst[1]["series"]
    out["samples"] = {k: len(v) for k, v in series.items() if v}
    return out
