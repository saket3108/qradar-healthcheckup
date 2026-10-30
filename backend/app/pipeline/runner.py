"""Assessment runner – executes stages with DB checkpoints (progress tracking, resume, error recovery)."""
from __future__ import annotations

import logging
import shutil
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db.base import session_scope
from app.db.models import Assessment, AssessmentData, Finding, JobStage, utcnow
from app.ingestion.safe_extract import ArchiveSecurityError, UnsupportedArchiveError
from app.pipeline.stages import STAGE_FUNCS, STAGES, Ctx

log = logging.getLogger(__name__)

FATAL_STAGES = {"extract"}
MAX_STAGE_ATTEMPTS = 2
NON_RETRYABLE = (ArchiveSecurityError, UnsupportedArchiveError, ValueError)


def init_stages(assessment_id: str) -> None:
    with session_scope() as db:
        existing = {s.name for s in db.scalars(select(JobStage).where(JobStage.assessment_id == assessment_id))}
        for i, (name, label, _) in enumerate(STAGES):
            if name not in existing:
                db.add(JobStage(assessment_id=assessment_id, name=name, label=label, order=i))


def _save(assessment_id: str, key: str, data: Any) -> None:
    with session_scope() as db:
        row = db.scalar(select(AssessmentData).where(AssessmentData.assessment_id == assessment_id, AssessmentData.key == key))
        if row is None:
            db.add(AssessmentData(assessment_id=assessment_id, key=key, data=data))
        else:
            row.data = data
            row.updated_at = utcnow()


def _load(assessment_id: str, key: str) -> Any:
    with session_scope() as db:
        row = db.scalar(select(AssessmentData).where(AssessmentData.assessment_id == assessment_id, AssessmentData.key == key))
        return row.data if row else None


def _workdir(assessment_id: str) -> Path:
    d = get_settings().assessments_dir / assessment_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stage_artifacts_ok(name: str, workdir: Path) -> bool:
    """A 'done' stage is only trusted if the on-disk artifacts it produced still exist."""
    if name == "extract":
        return (workdir / "extracted").is_dir()
    if name == "database":
        return (workdir / "tables.json").exists()
    return True


def run_assessment(assessment_id: str, from_stage: str | None = None) -> str:
    s = get_settings()
    init_stages(assessment_id)
    workdir = _workdir(assessment_id)
    with session_scope() as db:
        a = db.get(Assessment, assessment_id)
        if a is None:
            raise LookupError(assessment_id)
        a.status, a.error, a.attempts = "processing", None, (a.attempts or 0) + 1
        a.heartbeat_at = utcnow()
        source = Path(a.source_path)
    if not source.exists():
        _fail(assessment_id, "extract", "Source archive is no longer available on disk", fatal=True)
        return "failed"

    names = [n for n, _, _ in STAGES]
    weights = {n: w for n, _, w in STAGES}
    total_w = sum(weights.values())
    had_failure = False

    if from_stage:
        with session_scope() as db:
            for st in db.scalars(select(JobStage).where(JobStage.assessment_id == assessment_id)):
                if names.index(st.name) >= names.index(from_stage):
                    st.status, st.progress, st.message, st.warnings = "pending", 0.0, None, None

    def overall_progress(done_names: set[str], cur: str | None, cur_p: float) -> float:
        done = sum(weights[n] for n in done_names)
        if cur:
            done += weights[cur] * cur_p
        return round(100.0 * done / total_w, 1)

    done_names: set[str] = set()
    with session_scope() as db:
        for st in db.scalars(select(JobStage).where(JobStage.assessment_id == assessment_id)):
            if st.status == "done" and _stage_artifacts_ok(st.name, workdir):
                done_names.add(st.name)
            elif st.status == "done":
                st.status = "pending"

    for name in names:
        if name in done_names:
            continue
        # a stage whose prerequisite artefacts vanished forces re-running upstream first (handled by order above)
        warnings: list[str] = []

        def progress(p: float, msg: str | None = None, _name=name) -> None:
            with session_scope() as db:
                st = db.scalar(select(JobStage).where(JobStage.assessment_id == assessment_id, JobStage.name == _name))
                st.progress = max(0.0, min(1.0, p))
                if msg:
                    st.message = msg[:500]
                a2 = db.get(Assessment, assessment_id)
                a2.current_stage = _name
                a2.progress = overall_progress(done_names, _name, p)
                a2.heartbeat_at = utcnow()

        ctx = Ctx(assessment_id, workdir, source, lambda k: _load(assessment_id, k), lambda k, v: _save(assessment_id, k, v), progress, warnings.append)
        err: str | None = None
        for attempt in range(1, MAX_STAGE_ATTEMPTS + 1):
            with session_scope() as db:
                st = db.scalar(select(JobStage).where(JobStage.assessment_id == assessment_id, JobStage.name == name))
                st.status, st.attempts, st.started_at, st.finished_at = "running", st.attempts + 1, utcnow(), None
                a2 = db.get(Assessment, assessment_id)
                a2.current_stage = name
            try:
                msg = STAGE_FUNCS[name](ctx)
                with session_scope() as db:
                    st = db.scalar(select(JobStage).where(JobStage.assessment_id == assessment_id, JobStage.name == name))
                    st.status, st.progress, st.message, st.finished_at = "done", 1.0, (msg or "")[:500], utcnow()
                    st.warnings = warnings or None
                err = None
                break
            except NON_RETRYABLE as e:
                err = f"{type(e).__name__}: {e}"
                log.warning("stage %s failed (non retryable): %s", name, err)
                break
            except Exception as e:                      # noqa: BLE001
                err = f"{type(e).__name__}: {e}"
                log.error("stage %s attempt %d failed: %s\n%s", name, attempt, err, traceback.format_exc())
                time.sleep(min(2 * attempt, 5))
        if err is None:
            done_names.add(name)
            with session_scope() as db:
                db.get(Assessment, assessment_id).progress = overall_progress(done_names, None, 0)
            continue
        had_failure = True
        _fail(assessment_id, name, err, fatal=name in FATAL_STAGES)
        if name in FATAL_STAGES:
            return "failed"
        # non-fatal: mark stage failed, continue with remaining stages using whatever data exists
        done_names.add(name)

    finalize(assessment_id, partial=had_failure)
    return "partial" if had_failure else "completed"


