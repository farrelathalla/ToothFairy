"""Uploaded intraoral/panoramic image for a case (one row per view slot)."""
from __future__ import annotations

from enum import Enum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base


class ViewKey(str, Enum):
    front = "front"
    side_left = "side_left"
    side_right = "side_right"
    up = "up"            # maxillary occlusal (upper)
    bottom = "bottom"    # mandibular occlusal (lower)
    panoramic = "panoramic"


# canonical order for display
VIEW_KEYS = [v.value for v in ViewKey]
INTRAORAL_VIEWS = [v.value for v in ViewKey if v is not ViewKey.panoramic]


class CaseImage(Base):
    __tablename__ = "case_images"
    __table_args__ = (UniqueConstraint("case_id", "view_key", name="uq_case_view"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    view_key: Mapped[str] = mapped_column(String(16))
    # path relative to settings.upload_dir, e.g. "case-.../front.jpg" → served at /media/<path>
    path: Mapped[str] = mapped_column(String(512))

    case = relationship("Case", back_populates="images")
