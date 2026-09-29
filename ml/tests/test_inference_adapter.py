"""inference_adapter: builds a Ctx from a case's CaseImage rows and (in MOCK mode) copies
a precomputed demo dataset into results/<case.id>/, reporting monotonic progress to 100."""
from app.config import settings
from app.services import accounts, cases, inference_adapter

ANAMNESA = {
    "lokasi": "Geraham kiri bawah", "quality": "Cenut-cenut", "severity": "Skala 6",
    "chronology": "3 hari", "setting": "Saat mengunyah",
    "aggravating_alleviating": "Manis", "associated": "Bengkak",
    "pernah_ke_drg_lain": "Belum", "obat_digunakan": "Paracetamol",
    "tindakan_sebelumnya": "Belum", "penyakit_sistemik": "Tidak ada",
    "pernah_menunda": "Ya", "alasan_kuat": "Sulit tidur",
}


def _case_with_images(db, views=("up", "panoramic")):
    doc = accounts.create_user(db, email="d@x.io", name="D", password="secret1")
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)
    for v in views:
        cases.save_image(db, case, v, filename=f"{v}.jpg", content_type="image/jpeg",
                         data=b"\xff\xd8fakejpeg")
    return case


def test_build_ctx_from_rows(db):
    case = _case_with_images(db, ("up", "front", "panoramic"))
    ctx = inference_adapter.build_ctx(case)
    assert set(ctx.angles) == {"up", "front"}
    assert ctx.panoramic is not None
    assert ctx.name == case.id
    # angle paths point at the uploaded files for this case
    from pathlib import Path
    for p in ctx.angles.values():
        assert Path(p).parent.name == case.id
        assert Path(p).exists()


def test_mock_run_copies_dataset_and_reports_progress(db):
    case = _case_with_images(db)
    seen = []
    dataset_id = inference_adapter.run_inference(case, on_progress=lambda p, s: seen.append((p, s)))

    # results dir written with a detections.json
    result_dir = settings.results_dir / dataset_id
    assert (result_dir / "detections.json").exists()

    # progress is monotonic non-decreasing and ends at 100
    pcts = [p for p, _ in seen]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100
    assert all(isinstance(s, str) and s for _, s in seen)
