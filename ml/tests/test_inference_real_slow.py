"""Non-mock integration smoke: run the REAL inference pipeline through the adapter on the
shipped test_pic images. Marked `slow` and skipped by default (RF-DETR on CPU ~minutes);
its job is to catch import/signature drift between the backend adapter and inference/.

    cd backend && python -m pytest -m slow tests/test_inference_real_slow.py
"""
import os
import shutil

import pytest

from app.config import REPO_ROOT, settings
from app.services import accounts, cases

ANAMNESA = {
    "lokasi": "Geraham", "quality": "Nyeri", "severity": "6", "chronology": "3 hari",
    "setting": "Mengunyah", "aggravating_alleviating": "Manis", "associated": "-",
    "pernah_ke_drg_lain": "Belum", "obat_digunakan": "-", "tindakan_sebelumnya": "-",
    "penyakit_sistemik": "-", "pernah_menunda": "Ya", "alasan_kuat": "Sakit",
}


@pytest.mark.slow
def test_real_pipeline_end_to_end(db, monkeypatch):
    monkeypatch.setattr(settings, "mock_inference", False)
    doc = accounts.create_user(db, email="d@x.io", name="D", password="secret1")
    case = cases.create_case(db, doc, patient_name="P", anamnesa=ANAMNESA)

    tp = REPO_ROOT / "assets" / "samples"
    up = tp / "intraoral.jpg"
    pano = tp / "panoramic.png"
    if not up.exists() or not pano.exists():
        pytest.skip("test_pic images not present")

    cases.save_image(db, case, "up", filename="intraoral.jpg", content_type="image/jpeg",
                     data=up.read_bytes())
    cases.save_image(db, case, "panoramic", filename="panoramic.png", content_type="image/png",
                     data=pano.read_bytes())

    from app.services import inference_adapter

    # This exercises the real adapter → inference/run_all wiring (Ctx build + process()).
    # It catches import/signature drift against inference/. The heavy models are loaded here,
    # so on an environment where the model weights load (apostrophe-free path, weights present,
    # rfdetr installed) detections.json is produced; where they don't, run_all's per-step
    # `_safe` swallows the failure but the pipeline call itself must still complete cleanly.
    dataset_id = inference_adapter.run_inference(case)
    assert dataset_id == case.id
    result_dir = settings.results_dir / dataset_id
    assert result_dir.exists()  # Ctx created the public results dir

    det = result_dir / "detections.json"
    if det.exists():
        import json
        data = json.loads(det.read_text())
        assert "teeth" in data
    shutil.rmtree(result_dir, ignore_errors=True)
