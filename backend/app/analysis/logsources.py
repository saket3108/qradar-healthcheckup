"""Log source + WinCollect + application analysis."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from app.analysis import kb

PROTOCOL_ORDER = ["Syslog", "TCP", "UDP", "TLS", "SNMP", "JDBC", "WinCollect", "AWS", "Azure", "Office365", "SFTP",
                  "OPSEC", "LEEF", "REST API", "Universal DSM", "Other"]


def _dt(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


def analyse_log_sources(sources: list[dict[str, Any]], now: datetime | None = None, silent_hours: int = 24) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    st = Counter(s["status"] for s in sources)
    total_eps = sum(s["eps"] for s in sources)
    proto = defaultdict(lambda: {"count": 0, "eps": 0.0})
    types = defaultdict(lambda: {"count": 0, "eps": 0.0})
    problematic: list[dict[str, Any]] = []
    for s in sources:
        p = proto[s["protocol_group"]]
        p["count"] += 1
        p["eps"] += s["eps"]
        t = types[s["type"]]
        t["count"] += 1
        t["eps"] += s["eps"]
        le = _dt(s.get("last_event"))
        age_h = (now - le).total_seconds() / 3600 if le else None
        reasons = []
        if s["status"] == "error":
            reasons.append("Status ERROR" + (f" ({s['status_raw']})" if s.get("status_raw") else ""))
        if s["status"] == "enabled" and age_h is not None and age_h > silent_hours:
            reasons.append(f"No events for {age_h / 24:.1f} days")
        if s["status"] == "enabled" and le is None and s["eps"] == 0:
            reasons.append("Enabled but never reported events")
        if s["status"] == "unknown":
            reasons.append("Status unknown")
        if reasons:
            problematic.append({"id": s["id"], "name": s["name"], "type": s["type"], "protocol": s["protocol"], "status": s["status"],
                                "eps": s["eps"], "last_event": s.get("last_event"), "reasons": reasons,
                                "severity": "high" if s["status"] == "error" else "medium"})
    top = sorted(sources, key=lambda s: s["eps"], reverse=True)[:15]
    enabled = [s for s in sources if s["status"] in ("enabled", "error")]
    protocols = [{"name": n, "count": proto[n]["count"], "eps": round(proto[n]["eps"], 2)} for n in PROTOCOL_ORDER if n in proto]
    types_sorted = sorted(({"name": k, "count": v["count"], "eps": round(v["eps"], 2)} for k, v in types.items()), key=lambda x: (-x["eps"], -x["count"]))
    return {
        "total": len(sources), "enabled": st.get("enabled", 0), "disabled": st.get("disabled", 0), "error": st.get("error", 0),
        "unknown": st.get("unknown", 0), "total_eps": round(total_eps, 2),
        "average_eps": round(total_eps / len(enabled), 2) if enabled else 0.0,
        "top_eps": [{"name": s["name"], "type": s["type"], "eps": s["eps"], "protocol": s["protocol"]} for s in top],
        "protocols": protocols, "types": types_sorted[:40],
        "problematic": sorted(problematic, key=lambda p: (p["severity"] != "high", -p["eps"])),
        "silent_count": sum(1 for p in problematic if any("No events" in r or "never" in r for r in p["reasons"])),
        "unparsed_types": sum(v["count"] for k, v in types.items() if re.search(r"unknown|stored|sim generic|generic", k, re.I)),
    }


_VER_RE = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?")


def _ver_tuple(v: str | None) -> tuple[int, ...]:
    m = _VER_RE.search(v or "")
    return tuple(int(x) for x in m.groups(default="0")) if m else (0,)


def analyse_wincollect(agents: list[dict[str, Any]], sources: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    wc_sources = [s for s in sources if s.get("wincollect")]
    versions = Counter((a.get("version") or "unknown") for a in agents)
    latest = max((_ver_tuple(a.get("version")) for a in agents), default=(0,))
    # a supported baseline: anything older than 10.x is legacy; also behind newest seen by 2 minors
    def outdated(a: dict[str, Any]) -> bool:
        v = _ver_tuple(a.get("version"))
        return bool(a.get("version")) and (v < (10, 0) or (len(latest) >= 2 and v[:2] < latest[:2] and (latest[0] - v[0]) * 100 + (latest[1] - v[1] if len(v) > 1 and len(latest) > 1 else 0) >= 2))
    old = [a for a in agents if outdated(a)]
    disc = [a for a in agents if a["status"] == "disconnected"]
    stale = []
    for a in agents:
        ci = _dt(a.get("last_checkin"))
        if ci and (now - ci).total_seconds() > 48 * 3600 and a["status"] != "disconnected":
            stale.append(a)
    errors = [a for a in agents if a["status"] == "error"]
    cfg = [a for a in agents if a.get("config_error")]
    no_dest = [a for a in agents if a["managed"] and not a.get("destination")]
    managed = [a for a in agents if a["mode"] == "managed"]
    standalone = [a for a in agents if a["mode"] == "standalone"]
    unmanaged = [a for a in agents if a["mode"] == "unknown"]
    return {
        "total": len(agents), "managed": len(managed), "standalone": len(standalone), "unmanaged": len(unmanaged),
        "disconnected": len(disc) + len(stale), "error": len(errors), "outdated": len(old), "connected": sum(1 for a in agents if a["status"] == "connected"),
        "wincollect_log_sources": len(wc_sources),
        "versions": [{"version": k, "count": v} for k, v in sorted(versions.items(), key=lambda kv: _ver_tuple(kv[0]), reverse=True)],
        "latest_seen": ".".join(map(str, latest)) if latest != (0,) else None,
        "old_versions": [_slim(a) for a in old],
        "communication_problems": [_slim(a, "Disconnected") for a in disc] + [_slim(a, "No check-in for >48h") for a in stale],
        "config_issues": [_slim(a, str(a.get("config_error"))[:160]) for a in cfg] + [_slim(a, "Error state") for a in errors],
        "deployment_problems": [_slim(a, "Managed agent has no event destination") for a in no_dest],
        "agents": agents[:2000],
    }


def _slim(a: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    return {"id": a["id"], "name": a["name"], "ip": a.get("ip"), "version": a.get("version"), "status": a["status"], "mode": a["mode"],
            "last_checkin": a.get("last_checkin"), "reason": reason}


# ---------------------------------------------------------------------------
LATEST_UNKNOWN = "latest"


def analyse_applications(apps: list[dict[str, Any]], df_by_host: dict[str, float] | None = None) -> dict[str, Any]:
    from app.analysis.logsources import _ver_tuple as vt

    st = Counter(a["status"] for a in apps)
    items = []
    latest_by_name: dict[str, tuple[int, ...]] = {}
    for a in apps:
        latest_by_name[a["name"]] = max(latest_by_name.get(a["name"], (0,)), vt(a.get("version")))
    for a in apps:
        issues: list[dict[str, Any]] = []
        rc = a.get("restart_count") or 0
        err = str(a.get("last_error") or "")
        if rc >= 5 or (rc >= 3 and a["status"] in ("degraded", "error")):
            issues.append(_issue("APP_RESTART_LOOP", f"Container restarted {rc} times", "high" if rc >= 10 else "medium"))
        if a.get("latest_version") and vt(a["latest_version"]) > vt(a.get("version")):
            issues.append(_issue("APP_OUTDATED", f"Installed {a.get('version')} - latest available {a['latest_version']}", "low"))
        elif a.get("version") and vt(a["version"]) < latest_by_name[a["name"]]:
            issues.append(_issue("APP_OUTDATED", f"Installed {a.get('version')} - other instances run newer", "low"))
        if (a.get("memory_pct") or 0) >= 85 or re.search(r"out of memory|oom|137|memory", err, re.I):
            issues.append(_issue("APP_MEMORY", f"Memory at {a.get('memory_pct') or 0:.0f}% of limit" if a.get("memory_pct") else "Memory related error: " + err[:100], "high" if (a.get("memory_pct") or 0) >= 95 or "oom" in err.lower() else "medium"))
        du, dl = a.get("disk_used_bytes"), a.get("disk_limit_bytes")
        if (du and dl and du / dl >= 0.85) or re.search(r"no space|disk full|volume.*full|read-only file", err, re.I):
            issues.append(_issue("APP_STORAGE", "Application volume nearly full" if du and dl else "Storage error: " + err[:100], "high"))
        if re.search(r"permission denied|unauthori[sz]ed|forbidden|\b40[13]\b|token", err, re.I):
            issues.append(_issue("APP_PERMISSION", "Authorisation/permission error: " + err[:100], "medium"))
        if a["status"] in ("error", "stopped", "degraded") and not issues:
            issues.append(_issue("APP_FRAMEWORK", f"Application is {a['status']}" + (f": {err[:120]}" if err else ""), "high" if a["status"] == "error" else "medium"))
        elif a["status"] == "error" and not any(i["code"] == "APP_FRAMEWORK" for i in issues):
            issues.append(_issue("APP_FRAMEWORK", f"Application in error state" + (f": {err[:120]}" if err else ""), "high"))
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        issues.sort(key=lambda i: sev_rank[i["severity"]])
        obs = "; ".join(i["observation"] for i in issues) if issues else f"Application is {a['status']} with no anomalies detected."
        top = issues[0] if issues else None
        e = kb.BY_CODE[top["code"]] if top else None
        items.append({**a, "issues": issues, "observation": obs, "impact": e.impact if e else "No impact identified",
                      "recommendation": list(e.recommendation) if e else [], "priority": ({"high": "P2", "medium": "P3", "low": "P4"}[top["severity"]] if top else "-"),
                      "best_practice": e.best_practice if e else "", "health": "healthy" if not issues else ("critical" if top["severity"] == "high" else "warning")})
    hosts = Counter(a.get("host") or "unknown" for a in apps)
    return {"items": items, "total": len(items), "running": st.get("running", 0), "stopped": st.get("stopped", 0), "degraded": st.get("degraded", 0),
            "error": st.get("error", 0), "unknown": st.get("unknown", 0), "by_host": dict(hosts),
            "with_issues": sum(1 for i in items if i["issues"]), "restart_loops": sum(1 for i in items if any(x["code"] == "APP_RESTART_LOOP" for x in i["issues"])),
            "outdated": sum(1 for i in items if any(x["code"] == "APP_OUTDATED" for x in i["issues"]))}


def _issue(code: str, observation: str, severity: str) -> dict[str, Any]:
    return {"code": code, "observation": observation, "severity": severity}
