"""Findings engine: turns parsed + analysed data into KB-mapped findings, scoring and an executive summary."""
from __future__ import annotations

import re
from typing import Any

from app.analysis import kb

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def make_finding(code: str, *, source: str, observation: str, severity: str | None = None, source_ref: str | None = None,
                 evidence: Any = None, hosts: list[str] | None = None, title: str | None = None, category: str | None = None,
                 root_cause: str = "") -> dict[str, Any]:
    e = kb.BY_CODE[code]
    sev = severity or e.severity
    prio = {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4", "info": "P4"}[sev]
    if SEV_ORDER[sev] <= SEV_ORDER.get(e.severity, 2):
        prio = min(prio, e.priority) if e.priority and prio else prio
    return {"code": code, "category": category or e.category, "source": source, "source_ref": source_ref, "severity": sev, "priority": prio,
            "title": title or e.title, "observation": observation, "description": e.description, "root_cause": root_cause or "",
            "impact": e.impact, "business_impact": e.business_impact, "risk": e.risk, "recommendation": list(e.recommendation),
            "best_practice": e.best_practice, "evidence": evidence, "hosts": hosts or [], "status": "open"}


def build_findings(a: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    # ---- notifications -----------------------------------------------------
    notif = a.get("notifications") or {}
    grouped: dict[tuple[str, str], list[dict]] = {}
    for n in notif.get("items", []):
        if n["status"] in ("closed", "resolved", "dismissed"):
            continue
        key = (n.get("kb_code") or "GENERIC_CRITICAL", n["effective_severity"])
        grouped.setdefault(key, []).append(n)
    for (code, sev), items in grouped.items():
        if sev in ("info",) and code == "GENERIC_CRITICAL":
            continue
        if code == "GENERIC_CRITICAL" and sev == "low":
            continue
        first = items[0]
        hosts = sorted({i.get("host") for i in items if i.get("host")})
        entry = kb.BY_CODE[code]
        cat = {"notifications": "notifications"}.get(entry.category, entry.category)
        obs = first["message"][:300] if len(items) == 1 else f"{len(items)} notifications, e.g. \"{first['message'][:200]}\""
        out.append(make_finding(code, source="notification", severity=sev if sev in SEV_ORDER else None, source_ref=first["id"], observation=obs,
                                evidence=[{"id": i["id"], "message": i["message"][:300], "timestamp": i.get("timestamp"), "host": i.get("host")} for i in items[:10]],
                                hosts=hosts, category=cat if cat in ("deployment", "performance", "licensing", "logsources", "applications", "wincollect", "notifications") else "notifications",
                                root_cause=first.get("root_cause", "")))

    # ---- deployment ---------------------------------------------------------
    for c in a.get("deployment_checks", []):
        if c["status"] == "PASS":
            continue
        code = {"connectivity": "DEPLOY_CONNECTIVITY", "ha": "HA_NOT_CONFIGURED" if "No High Availability" in c["detail"] else "HA_FAILOVER",
                "version": "VERSION_MISMATCH"}.get(c["id"], "DEPLOY_CONFIG")
        if c["id"] == "xml" and c["status"] == "WARNING":
            code = "DEPLOY_CONFIG"
        sev = "critical" if c["status"] == "CRITICAL" else "medium"
        if code == "HA_NOT_CONFIGURED":
            sev = "medium"
        out.append(make_finding(code, source="deployment", source_ref=c["id"], severity=sev, observation=f"{c['name']}: {c['detail']}", title=f"{c['name']} - {c['status']}",
                                root_cause=c.get("recommendation", ""), category="deployment"))
    ver = a.get("environment", {}).get("version")
    if ver and re.match(r"7\.[0-4]\.", ver):
        out.append(make_finding("HOST_STALE", source="deployment", source_ref="version", severity="medium" if ver.startswith("7.4") else "high",
                                observation=f"QRadar {ver} is on an older release line; review lifecycle status and plan the upgrade.", category="deployment"))

    # ---- performance ---------------------------------------------------------
    for p in a.get("performance_assessments", []):
        if p["severity"] in ("ok", "info") or not p.get("code"):
            continue
        out.append(make_finding(p["code"], source="performance", source_ref=p["key"], severity=p["severity"],
                                observation=f"[{p['host']}] {p['finding']}", hosts=[p["host"]], title=f"{p['label']} on {p['host']}",
                                root_cause=p["root_cause"], category="performance", evidence={"value": p["value"], "unit": p["unit"], "threshold": p["threshold"]}))

    # ---- licensing -----------------------------------------------------------
    lic = a.get("licensing") or {}
    for m in (lic.get("eps"), lic.get("fpm")):
        if not m or m.get("risk") in (None, "unknown", "low"):
            continue
        pct = m.get("peak_pct") or m.get("consumption_pct") or 0
        code = "LIC_EPS_EXCEEDED" if m["name"] == "EPS" and pct >= 100 else "LIC_FPM_EXCEEDED" if m["name"] == "FPM" and pct >= 100 else "LIC_NEAR_LIMIT"
        sev = {"critical": "critical", "high": "high", "medium": "medium"}[m["risk"]]
        fc = (m.get("forecast") or [{}])[-1]
        obs = f"{m['name']}: licensed {m['licensed']:.0f}, current {m['current'] or 0:.0f}, peak {m['peak'] or 0:.0f} ({pct:.0f}% of licence)."
        if fc.get("pct"):
            obs += f" 12-month forecast {fc['pct']:.0f}%."
        out.append(make_finding(code, source="licensing", source_ref=m["name"], severity=sev, observation=obs, category="licensing",
                                title=f"{m['name']} licence utilisation {pct:.0f}%"))
    if lic.get("expiry_days") is not None and lic["expiry_days"] < 90:
        out.append(make_finding("LIC_EXPIRING", source="licensing", source_ref="expiry", severity="critical" if lic["expiry_days"] < 0 else "high" if lic["expiry_days"] < 30 else "medium",
                                observation=f"Licence expiry in {lic['expiry_days']} days ({lic['expiry']})." if lic["expiry_days"] >= 0 else f"Licence expired {-lic['expiry_days']} days ago.", category="licensing"))

    # ---- log sources ---------------------------------------------------------
    ls = a.get("logsources") or {}
    if ls.get("total"):
        err = ls.get("error", 0)
        if err:
            pct = 100.0 * err / ls["total"]
            out.append(make_finding("DSM_ERRORS", source="logsource", severity="high" if pct >= 5 or err >= 10 else "medium", category="logsources",
                                    observation=f"{err} of {ls['total']} log sources ({pct:.1f}%) are in ERROR state.",
                                    evidence=[p["name"] for p in ls["problematic"] if p["status"] == "error"][:15]))
        if ls.get("silent_count"):
            n = ls["silent_count"]
            out.append(make_finding("LOGSOURCE_NO_EVENTS", source="logsource", severity="high" if n >= 20 else "medium", category="logsources",
                                    observation=f"{n} enabled log source(s) have not sent events within 24 hours.",
                                    evidence=[p["name"] for p in ls["problematic"] if any('No events' in r or 'never' in r for r in p['reasons'])][:15]))
        if ls.get("unparsed_types"):
            n = ls["unparsed_types"]
            out.append(make_finding("PARSING_ERRORS", source="logsource", severity="medium" if n < 10 else "high", category="logsources",
                                    observation=f"{n} log source(s) are typed as Unknown/Generic, indicating missing or incorrect DSM mapping."))
        if ls.get("unknown", 0) / ls["total"] > 0.2:
            out.append(make_finding("DSM_ERRORS", source="logsource", severity="low", category="logsources", title="Log source status not available",
                                    observation=f"{ls['unknown']} log sources have no status information in the export."))

    # ---- wincollect ------------------------------------------------------------
    wc = a.get("wincollect") or {}
    if wc.get("total"):
        if wc["disconnected"] or wc["error"]:
            n = wc["disconnected"] + wc["error"]
            pct = 100.0 * n / wc["total"]
            out.append(make_finding("WINCOLLECT_COMM", source="wincollect", severity="high" if pct >= 10 else "medium", category="wincollect",
                                    observation=f"{n} of {wc['total']} WinCollect agents ({pct:.1f}%) are disconnected, silent or in error.",
                                    evidence=[x["name"] for x in wc["communication_problems"][:15]]))
        if wc["outdated"]:
            pct = 100.0 * wc["outdated"] / wc["total"]
            out.append(make_finding("WINCOLLECT_OUTDATED", source="wincollect", severity="medium" if pct >= 25 else "low", category="wincollect",
                                    observation=f"{wc['outdated']} agent(s) ({pct:.0f}%) run outdated versions; latest seen {wc.get('latest_seen')}.",
                                    evidence=[f"{x['name']} {x['version']}" for x in wc["old_versions"][:15]]))
        if wc["standalone"]:
            out.append(make_finding("WINCOLLECT_STANDALONE", source="wincollect", severity="low", category="wincollect",
                                    observation=f"{wc['standalone']} agent(s) run in standalone mode (unmanaged centrally)."))
        if wc["deployment_problems"] or wc["config_issues"]:
            out.append(make_finding("WINCOLLECT_COMM", source="wincollect", severity="medium", category="wincollect", title="WinCollect configuration / deployment issues",
                                    observation=f"{len(wc['config_issues'])} configuration issue(s) and {len(wc['deployment_problems'])} deployment issue(s) detected.",
                                    evidence=[x["reason"] for x in (wc["config_issues"] + wc["deployment_problems"])[:10]]))

    # ---- applications -----------------------------------------------------------
    for it in (a.get("applications") or {}).get("items", []):
        for iss in it["issues"]:
            out.append(make_finding(iss["code"], source="application", source_ref=it["id"], severity={"high": "high", "medium": "medium", "low": "low"}[iss["severity"]],
                                    observation=f"{it['name']} {it.get('version') or ''} on {it.get('host') or 'unknown host'}: {iss['observation']}", hosts=[str(it.get("host"))] if it.get("host") else [],
                                    category="applications", title=f"{kb.BY_CODE[iss['code']].title}: {it['name']}"))

    # ---- auto update ---------------------------------------------------------------
    au = a.get("autoupdate") or {}
    if au.get("errors") or au.get("repo_reachable") is False:
        out.append(make_finding("AUTOUPDATE_FAILED", source="autoupdate", severity="medium", category="deployment",
                                observation=("Repository unreachable. " if au.get("repo_reachable") is False else "") + (f"Last result: {au.get('last_status')}. " if au.get("last_status") else "") + f"{len(au.get('errors', []))} error(s) recorded.",
                                evidence=[e.get("message") for e in au.get("errors", [])[:5]]))
    elif au.get("pending_updates"):
        out.append(make_finding("AUTOUPDATE_PENDING", source="autoupdate", severity="low", category="deployment",
                                observation=f"{au['pending_updates']} update(s) pending installation."))

    out = _merge_corroborated(out)

    # drop exact duplicates (same code + source_ref + observation)
    seen, uniq = set(), []
    for f in out:
        k = (f["code"], f["source"], f.get("source_ref"), f["observation"][:120])
        if k not in seen:
            seen.add(k)
            uniq.append(f)
    uniq.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["priority"]))
    return uniq


