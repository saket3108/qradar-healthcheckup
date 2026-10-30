"""Performance analysis: per-host metric assessment (finding / risk / root cause / recommendation / priority)."""
from __future__ import annotations

from typing import Any

from app.analysis import kb

SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "ok": 0, "info": 0}


def _a(host: str, metric: str, label: str, value: Any, unit: str, sev: str, code: str | None, finding: str,
       root_cause: str, extra_reco: list[str] | None = None, threshold: str = "") -> dict[str, Any]:
    entry = kb.BY_CODE.get(code) if code else None
    prio = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4", "ok": "-", "info": "-"}[sev]
    if entry and sev != "ok":
        prio = entry.priority if SEV_RANK[sev] >= SEV_RANK.get(entry.severity, 2) else prio
    reco = list(entry.recommendation) if entry and sev != "ok" else []
    if extra_reco and sev != "ok":
        reco = extra_reco + reco
    return {
        "key": f"{host}:{metric}", "host": host, "metric": metric, "label": label, "value": value, "unit": unit,
        "severity": sev, "status": "ok" if sev in ("ok", "info") else sev, "code": code if sev not in ("ok", "info") else None,
        "finding": finding, "risk": (entry.risk if entry and sev != "ok" else "No material risk"),
        "impact": entry.impact if entry and sev != "ok" else "No impact identified",
        "root_cause": root_cause if sev != "ok" else "Within expected operating range",
        "recommendation": reco, "priority": prio, "threshold": threshold,
        "best_practice": entry.best_practice if entry else "",
    }


