from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis import kb
from app.analysis.scoring import CATEGORIES, overall, score_categories
from app.api.deps import client_ip, current_user, require
from app.api.schemas import (AssessmentCreate, AssessmentDetail, AssessmentOut, AssessmentUpdate, AssistantIn, CommentIn, FindingUpdate,
                             ReportConfigIn)
from app.core.config import get_settings
from app.core.security import Perm
from app.db.base import get_db
from app.db.models import (Assessment, AssessmentData, ChatMessage, Comment, Export, Finding, ReportConfig, Upload, User, utcnow)
from app.pipeline import dispatch
from app.pipeline.runner import init_stages, purge_workdir
from app.pipeline.stages import STAGE_NAMES
from app.reports.model import ALL_SECTIONS, SECTION_LABELS, build_report_model, get_data
from app.services import audit

router = APIRouter(prefix="/api", tags=["assessments"])
SAFE_NAME = re.compile(r"[^A-Za-z0-9._\- ]")
ALLOWED_EXT = (".tar", ".tar.gz", ".tgz", ".gz", ".zip")


def _safe_filename(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    base = SAFE_NAME.sub("_", base).strip(". ") or "upload"
    return base[:200]


def _get_a(db: Session, aid: str) -> Assessment:
    a = db.get(Assessment, aid)
    if not a:
        raise HTTPException(404, "Assessment not found")
    return a


def _ready(a: Assessment) -> None:
    if a.status not in ("completed", "partial"):
        raise HTTPException(409, f"Assessment is {a.status}; results are not available yet")


# ------------------------------------------------------------------ uploads
@router.post("/uploads", status_code=201)
def init_upload(body: dict, request: Request, user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    s = get_settings()
    s.ensure_dirs()
    filename = _safe_filename(str(body.get("filename", "")))
    size = int(body.get("size") or 0)
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXT)}")
    if size <= 0 or size > s.max_upload_bytes:
        raise HTTPException(413, f"File size must be between 1 byte and {s.max_upload_bytes} bytes")
    up = Upload(filename=filename, total_size=size, path="", created_by=user.id)
    db.add(up)
    db.flush()
    path = s.uploads_dir / f"{up.id}_{filename}"
    up.path = str(path)
    path.touch(mode=0o600)
    db.commit()
    audit.record(db, "upload", user.email, target=filename, detail={"size": size, "upload_id": up.id}, ip=client_ip(request))
    return {"upload_id": up.id, "chunk_size": s.upload_chunk_bytes, "received": 0}


@router.put("/uploads/{upload_id}")
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(ge=0), user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    up = db.get(Upload, upload_id)
    if not up or up.status != "open":
        raise HTTPException(404, "Upload not found or already completed")
    if up.created_by != user.id and user.role != "administrator":
        raise HTTPException(403, "Not your upload")
    if offset != up.received:
        raise HTTPException(409, detail={"message": "Offset mismatch - resume from received", "received": up.received})
    n = 0
    with open(up.path, "r+b") as fh:
        fh.seek(offset)
        async for chunk in request.stream():
            n += len(chunk)
            if offset + n > up.total_size:
                fh.truncate(offset)
                raise HTTPException(413, "Chunk exceeds declared upload size")
            fh.write(chunk)
    up.received = offset + n
    db.commit()
    return {"received": up.received, "complete": up.received >= up.total_size}


