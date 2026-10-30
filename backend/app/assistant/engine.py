"""QRadar assistant – answers questions strictly from the uploaded assessment data.

Deterministic intent engine (always available, no external calls).  When ``QHC_LLM_BASE_URL`` is configured the
engine's grounded answer plus a compact data context is sent to an OpenAI-compatible endpoint to be rephrased/extended;
if the call fails the deterministic answer is returned, so the assistant never hard-fails.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.analysis import kb
from app.core.config import get_settings

log = logging.getLogger(__name__)
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

INTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("why_score_low", re.compile(r"why.*(health|score).*(low|bad|poor|down|\d)|(low|poor|bad).*(health )?score|score.*(explain|breakdown|reason)|what.*(drag|lower|reduc).*score", re.I)),
    ("critical", re.compile(r"(show|list|what|give).*(critical|urgent|severe)|critical (findings|issues)|p1\b", re.I)),
    ("fix_first", re.compile(r"(fix|address|prioriti[sz]e|tackle|start).*first|top (priorit|recommend|action)|what should.*(customer|we|i).*(do|fix)|next steps?|priorit", re.I)),
    ("eps_high", re.compile(r"(why|what).*(eps|events? per second).*(high|spike|exceed|licen)|\beps\b.*(high|exceed|license|licence|usage|consum)|top eps|noisy", re.I)),
    ("explain_notification", re.compile(r"explain.*notif|notif.*(mean|explain|about)|what does.*notif|notification\s*#?\s*\d+", re.I)),
    ("license", re.compile(r"licen[sc]e|fpm|forecast|capacity|growth", re.I)),
    ("wincollect", re.compile(r"wincollect|win collect|agents?", re.I)),
    ("logsources", re.compile(r"log ?sources?|dsm|parsing|silent|protocol", re.I)),
    ("applications", re.compile(r"\bapps?\b|applications?|container|docker|restart", re.I)),
    ("performance", re.compile(r"perform|cpu|memory|disk|swap|latency|await|sar|load|storage|network|slow", re.I)),
    ("deployment", re.compile(r"deploy|\bha\b|high availability|failover|topology|host|console|event processor|managed host", re.I)),
    ("environment", re.compile(r"version|fix ?pack|environment|appliance|hardware|build|overview|summary|about", re.I)),
]


class AssessmentContext:
    """Lazy accessor over stored assessment datasets."""

    def __init__(self, load, findings: list[dict[str, Any]], assessment: dict[str, Any]) -> None:
        self._load, self.findings, self.assessment = load, findings, assessment
        self._cache: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        if key not in self._cache:
            self._cache[key] = self._load(key)
        return self._cache[key]


def answer(question: str, ctx: AssessmentContext, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    q = question.strip()
    intent = next((name for name, rx in INTENTS if rx.search(q)), "general")
    fn = _HANDLERS.get(intent, _general)
    res = fn(q, ctx)
    res["intent"] = intent
    s = get_settings()
    if s.llm_base_url and s.llm_api_key:
        try:
            res["answer"] = _llm_rewrite(q, res["answer"], ctx, history or [])
            res["llm"] = True
        except Exception as e:   # noqa: BLE001
            log.warning("LLM augmentation failed: %s", e)
            res["llm"] = False
    return res


def _fmt_f(f: dict[str, Any], n: int = 1) -> str:
    return f"{n}. **[{f['severity'].upper()} / {f['priority']}] {f['title']}** - {f['observation'][:240]}"


def _sorted_findings(ctx: AssessmentContext) -> list[dict[str, Any]]:
    return sorted([f for f in ctx.findings if f.get("status") not in ("dismissed", "resolved")], key=lambda f: (SEV_ORDER.get(f["severity"], 5), f["priority"]))


def _why_score_low(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    sc = ctx.get("scores") or {}
    ov, cats = sc.get("overall") or {}, sc.get("categories") or {}
    if not ov:
        return {"answer": "Scores are not available yet for this assessment.", "references": []}
    weakest = sorted(cats.values(), key=lambda c: c["score"])
    lines = [f"The overall health score is **{ov['score']}/100 (grade {ov['grade']}, {ov['risk_level']} risk, maturity: {ov['maturity_level']})**.",
             "", "Category scores (lowest first):"]
    for c in weakest:
        f = c["findings"]
        lines.append(f"- **{c['label']}: {c['score']}** - {f['critical']} critical, {f['high']} high, {f['medium']} medium, {f['low']} low findings" + ("" if c["data_available"] else " _(no data in bundle)_"))
    crit = ov["severity_totals"]["critical"]
    if crit:
        lines.append(f"\nBecause {crit} critical finding(s) exist, the overall score is capped below 90 regardless of other categories.")
    fs = [f for f in _sorted_findings(ctx) if f["category"] == weakest[0]["key"]][:3]
    if fs:
        lines.append(f"\nMain drivers in **{weakest[0]['label']}**:")
        lines += [_fmt_f(f, i + 1) for i, f in enumerate(fs)]
    return {"answer": "\n".join(lines), "references": [f["id"] for f in fs if "id" in f]}


def _critical(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    fs = [f for f in _sorted_findings(ctx) if f["severity"] == "critical"]
    if not fs:
        high = [f for f in _sorted_findings(ctx) if f["severity"] == "high"][:5]
        msg = "No **critical** findings were identified in this assessment."
        if high:
            msg += " The most severe remaining findings are:\n" + "\n".join(_fmt_f(f, i + 1) for i, f in enumerate(high))
        return {"answer": msg, "references": [f["id"] for f in high if "id" in f]}
    lines = [f"There are **{len(fs)} critical finding(s)**:"] + [_fmt_f(f, i + 1) for i, f in enumerate(fs[:12])]
    lines.append("\nAsk _\"Explain finding 1\"_ or _\"What should the customer fix first?\"_ for remediation detail.")
    return {"answer": "\n".join(lines), "references": [f["id"] for f in fs if "id" in f]}


def _fix_first(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    top = ctx.get("top_recommendations") or []
    if not top:
        return {"answer": "No recommendations were generated for this assessment.", "references": []}
    lines = ["Recommended order of remediation:"]
    for t in top[:5]:
        lines.append(f"\n**{t['rank']}. {t['title']}** ({t['severity']}, {t['priority']}, {t['count']} finding(s))")
        lines.append(f"   _Why:_ {t['impact']}")
        lines += [f"   - {r}" for r in t["recommendation"][:3]]
    return {"answer": "\n".join(lines), "references": [t["code"] for t in top[:5]]}


def _eps(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    lic, ls = ctx.get("a_licensing") or {}, ctx.get("a_logsources") or {}
    lines = []
    e = lic.get("eps") or {}
    if e.get("licensed"):
        lines.append(f"EPS licence: **{e['licensed']:.0f}**, current **{(e.get('current') or 0):.0f}** ({e.get('consumption_pct') or 0:.0f}%), peak **{(e.get('peak') or 0):.0f}** ({e.get('peak_pct') or 0:.0f}%). Risk: **{e['risk']}**.")
        if e.get("forecast"):
            lines.append("Forecast: " + ", ".join(f"{f['months']}m → {f['pct']:.0f}%" for f in e["forecast"] if f.get("pct") is not None) + ".")
    if ls.get("top_eps"):
        tot = ls["total_eps"] or 1
        lines.append(f"\nTotal log-source EPS is **{ls['total_eps']:.0f}**. Top contributors:")
        for s in ls["top_eps"][:6]:
            lines.append(f"- {s['name']} ({s['type']}, {s['protocol']}): {s['eps']:.1f} EPS ({100 * s['eps'] / tot:.0f}%)")
        lines.append("\nTo reduce EPS: filter/route noisy low-value events, enable coalescing, and review the highest contributors above.")
    return {"answer": "\n".join(lines) or "No EPS or licence data was found in this bundle.", "references": ["LIC_EPS_EXCEEDED"]}


def _explain_notification(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    nd = ctx.get("a_notifications") or {"items": []}
    items = nd["items"]
    m = re.search(r"#?\s*(\d+)", q)
    pick = None
    if m:
        pick = next((i for i in items if str(i["id"]) == m.group(1)), None)
    if pick is None:
        words = [w for w in re.findall(r"[a-z]{4,}", q.lower()) if w not in ("explain", "this", "notification", "what", "does", "mean", "about", "that")]
        scored = sorted(items, key=lambda i: -sum(w in (i.get("message", "") + i.get("title", "")).lower() for w in words))
        if scored and words and sum(w in (scored[0].get("message", "") + scored[0].get("title", "")).lower() for w in words):
            pick = scored[0]
    if pick is None and items:
        pick = items[0]
    if pick is None:
        return {"answer": "No notifications were found in this assessment.", "references": []}
    n = pick
    lines = [f"**Notification {n['id']} - {n['title']}** ({n['effective_severity'].upper()}, {n['priority']})",
             f"> {n['message'][:400]}", "", f"**What it means:** {n['technical_explanation']}", f"**Likely root cause:** {n['root_cause']}",
             f"**Impact:** {n['impact']}", f"**Business impact:** {n['business_impact']}", "", "**Recommended actions:**"]
    lines += [f"- {r}" for r in n["recommendation"]]
    lines.append(f"\n**IBM best practice:** {n['best_practice']}")
    return {"answer": "\n".join(lines), "references": [n["id"]]}


def _license(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    lic = ctx.get("a_licensing") or {}
    if not lic.get("has_data"):
        return {"answer": "No licensing data was found in the bundle.", "references": []}
    lines = [f"Overall licence utilisation risk: **{lic['utilisation_risk']}**."]
    for m in (lic.get("eps"), lic.get("fpm")):
        if m and m.get("licensed"):
            lines.append(f"- **{m['name']}**: licensed {m['licensed']:.0f}, current {(m.get('current') or 0):.0f} ({m.get('consumption_pct') or 0:.0f}%), peak {(m.get('peak') or 0):.0f} ({m.get('peak_pct') or 0:.0f}%)"
                         + (f", trend {m['trend']['direction']} ({m['trend']['growth_pct_per_month']}%/month)" if m.get("trend") else ""))
    if lic.get("expiry_days") is not None:
        lines.append(f"- Licence expiry in **{lic['expiry_days']} days**.")
    return {"answer": "\n".join(lines), "references": []}


def _wincollect(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    w = ctx.get("a_wincollect") or {}
    if not w.get("total"):
        return {"answer": "No WinCollect agent data was found in this bundle.", "references": []}
    lines = [f"**{w['total']}** agents: {w['managed']} managed, {w['standalone']} standalone, {w['disconnected']} disconnected/silent, {w['outdated']} outdated, {w['error']} in error."]
    if w["versions"]:
        lines.append("Versions: " + ", ".join(f"{v['version']} ({v['count']})" for v in w["versions"][:6]))
    lines.append("\nRecommendations: " + " ".join(kb.BY_CODE["WINCOLLECT_COMM"].recommendation[:2]))
    return {"answer": "\n".join(lines), "references": ["WINCOLLECT_COMM"]}


def _logsources(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    l = ctx.get("a_logsources") or {}
    if not l.get("total"):
        return {"answer": "No log source data was found in this bundle.", "references": []}
    lines = [f"**{l['total']}** log sources: {l['enabled']} enabled, {l['disabled']} disabled, {l['error']} error, {l['unknown']} unknown; total {l['total_eps']:.0f} EPS."]
    if l["problematic"]:
        lines.append("\nProblematic sources:")
        lines += [f"- {p['name']} ({p['type']}): {'; '.join(p['reasons'])}" for p in l["problematic"][:8]]
    return {"answer": "\n".join(lines), "references": ["DSM_ERRORS"]}


def _applications(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    a = ctx.get("a_applications") or {}
    if not a.get("total"):
        return {"answer": "No application data was found in this bundle.", "references": []}
    lines = [f"**{a['total']}** applications: {a['running']} running, {a['stopped']} stopped, {a['degraded']} degraded, {a['error']} error."]
    bad = [i for i in a["items"] if i["issues"]][:8]
    for i in bad:
        lines.append(f"- **{i['name']}** {i.get('version') or ''} on {i.get('host') or '?'}: {i['observation']}")
    return {"answer": "\n".join(lines), "references": []}


def _performance(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    p = [x for x in (ctx.get("a_performance_assessments") or []) if x["severity"] not in ("ok", "info")]
    if not p:
        return {"answer": "No performance risks were identified in the collected system data.", "references": []}
    p.sort(key=lambda x: (SEV_ORDER.get(x["severity"], 5)))
    lines = [f"**{len(p)} performance finding(s)**:"]
    for x in p[:8]:
        lines.append(f"- **[{x['severity'].upper()}] {x['label']} ({x['host']})**: {x['finding']} _Cause:_ {x['root_cause']}")
    return {"answer": "\n".join(lines), "references": []}


def _deployment(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    topo, checks = ctx.get("a_topology") or {}, ctx.get("a_deployment_checks") or []
    lines = [f"Deployment: **{len(topo.get('nodes', []))}** host(s) - " + ", ".join(f"{k}: {v}" for k, v in (topo.get("role_counts") or {}).items())]
    ha = topo.get("ha") or {}
    lines.append("HA: " + (f"{len(ha['pairs'])} pair(s) configured" if ha.get("pairs") else "**not configured**"))
    for c in checks:
        if c["status"] != "PASS":
            lines.append(f"- **{c['status']}** - {c['name']}: {c['detail']}")
    return {"answer": "\n".join(lines), "references": []}


def _environment(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    e = ctx.get("a_environment") or {}
    s = ctx.get("executive_summary") or {}
    lines = [f"QRadar **{e.get('version') or 'unknown version'}**, {e.get('deployment_type') or 'deployment type unknown'}, {e.get('hosts', 0)} host(s)."]
    lines += s.get("paragraphs", [])
    return {"answer": "\n\n".join(lines), "references": []}


def _general(q: str, ctx: AssessmentContext) -> dict[str, Any]:
    # keyword search across findings as a fallback
    words = [w for w in re.findall(r"[a-z]{4,}", q.lower())]
    scored = sorted(ctx.findings, key=lambda f: -sum(w in (f["title"] + f["observation"]).lower() for w in words))
    hits = [f for f in scored if words and sum(w in (f["title"] + f["observation"]).lower() for w in words)][:5]
    if hits:
        return {"answer": "Related findings:\n" + "\n".join(_fmt_f(f, i + 1) for i, f in enumerate(hits)), "references": [f["id"] for f in hits if "id" in f]}
    sc = (ctx.get("scores") or {}).get("overall") or {}
    return {"answer": ("I answer questions about this uploaded assessment. Try: _Why is the health score low?_, _Show critical findings_, _Why is EPS high?_, "
                       "_What should the customer fix first?_, or _Explain notification 12_." + (f"\n\nCurrent overall score: **{sc.get('score')}/100**." if sc else "")), "references": []}


_HANDLERS = {"why_score_low": _why_score_low, "critical": _critical, "fix_first": _fix_first, "eps_high": _eps, "explain_notification": _explain_notification,
             "license": _license, "wincollect": _wincollect, "logsources": _logsources, "applications": _applications, "performance": _performance,
             "deployment": _deployment, "environment": _environment}


def _llm_rewrite(question: str, grounded: str, ctx: AssessmentContext, history: list[dict[str, str]]) -> str:
    s = get_settings()
    sc = (ctx.get("scores") or {}).get("overall")
    facts = {"overall": sc, "top_findings": [{k: f[k] for k in ("severity", "priority", "title", "observation")} for f in _sorted_findings(ctx)[:15]]}
    msgs = [{"role": "system", "content": "You are an IBM QRadar health-check expert. Answer ONLY from the supplied assessment facts. If the facts do not contain the answer, say so. Be concise and actionable; use markdown."},
            {"role": "system", "content": "ASSESSMENT FACTS:\n" + json.dumps(facts)[:12000]}]
    msgs += history[-6:]
    msgs.append({"role": "user", "content": f"Question: {question}\n\nDraft grounded answer:\n{grounded}\n\nImprove clarity without adding unsupported claims."})
    r = httpx.post(s.llm_base_url.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {s.llm_api_key}"},
                   json={"model": s.llm_model, "messages": msgs, "temperature": 0.2}, timeout=45)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]
