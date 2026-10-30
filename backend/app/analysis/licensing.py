"""Licensing analysis: utilisation, growth trend, forecast and risk."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.parsers.common import mean


def _linear(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    n = len(points)
    if n < 3:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    den = sum((x - mx) ** 2 for x, _ in points)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in points) / den
    return slope, my - slope * mx


def _metric(name: str, licensed: float | None, history: list[dict], current: float | None, unit: str) -> dict[str, Any]:
    vals = [h["value"] for h in history]
    peaks = [h.get("peak", h["value"]) for h in history]
    cur = vals[-1] if vals else current
    avg = mean(vals)
    peak = max(peaks) if peaks else cur
    m: dict[str, Any] = {"name": name, "unit": unit, "licensed": licensed, "current": cur, "average": avg, "peak": peak,
                         "consumption_pct": None, "peak_pct": None, "trend": None, "forecast": None, "risk": "unknown",
                         "series": [{"ts": h["ts"], "value": h["value"], "peak": h.get("peak")} for h in history[-400:]]}
    if licensed and licensed > 0:
        if cur is not None:
            m["consumption_pct"] = round(100.0 * cur / licensed, 1)
        if peak is not None:
            m["peak_pct"] = round(100.0 * peak / licensed, 1)
    if len(history) >= 3:
        t0 = datetime.fromisoformat(history[0]["ts"])
        pts = [((datetime.fromisoformat(h["ts"]) - t0).total_seconds() / 86400.0, h.get("peak", h["value"])) for h in history]
        lr = _linear(pts)
        if lr:
            slope, icpt = lr
            span = max(pts[-1][0], 1)
            m["trend"] = {"slope_per_day": round(slope, 4), "growth_pct_per_month": round(100.0 * slope * 30 / max(mean(p for _, p in pts) or 1, 1e-9), 1),
                          "direction": "growing" if slope > 0.002 * (mean(p for _, p in pts) or 1) else "declining" if slope < -0.002 * (mean(p for _, p in pts) or 1) else "stable"}
            f = []
            for months in (3, 6, 12):
                d = pts[-1][0] + 30 * months
                v = max(0.0, slope * d + icpt)
                f.append({"months": months, "value": round(v, 1), "pct": round(100.0 * v / licensed, 1) if licensed else None})
            m["forecast"] = f
            if licensed and slope > 0:
                days = (licensed - (slope * pts[-1][0] + icpt)) / slope
                m["days_to_limit"] = int(days) if days > 0 else 0
            _ = span
    pct = m["peak_pct"] if m["peak_pct"] is not None else m["consumption_pct"]
    if pct is not None:
        fc12 = (m.get("forecast") or [{}] * 3)[-1].get("pct") if m.get("forecast") else None
        m["risk"] = ("critical" if pct >= 100 else "high" if pct >= 90 else "medium" if pct >= 75 or (fc12 or 0) >= 100 else "low")
    return m


def analyse_licensing(lic: dict[str, Any], eps_hist: list[dict], fpm_hist: list[dict], current_eps: float | None,
                      current_fpm: float | None, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    eps = _metric("EPS", lic.get("eps_licensed"), eps_hist, current_eps, "events/s")
    fpm = _metric("FPM", lic.get("fpm_licensed"), fpm_hist, current_fpm, "flows/min")
    expiry_days = None
    if lic.get("expiry"):
        try:
            expiry_days = (datetime.fromisoformat(lic["expiry"]) - now).days
        except ValueError:
            pass
    ranks = {"unknown": -1, "low": 0, "medium": 1, "high": 2, "critical": 3}
    worst = max((eps["risk"], fpm["risk"]), key=lambda r: ranks[r])
    if expiry_days is not None and expiry_days < 0:
        worst = "critical"
    elif expiry_days is not None and expiry_days < 60 and ranks[worst] < 2:
        worst = "high"
    return {"eps": eps, "fpm": fpm, "app_framework": {"licensed": lic.get("apps_licensed")},
            "expiry": lic.get("expiry"), "expiry_days": expiry_days, "license_type": lic.get("type"),
            "utilisation_risk": worst, "has_data": bool(lic.get("eps_licensed") or lic.get("fpm_licensed") or eps_hist or fpm_hist)}
