from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import Role


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime | None = None
    last_login: datetime | None = None


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(default="", max_length=255)
    password: str = Field(min_length=10, max_length=72)
    role: Role = Role.read_only

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        if not (any(c.isalpha() for c in v) and any(c.isdigit() for c in v)):
            raise ValueError("Password must contain letters and digits")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=10, max_length=72)


class AssessmentCreate(BaseModel):
    upload_id: str
    name: str | None = Field(default=None, max_length=255)
    customer_name: str = Field(default="", max_length=255)
    consultant_name: str = Field(default="", max_length=255)


class AssessmentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    customer_name: str | None = Field(default=None, max_length=255)
    consultant_name: str | None = Field(default=None, max_length=255)


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    label: str
    order: int
    status: str
    progress: float
    attempts: int
    message: str | None = None
    warnings: list[str] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    customer_name: str
    consultant_name: str
    source_filename: str
    source_size: int
    status: str
    progress: float
    current_stage: str | None = None
    error: str | None = None
    qradar_version: str | None = None
    overall_score: float | None = None
    created_at: datetime
    updated_at: datetime
    summary: dict | None = None


class AssessmentDetail(AssessmentOut):
    stages: list[StageOut] = []


class CommentIn(BaseModel):
    text: str = Field(max_length=20000)


class FindingUpdate(BaseModel):
    status: str | None = Field(default=None, pattern="^(open|accepted|resolved|dismissed)$")
    severity: str | None = Field(default=None, pattern="^(critical|high|medium|low|info)$")


class ReportConfigIn(BaseModel):
    customer_name: str | None = Field(default=None, max_length=255)
    consultant_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    sections: list[str] | None = None
    notes: str | None = Field(default=None, max_length=20000)
    next_steps: list[str] | None = None
    classification: str | None = Field(default=None, max_length=64)
    comments: dict[str, str] | None = None

    @field_validator("sections")
    @classmethod
    def known(cls, v):
        if v is None:
            return v
        from app.reports.model import ALL_SECTIONS
        bad = [s for s in v if s not in ALL_SECTIONS]
        if bad:
            raise ValueError(f"Unknown sections: {bad}")
        return v


class AssistantIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
