"""jobs: run_case_job drives a case queued→running→done (or failed), persisting progress,
dataset_id, and the LLM stub output. enqueue schedules it on a single background worker."""
import time

from app.config import settings
from app.models.case import Case, CaseStatus
from app.services import accounts, cases, jobs

ANAMNESA = {
    "lokasi": "Geraham kiri bawah", "quality": "Cenut-cenut", "severity": "Skala 6",
    "chronology": "3 hari", "setting": "Saat mengunyah",
    "aggravating_alleviating": "Manis", "associated": "Bengkak",
    "pernah_ke_drg_lain": "Belum", "obat_digunakan": "Paracetamol",
    "tindakan_sebelumnya": "Belum", "penyakit_sistemik": "Tidak ada",
    "pernah_menunda": "Ya", "alasan_kuat": "Sulit tidur",
}


def _case(db, with_images=True):
    doc = accounts.create_user(db, email="d@x.io", name="D", password="secret1")
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)
    if with_images:
        cases.save_image(db, case, "up", filename="up.jpg", content_type="image/jpeg",
                         data=b"\xff\xd8fakejpeg")
    return case


def test_run_case_job_completes(db):
    case = _case(db)
    jobs.run_case_job(case.id)

    fresh = db.get(Case, case.id)
    db.refresh(fresh)
    assert fresh.status == CaseStatus.done.value
    assert fresh.progress == 100
    assert fresh.dataset_id
    assert (settings.results_dir / fresh.dataset_id / "detections.json").exists()
    # LLM stub persisted
    assert fresh.diagnosis_md and fresh.recommendation_md


def test_run_case_job_failure_sets_failed(db, monkeypatch):
    case = _case(db)

    def boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(jobs.inference_adapter, "run_inference", boom)
    jobs.run_case_job(case.id)

    fresh = db.get(Case, case.id)
    db.refresh(fresh)
    assert fresh.status == CaseStatus.failed.value
    assert "model exploded" in (fresh.error or "")


def test_enqueue_then_polls_to_done(db):
    case = _case(db)
    jobs.enqueue(db, case)
    assert case.status == CaseStatus.queued.value

    deadline = time.time() + 15
    while time.time() < deadline:
        db.expire_all()
        fresh = db.get(Case, case.id)
        if fresh.status in (CaseStatus.done.value, CaseStatus.failed.value):
            break
        time.sleep(0.1)
    assert fresh.status == CaseStatus.done.value
