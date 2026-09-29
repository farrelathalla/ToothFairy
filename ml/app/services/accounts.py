"""Account (user) management: create, list, get, update, deactivate.

Kept framework-agnostic — raises domain errors from services/errors.py which the routers
translate to HTTP responses.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.user import Role, User
from ..security import hash_password
from .errors import EmailExists, UserNotFound


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == _normalize_email(email)))


def get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise UserNotFound(f"user {user_id} not found")
    return user


def list_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())))


def create_user(
    db: Session,
    *,
    email: str,
    name: str,
    password: str,
    role: Role | str = Role.doctor,
) -> User:
    email = _normalize_email(email)
    if get_by_email(db, email) is not None:
        raise EmailExists(f"email {email} already registered")
    role_value = role.value if isinstance(role, Role) else Role(role).value
    user = User(
        email=email,
        name=name.strip(),
        role=role_value,
        password_hash=hash_password(password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user_id: int,
    *,
    name: str | None = None,
    role: Role | str | None = None,
    is_active: bool | None = None,
    password: str | None = None,
) -> User:
    user = get_user(db, user_id)
    if name is not None:
        user.name = name.strip()
    if role is not None:
        user.role = role.value if isinstance(role, Role) else Role(role).value
    if is_active is not None:
        user.is_active = is_active
    if password is not None:
        user.password_hash = hash_password(password)
    db.commit()
    db.refresh(user)
    return user


def deactivate_user(db: Session, user_id: int) -> User:
    """Soft delete: keep the row (cases FK to it) but block login."""
    return update_user(db, user_id, is_active=False)
