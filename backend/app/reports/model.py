"""Report data model: gathers a complete, export-ready view of an assessment (shared by PDF / DOCX / PPTX)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import kb
from app.db.models import Assessment, AssessmentData, Comment, Finding, ReportConfig

ALL_SECTIONS = ["cover", "executive_summary", "health_score", "environment", "deployment", "notifications", "logsources", "wincollect",
                "applications", "performance", "licensing", "recommendations", "next_steps", "appendix"]
SECTION_LABELS = {
    "cover": "Cover Page", "executive_summary": "Executive Summary", "health_score": "Health Score", "environment": "Environment Overview",
    "deployment": "Deployment", "notifications": "Notifications", "logsources": "Log Sources", "wincollect": "WinCollect",
    "applications": "Applications", "performance": "Performance", "licensing": "Licensing", "recommendations": "Recommendations",
    "next_steps": "Next Steps", "appendix": "Appendix"}

SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def get_data(db: Session, assessment_id: str, key: str) -> Any:
    row = db.scalar(select(AssessmentData).where(AssessmentData.assessment_id == assessment_id, AssessmentData.key == key))
    return row.data if row else None


def get_comments(db: Session, assessment_id: str) -> dict[str, str]:
    return {f"{c.target_type}:{c.target_key}": c.text for c in db.scalars(select(Comment).where(Comment.assessment_id == assessment_id)) if c.text}


def default_next_steps(findings: list[dict]) -> list[str]:
    steps = []
    crit = [f for f in findings if f["severity"] == "critical"]
    if crit:
        steps.append(f"Within 7 days: remediate the {len(crit)} critical finding(s), starting with " + ", ".join(sorted({f['title'] for f in crit})[:3]) + ".")
    high = [f for f in findings if f["severity"] == "high"]
    if high:
        steps.append(f"Within 30 days: address the {len(high)} high-severity finding(s) and validate the results in a follow-up health check.")
    steps.append("Within 60 days: complete medium-priority tuning (log source clean-up, WinCollect standardisation, application updates).")
    steps.append("Schedule a follow-up QRadar health check after remediation, and quarterly thereafter.")
    steps.append("Review the capacity plan against the licence forecast and agree an upgrade path for QRadar software and apps.")
    return steps


def build_report_model(db: Session, a: Assessment, include_all_findings: bool = True) -> dict[str, Any]:
    cfg_row = db.get(ReportConfig, a.id)
    cfg = dict(cfg_row.config) if cfg_row else {}
    comments = get_comments(db, a.id)
    comments.update({f"section:{k}": v for k, v in (cfg.get("comments") or {}).items()})
    findings = [{"id": f.id, "code": f.code, "category": f.category, "severity": f.severity, "priority": f.priority, "title": f.title,
                 "observation": f.observation, "description": f.description, "root_cause": f.root_cause, "impact": f.impact,
                 "business_impact": f.business_impact, "risk": f.risk, "recommendation": f.recommendation or [], "best_practice": f.best_practice,
                 "hosts": f.hosts or [], "status": f.status, "comment": comments.get(f"finding:{f.id}", "")}
                for f in db.scalars(select(Finding).where(Finding.assessment_id == a.id))
                if f.status != "dismissed"]
    findings.sort(key=lambda f: (SEV_ORDER.get(f["severity"], 5), f["priority"]))
    notif = get_data(db, a.id, "a_notifications") or {"items": []}
    for n in notif.get("items", []):
        n["comment"] = comments.get(f"notification:{n['id']}", "")
    apps = get_data(db, a.id, "a_applications") or {"items": []}
    for ap in apps.get("items", []):
        ap["comment"] = comments.get(f"application:{ap['id']}", "")
    scores = get_data(db, a.id, "scores") or {}
    from app.analysis.findings import top_recommendations
    top = top_recommendations(findings, 10)
    return {
        "assessment": {"id": a.id, "name": a.name, "customer": cfg.get("customer_name") or a.customer_name or "Customer",
                       "consultant": cfg.get("consultant_name") or a.consultant_name or "", "source_filename": a.source_filename,
                       "generated": datetime.now(timezone.utc).strftime("%d %B %Y"), "version": a.qradar_version},
        "config": {"title": cfg.get("title") or "QRadar Health Check Assessment", "sections": cfg.get("sections") or list(ALL_SECTIONS),
                   "notes": cfg.get("notes") or "", "classification": cfg.get("classification") or "Confidential",
                   "next_steps": cfg.get("next_steps") or default_next_steps(findings), "logo_path": cfg_row.logo_path if cfg_row else None},
        "comments": comments, "scores": scores, "summary": get_data(db, a.id, "executive_summary") or {"headline": "", "paragraphs": [], "highlights": []},
        "environment": get_data(db, a.id, "a_environment") or {}, "topology": get_data(db, a.id, "a_topology") or {"nodes": [], "edges": [], "ha": {"pairs": []}},
        "deployment_checks": get_data(db, a.id, "a_deployment_checks") or [], "notifications": notif,
        "logsources": get_data(db, a.id, "a_logsources") or {}, "wincollect": get_data(db, a.id, "a_wincollect") or {},
        "applications": apps, "performance_hosts": get_data(db, a.id, "a_performance_hosts") or {},
        "performance_assessments": get_data(db, a.id, "a_performance_assessments") or [], "licensing": get_data(db, a.id, "a_licensing") or {},
        "autoupdate": get_data(db, a.id, "a_autoupdate") or {}, "findings": findings, "top_recommendations": top,
        "manifest": {k: v for k, v in (get_data(db, a.id, "manifest") or {}).items() if k != "entries"},
        "kb": {c: kb.BY_CODE[c].title for c in {f["code"] for f in findings}},
    }
