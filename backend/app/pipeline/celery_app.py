"""Celery application (worker entrypoint: ``celery -A app.pipeline.celery_app worker``)."""
from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready

from app.core.config import get_settings

s = get_settings()
celery_app = Celery("qhc", broker=s.redis_url, backend=s.redis_url)
celery_app.conf.update(
    task_acks_late=True,                 # job survives worker crash and is redelivered
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,        # fair scheduling for multi-GB jobs
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=60 * 60 * 12,
    result_expires=3600,
)


@celery_app.task(name="qhc.process_assessment", bind=True, max_retries=2, default_retry_delay=30)
def process_assessment(self, assessment_id: str, from_stage: str | None = None) -> str:
    from app.pipeline.runner import run_assessment

    try:
        return run_assessment(assessment_id, from_stage)
    except LookupError:
        return "missing"
    except Exception as exc:   # noqa: BLE001
        raise self.retry(exc=exc)


@worker_ready.connect
def _resume_stale(**_):   # pragma: no cover - requires worker runtime
    from app.pipeline.runner import recover_stale_jobs

    for aid in recover_stale_jobs():
        process_assessment.delay(aid)
