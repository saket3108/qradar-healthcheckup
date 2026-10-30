from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require
from app.api.schemas import LoginIn, TokenOut, UserCreate, UserOut, UserUpdate
from app.core.security import Perm, create_access_token, hash_password, login_throttle, verify_password
from app.db.base import get_db
from app.db.models import AuditLog, User, utcnow
from app.services import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/users", tags=["users"])
audit_router = APIRouter(prefix="/api/audit", tags=["audit"])

_DUMMY_HASH = hash_password("dummy-password-1")   # constant-time-ish behaviour for unknown users


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    email = body.email.lower()
    if login_throttle.is_locked(email):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts. Try again later.")
    user = db.scalar(select(User).where(User.email == email))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or not user.is_active:
        login_throttle.record_failure(email)
        audit.record(db, "login_failed", user_email=email, ip=client_ip(request))
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    login_throttle.reset(email)
    user.last_login = utcnow()
    db.commit()
    audit.record(db, "login", user_email=email, ip=client_ip(request))
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@users_router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(require(Perm.manage_users)), db: Session = Depends(get_db)):
    return list(db.scalars(select(User).order_by(User.created_at)))


@users_router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require(Perm.manage_users)), db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "A user with this email already exists")
    u = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password), role=body.role.value)
    db.add(u)
    db.commit()
    audit.record(db, "user_created", admin.email, target=email, detail={"role": u.role}, ip=client_ip(request))
    return u


@users_router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: str, body: UserUpdate, request: Request, admin: User = Depends(require(Perm.manage_users)), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.is_active is False or (body.role and body.role.value != "administrator")):
        raise HTTPException(400, "Administrators cannot demote or disable themselves")
    if body.full_name is not None:
        u.full_name = body.full_name
    if body.role is not None:
        u.role = body.role.value
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.password:
        u.password_hash = hash_password(body.password)
    db.commit()
    audit.record(db, "user_updated", admin.email, target=u.email, ip=client_ip(request))
    return u


@audit_router.get("")
def list_audit(assessment_id: str | None = None, action: str | None = None, limit: int = 200, offset: int = 0,
               _: User = Depends(require(Perm.audit)), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.ts.desc())
    if assessment_id:
        q = q.where(AuditLog.assessment_id == assessment_id)
    if action:
        q = q.where(AuditLog.action == action)
    rows = db.scalars(q.limit(min(limit, 1000)).offset(offset))
    return [{"id": r.id, "ts": r.ts, "user": r.user_email, "action": r.action, "assessment_id": r.assessment_id, "target": r.target,
             "detail": r.detail, "ip": r.ip} for r in rows]