def assess_host(host: str, perf: dict[str, Any], cpus: int | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    sar = perf.get("sar") or {}
    summ = sar.get("summary") or {}
    cpus = cpus or sar.get("cpus") or perf.get("cpus")

    cpu = summ.get("cpu")
    if cpu:
        avg, p95, mx, sat = cpu["avg"], cpu.get("p95") or 0, cpu["max"], cpu.get("saturation_pct", 0)
        sev = "critical" if avg >= 90 or sat >= 25 else "high" if avg >= 80 or sat >= 10 else "medium" if avg >= 70 or p95 >= 90 else "ok"
        out.append(_a(host, "cpu_utilisation", "CPU utilisation", round(avg, 1), "%", sev, "CPU_HIGH",
                      f"Average CPU {avg:.1f}% (p95 {p95:.1f}%, peak {mx:.1f}%); saturated (>=90%) in {sat:.1f}% of samples.",
                      "Event processing (ecs-ep / ecs-ec-ingress), Ariel searches, CRE rule evaluation or application containers are consuming available CPU capacity.",
                      threshold="warn >=70% avg, high >=80%, critical >=90%"))
        iw, iwm = cpu.get("iowait_avg") or 0, cpu.get("iowait_max") or 0
        sev = "high" if iw >= 15 else "medium" if iw >= 8 or iwm >= 40 else "ok"
        out.append(_a(host, "cpu_iowait", "CPU I/O wait", round(iw, 1), "%", sev, "CPU_IOWAIT",
                      f"Average I/O wait {iw:.1f}% (peak {iwm:.1f}%).",
                      "CPU threads are blocked waiting for storage; usually slow disks, heavy Ariel searches or retention/cleanup jobs.", threshold="warn >=8%, high >=15%"))
        steal = cpu.get("steal_avg") or 0
        if steal >= 3:
            out.append(_a(host, "cpu_steal", "CPU steal (virtualisation)", round(steal, 1), "%", "high" if steal >= 10 else "medium", "CPU_HIGH",
                          f"Hypervisor steal time averages {steal:.1f}%.", "The VM is not receiving its entitled CPU from the hypervisor (over-subscribed host).",
                          ["Reserve CPU for the QRadar VM and avoid host over-commit."], "warn >=3%"))
    elif perf.get("top", {}).get("cpu"):
        c = perf["top"]["cpu"]
        used = 100 - c["idle"]
        sev = "critical" if used >= 90 else "high" if used >= 80 else "medium" if used >= 70 else "ok"
        out.append(_a(host, "cpu_utilisation", "CPU utilisation (top snapshot)", round(used, 1), "%", sev, "CPU_HIGH",
                      f"Snapshot CPU usage {used:.1f}% (iowait {c['iowait']:.1f}%).", "Busy processes consuming CPU at capture time.", threshold="warn >=70%"))

    mem = summ.get("memory")
    mem_snapshot = perf.get("memory") or {}
    if mem:
        avg, mx = mem["avg"], mem["max"]
        sev = "critical" if mx >= 98 else "high" if avg >= 92 or mx >= 96 else "medium" if avg >= 85 else "ok"
        out.append(_a(host, "memory_utilisation", "Memory utilisation", round(avg, 1), "%", sev, "MEMORY_PRESSURE",
                      f"Memory (excluding cache) averages {avg:.1f}%, peaking at {mx:.1f}%.",
                      "Large resident sets from Java (tomcat/ecs), PostgreSQL shared buffers or application containers; insufficient RAM for the assigned roles.",
                      threshold="warn >=85% avg, high >=92%"))
    elif mem_snapshot.get("total"):
        avail_pct = 100.0 * mem_snapshot.get("available", mem_snapshot["free"]) / mem_snapshot["total"]
        sev = "critical" if avail_pct < 3 else "high" if avail_pct < 7 else "medium" if avail_pct < 12 else "ok"
        out.append(_a(host, "memory_utilisation", "Memory availability (snapshot)", round(100 - avail_pct, 1), "%", sev, "MEMORY_PRESSURE",
                      f"Available memory is {avail_pct:.1f}% of total.", "Resident memory of services exceeds comfortable headroom.", threshold="warn <12% available"))
    swap = summ.get("swap")
    swap_pct = swap["avg"] if swap else (100.0 * mem_snapshot["swap_used"] / mem_snapshot["swap_total"] if mem_snapshot.get("swap_total") else None)
    paging = summ.get("paging") or {}
    if swap_pct is not None:
        so = paging.get("swapout_max", 0)
        sev = "high" if swap_pct >= 30 or so >= 100 else "medium" if swap_pct >= 5 or so > 0 else "ok"
        out.append(_a(host, "swap_usage", "Swap usage", round(swap_pct, 1), "%", sev, "SWAP_USAGE",
                      f"Swap utilisation {swap_pct:.1f}%" + (f"; swap-out peak {so:.0f} pages/s." if so else "."),
                      "Memory demand exceeded physical RAM, forcing the kernel to page out.", threshold="warn >=5%"))

    load = summ.get("load")
    ld = (load or {}).get("avg5")
    if ld is None and perf.get("uptime", {}).get("load"):
        ld = perf["uptime"]["load"][1]
    elif ld is None and perf.get("top", {}).get("load"):
        ld = perf["top"]["load"][1]
    if ld is not None and cpus:
        ratio = ld / cpus
        sev = "high" if ratio >= 2 else "medium" if ratio >= 1 else "ok"
        out.append(_a(host, "load_average", "Load average (5 min)", round(ld, 2), "", sev, "LOAD_HIGH",
                      f"5-minute load average {ld:.2f} on {cpus} CPUs (ratio {ratio:.2f}).",
                      "More runnable/blocked tasks than CPU cores; CPU or I/O contention.", threshold="warn load/core >=1, high >=2"))

    httpd = perf.get("httpd_count")
    if httpd is not None:
        sev = "high" if httpd >= 80 else "medium" if httpd >= 40 else "ok"
        out.append(_a(host, "httpd_count", "httpd worker count", httpd, "procs", sev, "HTTPD_COUNT",
                      f"{httpd} httpd processes running.", "Heavy concurrent UI/API/app-proxy requests or slow backend responses holding workers open.", threshold="warn >=40"))

    for fs in perf.get("df") or []:
        mount = fs["mount"]
        if mount.startswith(("/dev", "/sys", "/proc", "/run")) or fs.get("size_bytes") in (0, None):
            continue
        pct = fs["use_pct"]
        crit_mount = mount in ("/", "/store", "/storetmp", "/var/log", "/transient", "/var", "/opt", "/store/ariel/events", "/store/ariel/flows")
        sev = "critical" if pct >= 95 else "high" if pct >= 90 else "medium" if pct >= 80 else "ok"
        if sev == "medium" and not crit_mount and pct < 85:
            sev = "ok"
        out.append(_a(host, f"disk_usage:{mount}", f"Disk usage {mount}", pct, "%", sev, "DISK_CAPACITY",
                      f"{mount} is {pct:.0f}% full ({_gb(fs.get('used_bytes'))} of {_gb(fs.get('size_bytes'))}).",
                      "Ariel data retention, backups, temporary files, core dumps or application volumes have filled the file system.",
                      threshold="warn >=80%, high >=90%, critical >=95%"))

    for dev, d in (sar.get("disks") or {}).items():
        aw, awm = d.get("await_avg") or 0, d.get("await_max") or 0
        sev = "critical" if aw >= 50 else "high" if aw >= 20 else "medium" if aw >= 10 or (d.get("await_p95") or 0) >= 30 else "ok"
        out.append(_a(host, f"disk_await:{dev}", f"Disk await {dev}", round(aw, 1), "ms", sev, "DISK_LATENCY",
                      f"Storage latency on {dev}: await avg {aw:.1f} ms (peak {awm:.0f} ms); r_await {d.get('r_await_avg') or 0:.1f} ms, w_await {d.get('w_await_avg') or 0:.1f} ms; avgqu-sz {d.get('avgqu_sz') or 0:.2f}.",
                      "Storage subsystem cannot service request queue fast enough (shared SAN latency, RAID rebuild, saturated spindles, noisy neighbours or heavy Ariel searches).",
                      threshold="warn >=10 ms, high >=20 ms, critical >=50 ms"))
        util = d.get("util_max") or 0
        if util >= 90:
            out.append(_a(host, f"disk_util:{dev}", f"Disk utilisation {dev}", round(util, 1), "%", "high" if (d.get('util_avg') or 0) >= 60 else "medium", "DISK_LATENCY",
                          f"{dev} reached {util:.0f}% utilisation (avg {d.get('util_avg') or 0:.0f}%).", "Device is saturated by sequential Ariel writes or concurrent searches.", threshold="warn peak >=90%"))

    net = sar.get("interfaces") or {}
    for iface, n in net.items():
        errs = max(n.get("rx_err_max", 0), n.get("tx_err_max", 0))
        drops = max(n.get("rx_drop_max", 0), n.get("tx_drop_max", 0))
        sev = "high" if errs >= 5 or drops >= 50 else "medium" if errs > 0 or drops > 0 else "ok"
        out.append(_a(host, f"network:{iface}", f"Network {iface}", round(max(errs, drops), 2), "pkts/s", sev, "NETWORK_ERRORS",
                      f"{iface}: errors peak {errs:.2f}/s, drops peak {drops:.2f}/s, avg rx {n.get('rx_kBps_avg') or 0:.0f} kB/s, tx {n.get('tx_kBps_avg') or 0:.0f} kB/s.",
                      "NIC/driver issues, duplex mismatch, receive buffer overruns or congested uplinks.", threshold="warn any errors/drops"))
    return out


def top_processes(perf: dict[str, Any], key: str, n: int = 10) -> list[dict[str, Any]]:
    procs = (perf.get("top") or {}).get("processes") or (perf.get("ps") or {}).get("processes") or []
    field = "cpu" if key == "cpu" else "mem"
    agg: dict[str, dict[str, Any]] = {}
    for p in procs:
        cmd = (p.get("command") or "").split()[0].split("/")[-1][:60] or "?"
        a = agg.setdefault(cmd, {"command": cmd, "cpu": 0.0, "mem": 0.0, "count": 0, "rss_kb": 0})
        a["cpu"] += p.get("cpu") or 0
        a["mem"] += p.get("mem") or 0
        a["count"] += 1
        a["rss_kb"] += p.get("rss_kb") or p.get("res_kb") or 0
    return sorted(agg.values(), key=lambda x: x[field], reverse=True)[:n]


def _gb(b: int | None) -> str:
    return f"{b / 1024**3:.1f} GB" if b else "n/a"
