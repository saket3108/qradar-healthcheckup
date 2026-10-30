"""Password hashing, JWT handling, RBAC permission model and login throttling."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from enum import Enum

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


class Role(str, Enum):
    administrator = "administrator"
    consultant = "consultant"
    manager = "manager"
    read_only = "read_only"


class Perm(str, Enum):
    view = "view"
    upload = "upload"
    edit = "edit"            # comments, report config
    export = "export"
    delete = "delete"
    audit = "audit"
    manage_users = "manage_users"


ROLE_PERMS: dict[Role, set[Perm]] = {
    Role.administrator: set(Perm),
    Role.consultant: {Perm.view, Perm.upload, Perm.edit, Perm.export},
    Role.manager: {Perm.view, Perm.export, Perm.audit},
    Role.read_only: {Perm.view},
}


def has_perm(role: str, perm: Perm) -> bool:
    try:
        return perm in ROLE_PERMS[Role(role)]
    except (ValueError, KeyError):
        return False


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("ascii"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str, minutes: int | None = None) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutes or s.access_token_minutes)
    return jwt.encode({"sub": subject, "role": role, "exp": exp}, s.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])


class LoginThrottle:
    """In-memory failed-login lockout (per e-mail)."""

    def __init__(self) -> None:
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        window = get_settings().login_lockout_minutes * 60
        now = time.time()
        recent = [t for t in self._fails.get(key, []) if now - t < window]
        self._fails[key] = recent
        return recent

    def is_locked(self, key: str) -> bool:
        with self._lock:
            return len(self._recent(key.lower())) >= get_settings().login_max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._recent(key.lower()).append(time.time())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._fails.clear()
            else:
                self._fails.pop(key.lower(), None)


login_throttle = LoginThrottle()
