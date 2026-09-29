"""Pydantic schemas for users / accounts."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ..models.user import Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    role: Role
    is_active: bool
    created_at: datetime


class AccountCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=255)
    role: Role = Role.doctor
    password: str = Field(min_length=6, max_length=128)


class AccountUpdate(BaseModel):
    """All fields optional — only provided ones are changed."""
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
