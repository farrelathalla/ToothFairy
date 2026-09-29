"""Patient case: anamnesa + uploaded images + inference status + (later) LLM output."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class CaseStatus(str, Enum):
    draft = "draft"          # created, no images yet
    uploaded = "uploaded"    # at least one image uploaded
    queued = "queued"        # inference job scheduled
    running = "running"      # inference in progress
    done = "done"            # results ready
    failed = "failed"        # inference errored


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    patient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    anamnesa: Mapped[dict] = mapped_column(JSON, default=dict)

    status: Mapped[str] = mapped_column(String(16), default=CaseStatus.draft.value)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM output (stubbed until Phase 8)
    diagnosis_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    sanity_md: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    images = relationship(
        "CaseImage", back_populates="case", cascade="all, delete-orphan", order_by="CaseImage.id"
    )