@router.get("/uploads/{upload_id}")
def upload_status(upload_id: str, user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    up = db.get(Upload, upload_id)
    if not up:
        raise HTTPException(404, "Upload not found")
    return {"upload_id": up.id, "filename": up.filename, "total": up.total_size, "received": up.received, "status": up.status}


@router.post("/uploads/{upload_id}/complete")
def complete_upload(upload_id: str, user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    up = db.get(Upload, upload_id)
    if not up:
        raise HTTPException(404, "Upload not found")
    if up.received != up.total_size:
        raise HTTPException(409, f"Upload incomplete ({up.received}/{up.total_size} bytes)")
    h = hashlib.sha256()
    with open(up.path, "rb") as fh:
        for blk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(blk)
    up.sha256, up.status = h.hexdigest(), "complete"
    db.commit()
    return {"upload_id": up.id, "sha256": up.sha256}


@router.post("/uploads/direct", status_code=201)
async def direct_upload(request: Request, file: UploadFile = File(...), user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    """Convenience single-request upload for small bundles / API clients (large files should use chunked upload)."""
    s = get_settings()
    s.ensure_dirs()
    filename = _safe_filename(file.filename or "upload")
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(400, f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXT)}")
    up = Upload(filename=filename, total_size=0, path="", created_by=user.id)
    db.add(up)
    db.flush()
    path = s.uploads_dir / f"{up.id}_{filename}"
    h, total = hashlib.sha256(), 0
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as out:
        while chunk := await file.read(8 * 1024 * 1024):
            total += len(chunk)
            if total > s.max_upload_bytes:
                out.close()
                path.unlink(missing_ok=True)
                raise HTTPException(413, "File too large")
            h.update(chunk)
            out.write(chunk)
    up.path, up.total_size, up.received, up.sha256, up.status = str(path), total, total, h.hexdigest(), "complete"
    db.commit()
    audit.record(db, "upload", user.email, target=filename, detail={"size": total, "upload_id": up.id}, ip=client_ip(request))
    return {"upload_id": up.id, "sha256": up.sha256, "size": total}


# ------------------------------------------------------------------ assessments
@router.post("/assessments", response_model=AssessmentOut, status_code=201)
def create_assessment(body: AssessmentCreate, request: Request, user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    up = db.get(Upload, body.upload_id)
    if not up or up.status != "complete":
        raise HTTPException(400, "Upload not found or not complete")
    a = Assessment(name=body.name or up.filename, customer_name=body.customer_name, consultant_name=body.consultant_name or user.full_name,
                   source_filename=up.filename, source_path=up.path, source_size=up.total_size, source_sha256=up.sha256, created_by=user.id)
    up.status = "consumed"
    db.add(a)
    db.commit()
    init_stages(a.id)
    audit.record(db, "assessment_created", user.email, a.id, target=a.name, detail={"filename": up.filename}, ip=client_ip(request))
    audit.record(db, "report_created", user.email, a.id, target=a.name, ip=client_ip(request))
    dispatch.enqueue(a.id)
    db.refresh(a)
    return a


@router.get("/assessments", response_model=list[AssessmentOut])
def list_assessments(q: str | None = None, status: str | None = None, limit: int = 100, offset: int = 0,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Assessment).order_by(Assessment.created_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Assessment.name.ilike(like) | Assessment.customer_name.ilike(like))
    if status:
        stmt = stmt.where(Assessment.status == status)
    return list(db.scalars(stmt.limit(min(limit, 500)).offset(offset)))


@router.get("/assessments/{aid}", response_model=AssessmentDetail)
def get_assessment(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _get_a(db, aid)


@router.patch("/assessments/{aid}", response_model=AssessmentOut)
def update_assessment(aid: str, body: AssessmentUpdate, request: Request, user: User = Depends(require(Perm.edit)), db: Session = Depends(get_db)):
    a = _get_a(db, aid)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None:
            setattr(a, k, v)
    db.commit()
    audit.record(db, "report_modified", user.email, aid, detail=body.model_dump(exclude_unset=True), ip=client_ip(request))
    return a


@router.delete("/assessments/{aid}", status_code=204)
def delete_assessment(aid: str, request: Request, user: User = Depends(require(Perm.delete)), db: Session = Depends(get_db)):
    a = _get_a(db, aid)
    if a.status == "processing":
        raise HTTPException(409, "Cannot delete while processing")
    for e in db.scalars(select(Export).where(Export.assessment_id == aid)):
        Path(e.path).unlink(missing_ok=True)
    Path(a.source_path).unlink(missing_ok=True)
    purge_workdir(aid)
    name = a.name
    db.delete(a)
    db.commit()
    audit.record(db, "assessment_deleted", user.email, aid, target=name, ip=client_ip(request))
    return Response(status_code=204)


@router.post("/assessments/{aid}/resume", response_model=AssessmentOut)
def resume(aid: str, from_stage: str | None = None, request: Request = None, user: User = Depends(require(Perm.upload)), db: Session = Depends(get_db)):
    a = _get_a(db, aid)
    if a.status == "processing" and a.heartbeat_at and (utcnow() - a.heartbeat_at.replace(tzinfo=a.heartbeat_at.tzinfo or utcnow().tzinfo)).total_seconds() < get_settings().stale_job_seconds:
        raise HTTPException(409, "Assessment is currently processing")
    if from_stage and from_stage not in STAGE_NAMES:
        raise HTTPException(400, f"Unknown stage; valid: {STAGE_NAMES}")
    a.status, a.error = "queued", None
    db.commit()
    audit.record(db, "assessment_reprocessed", user.email, aid, detail={"from_stage": from_stage}, ip=client_ip(request) if request else None)
    dispatch.enqueue(aid, from_stage)
    db.refresh(a)
    return a


# ------------------------------------------------------------------ analysis data
def _data_endpoint(path: str, keys: dict[str, str]):
    def handler(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        a = _get_a(db, aid)
        _ready(a)
        return {out: get_data(db, aid, k) for out, k in keys.items()}
    router.add_api_route(f"/assessments/{{aid}}/{path}", handler, methods=["GET"], name=f"get_{path}")


_data_endpoint("overview", {"environment": "a_environment", "topology": "a_topology", "logsources": "a_logsources", "wincollect": "a_wincollect",
                            "applications": "a_applications", "licensing": "a_licensing", "autoupdate": "a_autoupdate", "scores": "scores"})
_data_endpoint("deployment", {"topology": "a_topology", "checks": "a_deployment_checks", "environment": "a_environment"})
_data_endpoint("logsources-analysis", {"logsources": "a_logsources", "wincollect": "a_wincollect"})
_data_endpoint("licensing", {"licensing": "a_licensing"})
_data_endpoint("performance", {"hosts": "a_performance_hosts", "assessments": "a_performance_assessments"})
_data_endpoint("health", {"scores": "scores", "summary": "executive_summary", "top_recommendations": "top_recommendations"})


@router.get("/assessments/{aid}/notifications")
def notifications(aid: str, severity: str | None = None, q: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _ready(_get_a(db, aid))
    data = get_data(db, aid, "a_notifications") or {"items": []}
    comments = {c.target_key: c.text for c in db.scalars(select(Comment).where(Comment.assessment_id == aid, Comment.target_type == "notification"))}
    items = []
    for n in data["items"]:
        if severity and n["effective_severity"] != severity:
            continue
        if q and q.lower() not in (n.get("message", "") + n.get("title", "")).lower():
            continue
        items.append({**n, "comment": comments.get(str(n["id"]), "")})
    return {**data, "items": items}


@router.get("/assessments/{aid}/applications")
def applications(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _ready(_get_a(db, aid))
    data = get_data(db, aid, "a_applications") or {"items": []}
    comments = {c.target_key: c.text for c in db.scalars(select(Comment).where(Comment.assessment_id == aid, Comment.target_type == "application"))}
    return {**data, "items": [{**i, "comment": comments.get(str(i["id"]), "")} for i in data["items"]]}


@router.get("/assessments/{aid}/findings")
def findings(aid: str, category: str | None = None, severity: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _ready(_get_a(db, aid))
    stmt = select(Finding).where(Finding.assessment_id == aid)
    if category:
        stmt = stmt.where(Finding.category == category)
    if severity:
        stmt = stmt.where(Finding.severity == severity)
    comments = {c.target_key: c.text for c in db.scalars(select(Comment).where(Comment.assessment_id == aid, Comment.target_type == "finding"))}
    rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    rows = sorted(db.scalars(stmt), key=lambda f: (rank.get(f.severity, 5), f.priority))
    return [{"id": f.id, "code": f.code, "category": f.category, "source": f.source, "severity": f.severity, "priority": f.priority, "title": f.title,
             "observation": f.observation, "description": f.description, "root_cause": f.root_cause, "impact": f.impact, "business_impact": f.business_impact,
             "risk": f.risk, "recommendation": f.recommendation, "best_practice": f.best_practice, "hosts": f.hosts, "evidence": f.evidence,
             "status": f.status, "comment": comments.get(f.id, "")} for f in rows]


@router.patch("/assessments/{aid}/findings/{fid}")
def update_finding(aid: str, fid: str, body: FindingUpdate, request: Request, user: User = Depends(require(Perm.edit)), db: Session = Depends(get_db)):
    f = db.get(Finding, fid)
    if not f or f.assessment_id != aid:
        raise HTTPException(404, "Finding not found")
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    for k, v in changes.items():
        setattr(f, k, v)
    db.commit()
    _rescore(db, aid)
    audit.record(db, "finding_updated", user.email, aid, target=fid, detail=changes, ip=client_ip(request))
    return {"ok": True}


def _rescore(db: Session, aid: str) -> None:
    """Recompute category/overall scores after consultants change finding status/severity."""
    rows = [{"code": f.code, "category": f.category, "severity": f.severity, "status": f.status} for f in db.scalars(select(Finding).where(Finding.assessment_id == aid))]
    sc = get_data(db, aid, "scores") or {}
    cats = score_categories(rows, sc.get("available") or {})
    ov = overall(cats)
    for key, data in (("scores", {"categories": cats, "overall": ov, "available": sc.get("available") or {}}),):
        row = db.scalar(select(AssessmentData).where(AssessmentData.assessment_id == aid, AssessmentData.key == key))
        row.data = data
    a = db.get(Assessment, aid)
    a.overall_score = ov["score"]
    a.summary = {**(a.summary or {}), "overall": ov, "categories": cats}
    db.commit()


# ------------------------------------------------------------------ comments
@router.get("/assessments/{aid}/comments")
def list_comments(aid: str, target_type: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _get_a(db, aid)
    stmt = select(Comment).where(Comment.assessment_id == aid)
    if target_type:
        stmt = stmt.where(Comment.target_type == target_type)
    return [{"target_type": c.target_type, "target_key": c.target_key, "text": c.text, "updated_by": c.updated_by, "updated_at": c.updated_at} for c in db.scalars(stmt)]


VALID_TARGETS = {"notification", "application", "logsource", "wincollect", "finding", "section", "performance", "deployment", "licensing"}


@router.put("/assessments/{aid}/comments/{target_type}/{target_key:path}")
def put_comment(aid: str, target_type: str, target_key: str, body: CommentIn, request: Request, user: User = Depends(require(Perm.edit)), db: Session = Depends(get_db)):
    _get_a(db, aid)
    if target_type not in VALID_TARGETS:
        raise HTTPException(400, f"target_type must be one of {sorted(VALID_TARGETS)}")
    c = db.scalar(select(Comment).where(Comment.assessment_id == aid, Comment.target_type == target_type, Comment.target_key == target_key))
    if c is None:
        c = Comment(assessment_id=aid, target_type=target_type, target_key=target_key, text=body.text, updated_by=user.email)
        db.add(c)
    else:
        c.text, c.updated_by = body.text, user.email
    db.commit()
    audit.record(db, "comment_updated", user.email, aid, target=f"{target_type}:{target_key}", ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ report config + logo
@router.get("/assessments/{aid}/report-config")
def get_report_config(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = _get_a(db, aid)
    cfg_row = db.get(ReportConfig, aid)
    cfg = cfg_row.config if cfg_row else {}
    model = build_report_model(db, a) if a.status in ("completed", "partial") else None
    return {"config": {"customer_name": cfg.get("customer_name") or a.customer_name, "consultant_name": cfg.get("consultant_name") or a.consultant_name,
                       "title": cfg.get("title") or "QRadar Health Check Assessment", "sections": cfg.get("sections") or ALL_SECTIONS, "notes": cfg.get("notes") or "",
                       "classification": cfg.get("classification") or "Confidential", "next_steps": cfg.get("next_steps") or (model["config"]["next_steps"] if model else []),
                       "comments": cfg.get("comments") or {}},
            "has_logo": bool(cfg_row and cfg_row.logo_path), "available_sections": [{"key": k, "label": SECTION_LABELS[k]} for k in ALL_SECTIONS]}


@router.put("/assessments/{aid}/report-config")
def put_report_config(aid: str, body: ReportConfigIn, request: Request, user: User = Depends(require(Perm.edit)), db: Session = Depends(get_db)):
    a = _get_a(db, aid)
    row = db.get(ReportConfig, aid)
    existing = dict(row.config) if row else {}
    existing.update(body.model_dump(exclude_unset=True))
    if row is None:
        db.add(ReportConfig(assessment_id=aid, config=existing))
    else:
        row.config = existing
    if body.customer_name is not None:
        a.customer_name = body.customer_name
    if body.consultant_name is not None:
        a.consultant_name = body.consultant_name
    db.commit()
    audit.record(db, "report_modified", user.email, aid, detail={"fields": sorted(body.model_dump(exclude_unset=True))}, ip=client_ip(request))
    return {"ok": True}


_LOGO_MAGIC = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg"}


@router.post("/assessments/{aid}/logo")
async def upload_logo(aid: str, file: UploadFile = File(...), request: Request = None, user: User = Depends(require(Perm.edit)), db: Session = Depends(get_db)):
    _get_a(db, aid)
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise HTTPException(413, "Logo must be smaller than 2 MB")
    ext = next((e for m, e in _LOGO_MAGIC.items() if data.startswith(m)), None)
    if not ext:
        raise HTTPException(400, "Logo must be a PNG or JPEG image")
    s = get_settings()
    s.ensure_dirs()
    path = s.logos_dir / f"{aid}{ext}"
    for old in s.logos_dir.glob(f"{aid}.*"):
        old.unlink(missing_ok=True)
    path.write_bytes(data)
    row = db.get(ReportConfig, aid)
    if row is None:
        db.add(ReportConfig(assessment_id=aid, config={}, logo_path=str(path)))
    else:
        row.logo_path = str(path)
    db.commit()
    audit.record(db, "report_modified", user.email, aid, detail={"logo": True}, ip=client_ip(request) if request else None)
    return {"ok": True}


@router.get("/assessments/{aid}/logo")
def get_logo(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(ReportConfig, aid)
    if not row or not row.logo_path or not Path(row.logo_path).exists():
        raise HTTPException(404, "No logo")
    return FileResponse(row.logo_path, media_type=mimetypes.guess_type(row.logo_path)[0] or "image/png")


@router.get("/knowledge-base")
def knowledge_base(user: User = Depends(current_user)):
    return [{"code": e.code, "category": e.category, "domain": e.domain, "title": e.title, "description": e.description, "impact": e.impact,
             "business_impact": e.business_impact, "risk": e.risk, "recommendation": list(e.recommendation), "best_practice": e.best_practice,
             "priority": e.priority, "severity": e.severity} for e in kb.ENTRIES]
