"""Health scoring engine: category scores 0-100, overall score, risk score, maturity level."""
from __future__ import annotations

import math
from typing import Any

CATEGORIES = ["deployment", "notifications", "logsources", "applications", "performance", "licensing", "wincollect"]
LABELS = {"deployment": "Deployment", "notifications": "Notifications", "logsources": "Log Sources", "applications": "Applications",
          "performance": "Performance", "licensing": "Licensing", "wincollect": "WinCollect"}
WEIGHTS = {"deployment": 0.18, "notifications": 0.14, "logsources": 0.16, "applications": 0.08, "performance": 0.22, "licensing": 0.14, "wincollect": 0.08}
PENALTY = {"critical": 25, "high": 14, "medium": 6, "low": 2, "info": 0}
SEV_WEIGHT = {"critical": 10, "high": 6, "medium": 3, "low": 1, "info": 0}
MATURITY = [(90, "Optimised", 5), (78, "Managed", 4), (62, "Defined", 3), (45, "Developing", 2), (0, "Initial", 1)]


def _grade(score: float) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 55 else "F"


def score_categories(findings: list[dict[str, Any]], available: dict[str, bool]) -> dict[str, Any]:
    """Penalty model with diminishing returns per category so one noisy source cannot zero a category."""
    cats: dict[str, Any] = {}
    for c in CATEGORIES:
        fs = [f for f in findings if f["category"] == c and f.get("status", "open") not in ("dismissed", "resolved")]
        penalty = 0.0
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        ordered = sorted(fs, key=lambda f: -PENALTY.get(f["severity"], 0))
        for rank, f in enumerate(ordered):
            sev = f["severity"]
            if sev in counts:
                counts[sev] += 1
            penalty += PENALTY.get(sev, 0) * (0.9 ** rank)   # each further finding weighs slightly less (bounded total)
        score = 100.0 * math.exp(-penalty / 60.0)   # smooth saturating curve: 1 critical ~66, 1 high ~79, 1 medium ~90
        cats[c] = {"key": c, "label": LABELS[c], "score": round(score), "grade": _grade(score), "findings": counts,
                   "weight": WEIGHTS[c], "data_available": available.get(c, True)}
    return cats


def overall(cats: dict[str, Any]) -> dict[str, Any]:
    rated = {k: v for k, v in cats.items() if v["data_available"]}
    if not rated:
        rated = cats
    wsum = sum(v["weight"] for v in rated.values())
    score = sum(v["score"] * v["weight"] for v in rated.values()) / wsum if wsum else 0
    # cap: a critical finding anywhere prevents a score above 89; multiple criticals lower the ceiling
    crit = sum(v["findings"]["critical"] for v in cats.values())
    if crit:
        score = min(score, 89 - 3 * min(crit - 1, 8))
    score = round(max(0, min(100, score)))
    sev_total = {s: sum(v["findings"][s] for v in cats.values()) for s in ("critical", "high", "medium", "low")}
    risk = min(100, sum(SEV_WEIGHT[s] * n * (0.8 if n > 5 else 1) for s, n in sev_total.items()))
    risk = round(min(100, risk * 1.0 + (100 - score) * 0.35))
    risk = min(100, risk)
    mat = next((name, lvl) for thr, name, lvl in MATURITY if score >= thr)
    return {"score": score, "grade": _grade(score), "risk_score": risk,
            "risk_level": "Critical" if risk >= 75 else "High" if risk >= 55 else "Medium" if risk >= 30 else "Low",
            "maturity_level": mat[0], "maturity_index": mat[1], "severity_totals": sev_total}
