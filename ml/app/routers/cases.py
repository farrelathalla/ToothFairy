"""Case routes — doctor only. Create with anamnesa, list/get own cases, upload images."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.user import Role, User
from ..schemas.case import (
    CaseCreate,
    CaseImageOut,
    CaseListItem,
    CaseOut,
    CaseStatusOut,
    RunResponse,
)
from ..security import require_role
from ..services import cases, jobs
from ..services.errors import CaseNotFound, InvalidImage

router = APIRouter(prefix="/cases", tags=["cases"])

DoctorDep = require_role(Role.doctor)


def serialize_case(case) -> CaseOut:
    out = CaseOut.model_validate(case)
    out.images = [
        CaseImageOut(view_key=i.view_key, path=i.path, url=cases.media_url(i)) for i in case.images
    ]
    return out


def _load_owned(db: Session, doctor: User, case_id: str):
    try:
        return cases.get_case(db, doctor, case_id)
    except CaseNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kasus tidak ditemukan")


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreate, doctor: User = Depends(DoctorDep), db: Session = Depends(get_db)):
    case = cases.create_case(
        db, doctor, patient_name=payload.patient_name, anamnesa=payload.anamnesa.model_dump()
    )
    return serialize_case(case)


@router.get("", response_model=list[CaseListItem])
def list_cases(doctor: User = Depends(DoctorDep), db: Session = Depends(get_db)):
    return cases.list_cases(db, doctor)


@router.get("/{case_id}", response_model=CaseOut)
def get_case(case_id: str, doctor: User = Depends(DoctorDep), db: Session = Depends(get_db)):
    return serialize_case(_load_owned(db, doctor, case_id))


@router.post("/{case_id}/images", response_model=CaseOut)
async def upload_images(
    case_id: str,
    doctor: User = Depends(DoctorDep),
    db: Session = Depends(get_db),
    front: UploadFile = File(None),
    side_left: UploadFile = File(None),
    side_right: UploadFile = File(None),
    up: UploadFile = File(None),
    bottom: UploadFile = File(None),
    panoramic: UploadFile = File(None),
):
    case = _load_owned(db, doctor, case_id)
    incoming = {
        "front": front,
        "side_left": side_left,
        "side_right": side_right,
        "up": up,
        "bottom": bottom,
        "panoramic": panoramic,
    }
    saved = 0
    for key, uf in incoming.items():
        if uf is not None and uf.filename:
            data = await uf.read()
            try:
                cases.save_image(
                    db, case, key, filename=uf.filename, content_type=uf.content_type, data=data
                )
            except InvalidImage as e:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
            saved += 1

    if saved == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tidak ada gambar diunggah")

    db.refresh(case)
    return serialize_case(case)


@router.post("/{case_id}/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def run_case(case_id: str, doctor: User = Depends(DoctorDep), db: Session = Depends(get_db)):
    case = _load_owned(db, doctor, case_id)
    if not case.images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unggah minimal satu gambar sebelum menjalankan analisis",
        )
    jobs.enqueue(db, case)
    return RunResponse(status=case.status, case_id=case.id)


@router.get("/{case_id}/status", response_model=CaseStatusOut)
def case_status(case_id: str, doctor: User = Depends(DoctorDep), db: Session = Depends(get_db)):
    case = _load_owned(db, doctor, case_id)
    db.refresh(case)
    return CaseStatusOut.model_validate(case)
