"""FastAPI application factory."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.api import routes_assess, routes_auth, routes_misc
from app.core.config import get_settings
from app.core.security import Role, hash_password
from app.db.base import init_db, session_scope
from app.db.models import User

log = logging.getLogger("qhc")


def bootstrap_admin() -> None:
    s = get_settings()
    if not (s.admin_email and s.admin_password):
        return
    with session_scope() as db:
        if db.scalar(select(User).where(User.email == s.admin_email.lower())) is None:
            db.add(User(email=s.admin_email.lower(), full_name="Administrator", password_hash=hash_password(s.admin_password), role=Role.administrator.value))
            log.info("Created bootstrap administrator %s", s.admin_email)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.ensure_dirs()
    if s.environment == "production" and s.secret_key.startswith("dev-only"):
        raise RuntimeError("QHC_SECRET_KEY must be set to a strong random value in production")
    if s.database_url.startswith("sqlite"):
        init_db()
    bootstrap_admin()
    from app.pipeline import dispatch
    from app.pipeline.runner import recover_stale_jobs

    for aid in recover_stale_jobs():     # resume jobs interrupted by a crash/restart
        dispatch.enqueue(aid)
    yield
    dispatch.shutdown_pool()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    app.include_router(routes_auth.router)
    app.include_router(routes_auth.users_router)
    app.include_router(routes_auth.audit_router)
    app.include_router(routes_assess.router)
    app.include_router(routes_misc.router)

    @app.get("/api/health", tags=["system"])
    def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    return app


app = create_app()
