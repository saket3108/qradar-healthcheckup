from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require
from app.api.schemas import AssistantIn
from app.assistant.engine import AssessmentContext, answer
from app.core.security import Perm
from app.db.base import get_db
from app.db.models import Assessment, ChatMessage, Export, Finding, User
from app.reports.model import get_data
from app.services import audit

router = APIRouter(prefix="/api", tags=["assistant", "exports"])


def _ctx(db: Session, aid: str) -> AssessmentContext:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "Assessment not found")
    if a.status not in ("completed", "partial"):
        raise HTTPException(409, "Assessment results not available yet")
    findings = [{"id": f.id, "code": f.code, "category": f.category, "severity": f.severity, "priority": f.priority, "title": f.title,
                 "observation": f.observation, "status": f.status} for f in db.scalars(select(Finding).where(Finding.assessment_id == aid))]
    return AssessmentContext(lambda k: get_data(db, aid, k), findings, {"id": a.id, "name": a.name})


@router.get("/assessments/{aid}/assistant")
def history(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ChatMessage).where(ChatMessage.assessment_id == aid, ChatMessage.user_id == user.id).order_by(ChatMessage.id))
    return [{"id": r.id, "role": r.role, "content": r.content, "meta": r.meta, "created_at": r.created_at} for r in rows]


@router.post("/assessments/{aid}/assistant")
def ask(aid: str, body: AssistantIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ctx = _ctx(db, aid)
    prev = [{"role": m.role, "content": m.content} for m in db.scalars(select(ChatMessage).where(ChatMessage.assessment_id == aid, ChatMessage.user_id == user.id).order_by(ChatMessage.id.desc()).limit(6))][::-1]
    res = answer(body.message, ctx, prev)
    db.add(ChatMessage(assessment_id=aid, user_id=user.id, role="user", content=body.message))
    db.add(ChatMessage(assessment_id=aid, user_id=user.id, role="assistant", content=res["answer"], meta={"intent": res["intent"], "references": res.get("references", [])}))
    db.commit()
    audit.record(db, "assistant_query", user.email, aid, detail={"intent": res["intent"]}, ip=client_ip(request))
    return {"answer": res["answer"], "intent": res["intent"], "references": res.get("references", [])}


@router.delete("/assessments/{aid}/assistant", status_code=204)
def clear_history(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for m in db.scalars(select(ChatMessage).where(ChatMessage.assessment_id == aid, ChatMessage.user_id == user.id)):
        db.delete(m)
    db.commit()


# ------------------------------------------------------------------ exports
@router.post("/assessments/{aid}/exports/{fmt}")
def create_export(aid: str, fmt: str, request: Request, user: User = Depends(require(Perm.export)), db: Session = Depends(get_db)):
    from app.reports.export import generate

    if fmt not in ("pdf", "docx", "pptx"):
        raise HTTPException(400, "Format must be pdf, docx or pptx")
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "Assessment not found")
    if a.status not in ("completed", "partial"):
        raise HTTPException(409, "Assessment results not available yet")
    exp = generate(db, a, fmt, user.email)
    audit.record(db, "export_generated", user.email, aid, target=fmt, detail={"export_id": exp.id, "size": exp.size}, ip=client_ip(request))
    return {"id": exp.id, "format": fmt, "size": exp.size, "download": f"/api/exports/{exp.id}/download"}


@router.get("/assessments/{aid}/exports")
def list_exports(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Export).where(Export.assessment_id == aid).order_by(Export.created_at.desc()))
    return [{"id": e.id, "format": e.fmt, "size": e.size, "created_at": e.created_at, "created_by": e.created_by, "download": f"/api/exports/{e.id}/download"} for e in rows]


_MEDIA = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation"}


@router.get("/exports/{eid}/download")
def download(eid: str, user: User = Depends(require(Perm.export)), db: Session = Depends(get_db)):
    e = db.get(Export, eid)
    if not e or not Path(e.path).exists():
        raise HTTPException(404, "Export not found")
    a = db.get(Assessment, e.assessment_id)
    fname = f"QRadar-Health-Check-{(a.customer_name or a.name or 'report').replace(' ', '_')[:40]}.{e.fmt}"
    return FileResponse(e.path, media_type=_MEDIA[e.fmt], filename=fname)
