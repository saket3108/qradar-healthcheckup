from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import Assessment, Export
from app.reports.model import build_report_model


def generate(db: Session, a: Assessment, fmt: str, user_email: str | None) -> Export:
    model = build_report_model(db, a)
    if fmt == "pdf":
        from app.reports.pdf import build_pdf
        data = build_pdf(model)
    elif fmt == "docx":
        from app.reports.docx_report import build_docx
        data = build_docx(model)
    elif fmt == "pptx":
        from app.reports.pptx_report import build_pptx
        data = build_pptx(model)
    else:
        raise ValueError(fmt)
    s = get_settings()
    s.ensure_dirs()
    exp = Export(assessment_id=a.id, fmt=fmt, path="", size=len(data), created_by=user_email)
    db.add(exp)
    db.flush()
    path = s.exports_dir / f"{a.id}_{exp.id}.{fmt}"
    path.write_bytes(data)
    exp.path = str(path)
    db.commit()
    return exp
