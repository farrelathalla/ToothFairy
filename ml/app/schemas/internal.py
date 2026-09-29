"""Request/response contracts for the internal ML API.

These are the only shapes the Go gateway needs to know about. Keeping them explicit (rather
than passing ORM objects around, as an earlier single-process design did) is what lets the
two services scale and deploy independently.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..views import ViewKey


class AnalyzeRequest(BaseModel):
    """Run the vision pipeline for one capture."""

    case_id: str = Field(min_length=1, max_length=64)
    # view key -> absolute path on the shared media volume
    images: dict[ViewKey, str] = Field(min_length=1)


class ProgressEvent(BaseModel):
    type: Literal["progress"] = "progress"
    pct: int
    stage: str


class ResultEvent(BaseModel):
    type: Literal["result"] = "result"
    dataset_id: str


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class AdvisoryRequest(BaseModel):
    """Run the LLM/RAG advisory graph over an already-computed dataset."""

    case_id: str = Field(min_length=1, max_length=64)
    dataset_id: str = Field(min_length=1, max_length=64)
    patient_name: str | None = None
    anamnesa: dict[str, Any] = Field(default_factory=dict)


class AdvisoryResponse(BaseModel):
    diagnosis_md: str
    recommendation_md: str
    sanity_md: str
    # Non-clinical telemetry the gateway logs but does not display.
    meta: dict[str, Any] = Field(default_factory=dict)


class ModerationRequest(BaseModel):
    text: str = ""


class ModerationResponse(BaseModel):
    flagged: bool
    categories: list[str] = Field(default_factory=list)
    checked: bool = False
