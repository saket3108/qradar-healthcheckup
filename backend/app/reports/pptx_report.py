"""PPTX export: prepares slide-ready data + chart images and invokes the pptxgenjs generator."""
from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.reports import charts

GEN = Path(__file__).resolve().parents[2] / "pptx_gen" / "generate.js"


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _gb(v):
    return f"{v / 1024**3:.0f} GB" if v else "-"


def _plan(model: dict[str, Any]) -> dict[str, list[str]]:
    plan: dict[str, list[str]] = {"immediate": [], "short": [], "medium": []}
    for t in model["top_recommendations"]:
        action = t["recommendation"][0] if t["recommendation"] else t["title"]
        line = f"{t['title']}: {action}"[:210]
        key = "immediate" if t["severity"] == "critical" else "short" if t["severity"] == "high" else "medium"
        plan[key].append(line)
    return {k: v[:6] for k, v in plan.items()}


def _lic_rows(lic: dict[str, Any]) -> list[list[str]]:
    rows = []
    for m in (lic.get("eps"), lic.get("fpm")):
        if m:
            rows.append([m["name"], f"{m['licensed']:,.0f}" if m.get("licensed") else "n/a", f"{m['current']:,.0f}" if m.get("current") is not None else "n/a",
                         f"{m['peak']:,.0f}" if m.get("peak") is not None else "n/a",
                         f"{m['consumption_pct']:.0f}%" if m.get("consumption_pct") is not None else "n/a", m["risk"]])
    return rows


def build_payload(model: dict[str, Any]) -> dict[str, Any]:
    a, cfg = model["assessment"], model["config"]
    S = model["scores"]
    cats, ov = S.get("categories") or {}, S.get("overall") or {}
    lic = model["licensing"] or {}
    ls, wc, apps = model["logsources"], model["wincollect"], model["applications"]
    images: dict[str, str] = {}
    if ov:
        images["gauge"] = _b64(charts.gauge(ov["score"], f"Grade {ov['grade']}"))
        images["donut"] = _b64(charts.severity_donut(ov.get("severity_totals", {})))
    if cats:
        images["category_bars"] = _b64(charts.category_bars(cats))
    images["deployment"] = _b64(charts.deployment_diagram(model["topology"]))
    if ls.get("protocols"):
        pr = ls["protocols"]
        images["protocols"] = _b64(charts.bar([p["name"] for p in pr], [p["count"] for p in pr], "Log sources by protocol", size=(6.2, 3.4)))
    if wc.get("versions"):
        images["wc_versions"] = _b64(charts.bar([v["version"] for v in wc["versions"]][:10], [v["count"] for v in wc["versions"]][:10], "Agent versions",
                                                color=charts.TEAL, horizontal=False, size=(6.2, 3.4)))
    hosts = list(model["performance_hosts"].values())
    h0 = next((h for h in hosts if h.get("series", {}).get("cpu")), None)
    if h0:
        images["perf_cpu"] = _b64(charts.line(h0["series"]["cpu"], [("used", "CPU used %", charts.BLUE), ("iowait", "I/O wait %", "#ff832b")], "CPU utilisation", "%", (0, 100), size=(6.2, 2.5), hline=90))
    h1 = next((h for h in hosts if h.get("series", {}).get("memory")), None)
    if h1:
        images["perf_mem"] = _b64(charts.line(h1["series"]["memory"], [("used_pct", "Memory used %", charts.PURPLE)], "Memory utilisation", "%", (0, 100), size=(6.2, 2.5), hline=90))
    if lic.get("has_data"):
        images["lic_eps"] = _b64(charts.usage_gauge((lic.get("eps") or {}).get("consumption_pct"), "EPS licence"))
        images["lic_fpm"] = _b64(charts.usage_gauge((lic.get("fpm") or {}).get("consumption_pct"), "FPM licence"))
        if (lic.get("eps") or {}).get("series"):
            images["lic_chart"] = _b64(charts.licence_chart(lic["eps"]))
    logo_b64 = None
    if cfg.get("logo_path") and Path(cfg["logo_path"]).exists():
        logo_b64 = "image/png;base64," + _b64(Path(cfg["logo_path"]).read_bytes())
    ha = model["topology"].get("ha", {})
    wc_slim = {k: wc.get(k) for k in ("total", "managed", "standalone", "disconnected", "outdated", "error")}
    for k in ("old_versions", "communication_problems", "config_issues", "deployment_problems"):
        wc_slim[k] = wc.get(k, [])
    perf_rows = [[p["host"], p["label"], p["severity"], p["finding"][:140]] for p in model["performance_assessments"] if p["severity"] not in ("ok", "info")][:10]
    return {"model": {
        "title": cfg["title"], "customer": a["customer"], "consultant": a["consultant"], "generated": a["generated"], "classification": cfg["classification"],
        "version": a.get("version") or model["environment"].get("version"), "sections": cfg["sections"], "comments": model["comments"], "overall": ov, "logo": logo_b64,
        "summary": {"headline": model["summary"].get("headline", ""), "paragraphs": model["summary"].get("paragraphs", []), "highlights": model["summary"].get("highlights", [])},
        "environment": model["environment"],
        "nodes": [{"hostname": n.get("hostname") or "", "role": n.get("role"), "cpu": n.get("cpu_cores"), "ram": _gb(n.get("memory_bytes")), "disk": _gb(n.get("disk_bytes"))} for n in model["topology"].get("nodes", [])],
        "checks": model["deployment_checks"],
        "ha_text": "High availability: " + (f"{len(ha['pairs'])} HA pair(s) configured." if ha.get("pairs") else "not configured - single points of failure exist."),
        "notif": {"by_severity": model["notifications"].get("by_severity", {}),
                  "top": [{"severity": i["effective_severity"], "title": i["title"], "root_cause": i["root_cause"], "priority": i["priority"]}
                          for i in model["notifications"].get("items", []) if i["effective_severity"] in ("critical", "high", "medium")][:10]},
        "logsources": {k: ls.get(k) for k in ("total", "enabled", "disabled", "error", "silent_count", "total_eps", "top_eps")},
        "wincollect": wc_slim,
        "applications": {k: apps.get(k) for k in ("total", "running", "stopped", "degraded", "error")},
        "app_rows": [[i["name"], i.get("version") or "-", i.get("host") or "-", i["status"], i["observation"][:120]] for i in sorted(apps.get("items", []), key=lambda x: (not x["issues"]))][:10],
        "perf_rows": perf_rows or [["-", "No performance risks identified", "low", "-"]],
        "licensing": {"has_data": bool(lic.get("has_data")), "rows": _lic_rows(lic)},
        "recs": [{"rank": t["rank"], "title": t["title"], "severity": t["severity"], "priority": t["priority"], "action": (t["recommendation"][0] if t["recommendation"] else "")[:160]} for t in model["top_recommendations"]],
        "plan": _plan(model), "next_steps": cfg["next_steps"][:6]},
        "images": images}


def build_pptx(model: dict[str, Any]) -> bytes:
    payload = build_payload(model)
    with tempfile.TemporaryDirectory() as td:
        inp, out = Path(td) / "in.json", Path(td) / "out.pptx"
        inp.write_text(json.dumps(payload))
        r = subprocess.run([get_settings().node_bin, str(GEN), str(inp), str(out)], capture_output=True, text=True, timeout=180, cwd=GEN.parent)
        if r.returncode != 0 or not out.exists():
            raise RuntimeError(f"PPTX generation failed: {r.stderr[-500:]}")
        return out.read_bytes()
