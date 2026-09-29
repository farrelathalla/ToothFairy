"""Pydantic schemas for cases: the anamnesa questionnaire + case DTOs."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from ..models.case import CaseStatus
from ..models.case_image import ViewKey


class Anamnesa(BaseModel):
    """Anamnesa (Sacred Seven) + riwayat. Free-text; a small subset is required.

    All fields are Indonesian-labelled on the frontend. Stored as a JSON blob on the case.
    """
    # --- Sacred Seven ---
    lokasi: str = Field(min_length=1, description="Lokasi keluhan utama + apakah menjalar")
    quality: str = Field(min_length=1, description="Kualitas nyeri")
    severity: str = Field(default="", description="Keparahan / dampak")
    chronology: str = Field(default="", description="Kapan & seberapa sering")
    setting: str = Field(default="", description="Kondisi saat nyeri muncul")
    aggravating_alleviating: str = Field(default="", description="Memperparah / meredakan")
    associated: str = Field(default="", description="Gejala penyerta")

    # --- Riwayat ---
    pernah_ke_drg_lain: str = Field(default="", description="Sudah ke drg lain?")
    obat_digunakan: str = Field(default="", description="Obat yang sudah digunakan")
    tindakan_sebelumnya: str = Field(default="", description="Tindakan drg sebelumnya")
    penyakit_sistemik: str = Field(default="", description="Penyakit/kondisi sistemik")
    pernah_menunda: str = Field(default="", description="Pernah menunda kunjungan?")
    alasan_kuat: str = Field(min_length=1, description="Alasan/motivasi utama datang")


class CaseCreate(BaseModel):
    patient_name: str | None = Field(default=None, max_length=255)
    anamnesa: Anamnesa


class CaseImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    view_key: ViewKey
    path: str
    url: str = ""  # /media/<path>, filled by the router


class CaseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_name: str | None
    status: CaseStatus
    dataset_id: str | None
    created_at: datetime
    updated_at: datetime


class RunResponse(BaseModel):
    status: CaseStatus
    case_id: str


class CaseStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: CaseStatus
    progress: int
    stage: str | None
    error: str | None
    dataset_id: str | None


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doctor_id: int
    patient_name: str | None
    anamnesa: dict
    status: CaseStatus
    progress: int
    stage: str | None
    dataset_id: str | None
    error: str | None
    diagnosis_md: str | None
    recommendation_md: str | None
    created_at: datetime
    updated_at: datetime
    images: list[CaseImageOut] = []
