"""Notification analysis: KB-mapped root cause / impact / recommendation for each notification."""
from __future__ import annotations

from collections import Counter
from typing import Any

from app.analysis import kb

SEV_ORDER = ["critical", "high", "medium", "low", "info"]
_RANK = {s: i for i, s in enumerate(SEV_ORDER)}

_ROOT_CAUSE_HINT = {
    "Storage": "Capacity growth or retention misalignment on the affected file system, or storage subsystem latency.",
    "License": "Event/flow volume exceeding the licensed pool or an invalid/expired licence key.",
    "HA": "Replication, heartbeat or configuration fault in the HA cluster.",
    "Backup": "Backup target unavailable/full or the backup job failed to complete.",
    "Parsing": "Events not matching an installed DSM, DSM out of date or log source mis-typed.",
    "DSM": "Log source integration error (credentials, connectivity, DSM/protocol mismatch).",
    "WinCollect": "Agent connectivity, certificate or configuration problem.",
    "Application": "App Framework container fault, resource limit or permission issue.",
    "Deployment": "Deployment/connectivity configuration inconsistency or failed update.",
    "EPS": "Event pipeline saturation causing queue overflow.",
    "Search": "Resource contention or inefficient searches.",
    "CRE": "Expensive custom rules.",
    "Offense": "Magistrate or rule tuning issues.",
    "Performance": "Host resource exhaustion (CPU / memory / I/O).",
    "FPM": "Flow volume exceeding capacity.",
}


def analyse_notification(n: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(str(x) for x in (n.get("message"), n.get("type"), n.get("component")) if x)
    entry = kb.match_notification(text)
    sev = n["severity"]
    if entry is None:
        entry = kb.BY_CODE["GENERIC_CRITICAL"]
        matched = False
    else:
        matched = True
    # Severity: take the more severe of QRadar's own value and KB's default (when matched) - never downgrade.
    eff = sev
    if matched and _RANK[entry.severity] < _RANK.get(sev, 2) and sev == "info":
        eff = entry.severity
    prio = entry.priority if matched else {"critical": "P1", "high": "P2", "medium": "P3", "low": "P4", "info": "P4"}[eff]
    if _RANK[eff] <= _RANK["critical"] and eff == "critical" and prio not in ("P1",):
        prio = "P1"
    return {
        **n,
        "kb_code": entry.code if matched else None,
        "matched": matched,
        "category": entry.category,
        "domain": entry.domain,
        "effective_severity": eff,
        "priority": prio,
        "title": entry.title if matched else (n.get("message") or "Notification")[:120],
        "technical_explanation": entry.description,
        "root_cause": _ROOT_CAUSE_HINT.get(entry.domain, "Underlying component fault; see recommendation."),
        "business_impact": entry.business_impact,
        "impact": entry.impact,
        "risk": entry.risk,
        "recommendation": list(entry.recommendation),
        "best_practice": entry.best_practice,
    }


def analyse_notifications(notifs: list[dict[str, Any]]) -> dict[str, Any]:
    items = [analyse_notification(n) for n in notifs]
    # Collapse duplicates (same KB code + message) for summaries but keep all items.
    items.sort(key=lambda x: (_RANK.get(x["effective_severity"], 5), x.get("timestamp") or ""), reverse=False)
    sev = Counter(i["effective_severity"] for i in items)
    open_items = [i for i in items if i["status"] not in ("closed", "resolved", "dismissed")]
    by_domain = Counter(i["domain"] for i in items)
    return {"items": items, "total": len(items), "open": len(open_items),
            "by_severity": {s: sev.get(s, 0) for s in SEV_ORDER},
            "by_domain": dict(by_domain.most_common()),
            "unmapped": sum(1 for i in items if not i["matched"])}