def _merge_corroborated(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A QRadar notification that merely restates a finding discovered by direct analysis is folded into that
    finding as corroborating evidence instead of being listed (and scored) twice."""
    direct: dict[str, dict[str, Any]] = {}
    for f in findings:
        if f["source"] != "notification":
            cur = direct.get(f["code"])
            if cur is None or SEV_ORDER[f["severity"]] < SEV_ORDER[cur["severity"]]:
                direct[f["code"]] = f
    kept: list[dict[str, Any]] = []
    for f in findings:
        target = direct.get(f["code"]) if f["source"] == "notification" else None
        if target is None:
            kept.append(f)
            continue
        ev = target.get("evidence")
        notes = [e["message"] for e in (f.get("evidence") or []) if isinstance(e, dict) and e.get("message")][:3]
        corro = {"corroborating_notifications": notes}
        if isinstance(ev, dict):
            ev.setdefault("corroborating_notifications", notes)
        elif isinstance(ev, list):
            ev.append(corro)
        else:
            target["evidence"] = corro
        if notes:
            target["observation"] += f" QRadar also raised {len(f.get('evidence') or [1])} related notification(s), e.g. \"{notes[0][:160]}\"."
        for h in f.get("hosts") or []:
            if h not in target["hosts"]:
                target["hosts"].append(h)
        if SEV_ORDER[f["severity"]] < SEV_ORDER[target["severity"]]:
            target["severity"], target["priority"] = f["severity"], f["priority"]
    return kept


def top_recommendations(findings: list[dict[str, Any]], n: int = 10) -> list[dict[str, Any]]:
    """Group findings by KB code, rank by severity then volume, return the top *n* actionable items."""
    groups: dict[str, dict[str, Any]] = {}
    for f in findings:
        if f.get("status") in ("dismissed", "resolved"):
            continue
        g = groups.setdefault(f["code"], {"code": f["code"], "title": kb.BY_CODE[f["code"]].title, "category": f["category"], "severity": f["severity"],
                                          "priority": f["priority"], "count": 0, "recommendation": f["recommendation"], "best_practice": f["best_practice"],
                                          "impact": f["impact"], "business_impact": f["business_impact"], "finding_ids": [], "observations": []})
        g["count"] += 1
        g["observations"].append(f["observation"][:200])
        if SEV_ORDER[f["severity"]] < SEV_ORDER[g["severity"]]:
            g["severity"], g["priority"] = f["severity"], f["priority"]
        if "id" in f:
            g["finding_ids"].append(f["id"])
    ranked = sorted(groups.values(), key=lambda g: (SEV_ORDER[g["severity"]], g["priority"], -g["count"]))
    for i, g in enumerate(ranked[:n], 1):
        g["rank"] = i
        g["observations"] = g["observations"][:3]
    return ranked[:n]


def executive_summary(a: dict[str, Any], score: dict[str, Any], cats: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
    env = a.get("environment", {})
    tot = score["severity_totals"]
    weakest = sorted(cats.values(), key=lambda c: c["score"])[:3]
    strongest = sorted(cats.values(), key=lambda c: -c["score"])[:2]
    top = top_recommendations(findings, 5)
    n_hosts = len(a.get("topology", {}).get("nodes", []))
    verdict = ("is operating in good health with minor tuning opportunities" if score["score"] >= 85 else
               "is broadly healthy but has several areas that need attention" if score["score"] >= 70 else
               "shows significant health concerns that should be addressed promptly" if score["score"] >= 55 else
               "is at material operational risk and requires immediate remediation")
    p1 = (f"The QRadar deployment{' (version ' + env['version'] + ')' if env.get('version') else ''} comprising {n_hosts} managed host(s) "
          f"{verdict}, with an overall health score of {score['score']}/100 (grade {score['grade']}) and a {score['risk_level'].lower()} risk rating.")
    p2 = (f"The assessment identified {tot['critical']} critical, {tot['high']} high, {tot['medium']} medium and {tot['low']} low severity findings. "
          f"The weakest areas are {', '.join(f'{c['label']} ({c['score']})' for c in weakest)}; "
          f"strongest areas are {', '.join(f'{c['label']} ({c['score']})' for c in strongest)}.")
    p3 = "Priority actions: " + "; ".join(f"{i + 1}) {t['title']}" for i, t in enumerate(top)) + "." if top else "No priority actions identified."
    bullets = []
    ls = a.get("logsources") or {}
    if ls.get("total"):
        bullets.append(f"{ls['total']} log sources analysed ({ls['error']} in error, {ls['silent_count']} silent) generating {ls['total_eps']:.0f} EPS in aggregate.")
    wc = a.get("wincollect") or {}
    if wc.get("total"):
        bullets.append(f"{wc['total']} WinCollect agents ({wc['managed']} managed, {wc['standalone']} standalone, {wc['outdated']} outdated).")
    ap = a.get("applications") or {}
    if ap.get("total"):
        bullets.append(f"{ap['total']} applications ({ap['running']} running, {ap['error'] + ap['degraded'] + ap['stopped']} not healthy).")
    lic = a.get("licensing") or {}
    if lic.get("eps", {}).get("consumption_pct") is not None:
        bullets.append(f"EPS licence consumption at {lic['eps']['consumption_pct']:.0f}% of {lic['eps']['licensed']:.0f} EPS.")
    return {"headline": f"Overall health {score['score']}/100 - {score['risk_level']} risk", "paragraphs": [p1, p2, p3], "highlights": bullets}
