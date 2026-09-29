"""Seed default accounts (and, from Phase 6, demo cases).

    cd backend && python seed.py

Idempotent: existing accounts (matched by email) are left untouched.

Default credentials (change in production):
    admin@toothfairy.com  / admin123   (role: admin)
    doctor@toothfairy.com / doctor123  (role: doctor)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import SessionLocal, init_db  # noqa: E402
from app.llm import graph  # noqa: E402
from app.models.case import Case, CaseStatus  # noqa: E402
from app.models.user import Role  # noqa: E402
from app.services import accounts  # noqa: E402

DEFAULT_ACCOUNTS = [
    {"email": "admin@toothfairy.com", "name": "Administrator", "role": Role.admin, "password": "admin123"},
    {"email": "doctor@toothfairy.com", "name": "Dokter Gigi", "role": Role.doctor, "password": "doctor123"},
]

# The real `claude-sonnet-5` diagnoses for the 4 demo cases, generated once via
# `evals.run_evals` and committed here so a fresh clone shows them **without any API call**
# (the SQLite DB is git-ignored, so seeding is the only place these can be restored). If a
# file is absent the case falls back to the deterministic graph stub.
SEED_DIAG_DIR = Path(__file__).resolve().parent / "seed_data" / "diagnoses"

# Four demo history cases, each linked to a precomputed dataset (CLAUDE.md §7). Deterministic
# ids make re-seeding idempotent. Anamnesa is plausible Indonesian filler (user-approved).
DEMO_CASES = [
    {
        "id": "demo-original", "dataset": "original", "patient_name": "Ananda R. (7 th)",
        "anamnesa": {
            "lokasi": "Gigi depan atas, ngilu saat minum dingin",
            "quality": "Ngilu tajam sesaat",
            "severity": "Skala 4, belum mengganggu tidur",
            "chronology": "Sejak ±2 minggu, muncul saat makan/minum",
            "setting": "Terutama saat mengunyah makanan manis",
            "aggravating_alleviating": "Diperparah manis & dingin; reda dengan berkumur air hangat",
            "associated": "Tidak ada bengkak",
            "pernah_ke_drg_lain": "Belum pernah",
            "obat_digunakan": "Belum ada",
            "tindakan_sebelumnya": "Belum ada",
            "penyakit_sistemik": "Tidak ada",
            "pernah_menunda": "Tidak",
            "alasan_kuat": "Orang tua ingin memastikan gigi anak sebelum makin parah",
        },
    },
    {
        "id": "demo-set1", "dataset": "set1", "patient_name": "Bima S. (6 th)",
        "anamnesa": {
            "lokasi": "Geraham kiri bawah",
            "quality": "Cenut-cenut ringan",
            "severity": "Skala 3",
            "chronology": "Kadang-kadang, ±1 bulan",
            "setting": "Saat mengunyah",
            "aggravating_alleviating": "Diperparah makanan keras",
            "associated": "Tidak ada",
            "pernah_ke_drg_lain": "Belum",
            "obat_digunakan": "Belum ada",
            "tindakan_sebelumnya": "Belum ada",
            "penyakit_sistemik": "Tidak ada",
            "pernah_menunda": "Tidak",
            "alasan_kuat": "Pemeriksaan rutin penyuluhan karies",
        },
    },
    {
        "id": "demo-set2", "dataset": "set2", "patient_name": "Citra P. (8 th)",
        "anamnesa": {
            "lokasi": "Beberapa gigi geraham atas & bawah",
            "quality": "Nyeri cenut-cenut, kadang tajam",
            "severity": "Skala 5, sesekali mengganggu tidur",
            "chronology": "±2 bulan, makin sering",
            "setting": "Saat mengunyah dan tiba-tiba saat diam",
            "aggravating_alleviating": "Diperparah manis; reda sementara dengan paracetamol",
            "associated": "Gusi kadang ngilu",
            "pernah_ke_drg_lain": "Pernah, hanya dibersihkan",
            "obat_digunakan": "Paracetamol sirup",
            "tindakan_sebelumnya": "Pembersihan karang gigi",
            "penyakit_sistemik": "Tidak ada",
            "pernah_menunda": "Ya, sekitar 1 bulan",
            "alasan_kuat": "Nyeri makin sering dan mengganggu makan",
        },
    },
    {
        "id": "demo-set3", "dataset": "set3", "patient_name": "Dinda A. (7 th)",
        "anamnesa": {
            "lokasi": "Hampir seluruh kuadran, terparah gigi depan atas",
            "quality": "Nyeri spontan, berdenyut",
            "severity": "Skala 7, sering mengganggu tidur malam",
            "chronology": "±3 bulan, hampir tiap hari",
            "setting": "Spontan saat diam maupun saat mengunyah",
            "aggravating_alleviating": "Diperparah manis & dingin; obat hanya meredakan sebentar",
            "associated": "Gusi bengkak ringan, sesekali sakit kepala",
            "pernah_ke_drg_lain": "Belum pernah",
            "obat_digunakan": "Paracetamol, ibuprofen anak",
            "tindakan_sebelumnya": "Belum ada",
            "penyakit_sistemik": "Tidak ada",
            "pernah_menunda": "Ya, beberapa bulan karena takut ke dokter gigi",
            "alasan_kuat": "Karies sudah rampant dan anak kesakitan hebat",
        },
    },
]


def seed_accounts(db) -> list[str]:
    """Create any missing default accounts. Returns the emails newly created."""
    created: list[str] = []
    for spec in DEFAULT_ACCOUNTS:
        if accounts.get_by_email(db, spec["email"]) is None:
            accounts.create_user(
                db,
                email=spec["email"],
                name=spec["name"],
                role=spec["role"],
                password=spec["password"],
            )
            created.append(spec["email"])
    return created


def seed_demo_cases(db) -> list[str]:
    """Create the 4 demo history cases (done, linked to a dataset) for the seeded doctor.
    Idempotent by deterministic case id. Returns the ids newly created."""
    doctor = accounts.get_by_email(db, "doctor@toothfairy.com")
    if doctor is None:
        return []
    created: list[str] = []
    for spec in DEMO_CASES:
        if db.get(Case, spec["id"]) is not None:
            continue
        case = Case(
            id=spec["id"],
            doctor_id=doctor.id,
            patient_name=spec["patient_name"],
            anamnesa=spec["anamnesa"],
            status=CaseStatus.done.value,
            progress=100,
            stage="Selesai",
            dataset_id=spec["dataset"],
        )
        llm = graph.run(case)
        # Prefer the committed real diagnosis (see SEED_DIAG_DIR); recommendation + sanity are
        # still the Phase-8 stubs (Phase 11).
        real_diag = SEED_DIAG_DIR / f"{spec['id']}.md"
        case.diagnosis_md = (
            real_diag.read_text(encoding="utf-8") if real_diag.exists() else llm["diagnosis_md"]
        )
        case.recommendation_md = llm["recommendation_md"]
        case.sanity_md = llm["sanity_md"]
        db.add(case)
        created.append(spec["id"])
    db.commit()
    return created


def run() -> None:
    init_db()
    db = SessionLocal()
    try:
        created = seed_accounts(db)
        created_cases = seed_demo_cases(db)
    finally:
        db.close()
    if created:
        print(f"Seeded accounts: {', '.join(created)}")
    else:
        print("Accounts already present - nothing to seed.")
    if created_cases:
        print(f"Seeded demo cases: {', '.join(created_cases)}")
    else:
        print("Demo cases already present - nothing to seed.")


if __name__ == "__main__":
    run()
