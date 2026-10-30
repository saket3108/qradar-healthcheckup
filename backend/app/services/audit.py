"""Audit trail helper."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import AuditLog

ACTIONS = {
    "login", "login_failed", "user_created", "user_updated", "upload", "assessment_created", "assessment_deleted",
    "assessment_reprocessed", "report_created", "report_modified", "comment_updated", "finding_updated",
    "export_generated", "assistant_query",
}


def record(db: Session, action: str, user_email: str | None = None, assessment_id: str | None = None,
           target: str | None = None, detail: dict | None = None, ip: str | None = None) -> None:
    db.add(AuditLog(user_email=user_email, action=action, assessment_id=assessment_id, target=target,
                    detail=detail, ip=ip))
    db.commit()
