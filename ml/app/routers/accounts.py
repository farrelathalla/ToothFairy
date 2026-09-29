"""Account management routes — admin only (enforced at the router level)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.user import Role
from ..schemas.user import AccountCreate, AccountUpdate, UserOut
from ..security import require_role
from ..services import accounts
from ..services.errors import EmailExists, UserNotFound

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_role(Role.admin))],
)


@router.get("", response_model=list[UserOut])
def list_accounts(db: Session = Depends(get_db)):
    return accounts.list_users(db)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)):
    try:
        return accounts.create_user(
            db,
            email=payload.email,
            name=payload.name,
            password=payload.password,
            role=payload.role,
        )
    except EmailExists as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.patch("/{user_id}", response_model=UserOut)
def update_account(user_id: int, payload: AccountUpdate, db: Session = Depends(get_db)):
    try:
        return accounts.update_user(db, user_id, **payload.model_dump(exclude_unset=True))
    except UserNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan")


@router.delete("/{user_id}", response_model=UserOut)
def deactivate_account(user_id: int, db: Session = Depends(get_db)):
    """Soft delete (deactivate) — preserves case ownership."""
    try:
        return accounts.deactivate_user(db, user_id)
    except UserNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Akun tidak ditemukan")
