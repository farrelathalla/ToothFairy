"""Auth request/response schemas."""
from __future__ import annotations

from pydantic import BaseModel, EmailStr

from .user import UserOut


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut
