"""Case lifecycle: create, list, get (owner-scoped), and image upload."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models.case import Case, CaseStatus
from ..models.case_image import VIEW_KEYS, CaseImage
from ..models.user import User
from .errors import CaseNotFound, InvalidImage

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_CONTENT = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MB


def new_case_id() -> str:
    return "case-" + time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def create_case(db: Session, doctor: User, *, patient_name: str | None, anamnesa: dict) -> Case:
    case = Case(
        id=new_case_id(),
        doctor_id=doctor.id,
        patient_name=(patient_name.strip() if patient_name else None),
        anamnesa=anamnesa or {},
        status=CaseStatus.draft.value,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return case


def list_cases(db: Session, doctor: User) -> list[Case]:
    return list(
        db.scalars(
            select(Case).where(Case.doctor_id == doctor.id).order_by(Case.created_at.desc())
        )
    )


def get_case(db: Session, doctor: User, case_id: str) -> Case:
    """Owner-scoped fetch. Missing OR not-owned both raise CaseNotFound (don't leak existence)."""
    case = db.get(Case, case_id)
    if case is None or case.doctor_id != doctor.id:
        raise CaseNotFound(case_id)
    return case


def _ext_for(filename: str | None, content_type: str | None) -> str:
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in ALLOWED_EXT:
            return ".jpg" if ext == ".jpeg" else ext
    if content_type:
        ct = content_type.lower()
        if ct in ("image/jpeg", "image/jpg"):
            return ".jpg"
        if ct == "image/png":
            return ".png"
        if ct == "image/webp":
            return ".webp"
    return ""


def save_image(
    db: Session,
    case: Case,
    view_key: str,
    *,
    filename: str | None,
    content_type: str | None,
    data: bytes,
) -> CaseImage:
    if view_key not in VIEW_KEYS:
        raise InvalidImage(f"unknown view '{view_key}'")
    if not data:
        raise InvalidImage("empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise InvalidImage("file too large (max 25MB)")

    ext = _ext_for(filename, content_type)
    ok_ext = Path(filename or "").suffix.lower() in ALLOWED_EXT
    ok_ct = (content_type or "").lower() in ALLOWED_CONTENT
    if not (ok_ext or ok_ct):
        raise InvalidImage("unsupported image type (use jpg/png/webp)")
    if not ext:
        ext = ".jpg"

    case_dir = settings.upload_dir / case.id
    case_dir.mkdir(parents=True, exist_ok=True)
    rel_path = f"{case.id}/{view_key}{ext}"
    dest = settings.upload_dir / rel_path

    # replace: remove any prior file for this slot (possibly different extension)
    existing = db.scalar(
        select(CaseImage).where(CaseImage.case_id == case.id, CaseImage.view_key == view_key)
    )
    if existing is not None:
        old = settings.upload_dir / existing.path
        if old.exists() and old != dest:
            old.unlink()

    dest.write_bytes(data)

    if existing is not None:
        existing.path = rel_path
        img = existing
    else:
        img = CaseImage(case_id=case.id, view_key=view_key, path=rel_path)
        db.add(img)

    if case.status == CaseStatus.draft.value:
        case.status = CaseStatus.uploaded.value

    db.commit()
    db.refresh(img)
    return img


def media_url(image: CaseImage) -> str:
    return f"/media/{image.path}"
