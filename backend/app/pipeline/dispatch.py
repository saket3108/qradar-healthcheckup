"""Job dispatch: Celery (Redis broker) in production, bounded in-process thread pool for dev/tests."""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from app.core.config import get_settings

log = logging.getLogger(__name__)
_pool: ThreadPoolExecutor | None = None
_lock = threading.Lock()
_inflight: set[str] = set()


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    with _lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(max_workers=get_settings().inline_workers, thread_name_prefix="assess")
        return _pool


def shutdown_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.shutdown(wait=True, cancel_futures=False)
            _pool = None


def _run_inline(assessment_id: str, from_stage: str | None) -> None:
    from app.pipeline.runner import run_assessment

    try:
        run_assessment(assessment_id, from_stage)
    except Exception:   # noqa: BLE001
        log.exception("assessment %s crashed", assessment_id)
        from app.db.base import session_scope
        from app.db.models import Assessment

        with session_scope() as db:
            a = db.get(Assessment, assessment_id)
            if a and a.status == "processing":
                a.status, a.error = "failed", "Unexpected worker error - see server logs; use Resume to retry"
    finally:
        with _lock:
            _inflight.discard(assessment_id)


def enqueue(assessment_id: str, from_stage: str | None = None) -> None:
    s = get_settings()
    with _lock:
        if assessment_id in _inflight:
            return
        _inflight.add(assessment_id)
    if s.run_mode == "celery":
        from app.pipeline.celery_app import process_assessment

        process_assessment.delay(assessment_id, from_stage)
        with _lock:
            _inflight.discard(assessment_id)
    else:
        _get_pool().submit(_run_inline, assessment_id, from_stage)


def wait_idle(timeout: float = 120.0) -> None:
    import time

    end = time.time() + timeout
    while time.time() < end:
        with _lock:
            if not _inflight:
                return
        time.sleep(0.1)