def _fail(assessment_id: str, stage: str, error: str, fatal: bool) -> None:
    with session_scope() as db:
        st = db.scalar(select(JobStage).where(JobStage.assessment_id == assessment_id, JobStage.name == stage))
        if st:
            st.status, st.message, st.finished_at = "failed", error[:1000], utcnow()
        if fatal:
            a = db.get(Assessment, assessment_id)
            a.status, a.error, a.current_stage = "failed", f"[{stage}] {error}"[:2000], stage


def finalize(assessment_id: str, partial: bool = False) -> None:
    findings = _load(assessment_id, "_findings") or []
    scores = _load(assessment_id, "scores") or {}
    env = _load(assessment_id, "a_environment") or {}
    summary = _load(assessment_id, "executive_summary")
    with session_scope() as db:
        db.execute(delete(Finding).where(Finding.assessment_id == assessment_id))
        for f in findings:
            db.add(Finding(
                assessment_id=assessment_id, code=f["code"], category=f["category"], source=f["source"], source_ref=(str(f["source_ref"]) if f.get("source_ref") is not None else None),
                severity=f["severity"], priority=f["priority"], title=f["title"][:500], observation=f["observation"], description=f["description"],
                root_cause=f.get("root_cause") or "", impact=f["impact"], business_impact=f["business_impact"], risk=f["risk"],
                recommendation=f["recommendation"], best_practice=f["best_practice"], evidence=f.get("evidence"), hosts=f.get("hosts")))
        a = db.get(Assessment, assessment_id)
        a.status = "partial" if partial else "completed"
        a.progress, a.current_stage = 100.0, None
        a.qradar_version = env.get("version")
        a.overall_score = (scores.get("overall") or {}).get("score")
        a.summary = {"overall": scores.get("overall"), "categories": scores.get("categories"), "headline": (summary or {}).get("headline"),
                     "findings": len(findings)}


def purge_workdir(assessment_id: str) -> None:
    shutil.rmtree(get_settings().assessments_dir / assessment_id, ignore_errors=True)


def recover_stale_jobs() -> list[str]:
    """Return IDs of jobs left in 'processing'/'queued' by a crashed worker – they are resumed from their checkpoints."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    ids: list[str] = []
    with session_scope() as db:
        for a in db.scalars(select(Assessment).where(Assessment.status.in_(["processing", "queued"]))):
            hb = a.heartbeat_at or a.created_at
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            if (now - hb).total_seconds() > s.stale_job_seconds or a.status == "queued":
                a.status = "queued"
                ids.append(a.id)
    return ids
