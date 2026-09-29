"""Non-mock integration smoke: run the REAL vision pipeline through the adapter on the
shipped sample images. Marked `slow` and skipped by default (RF-DETR on CPU takes minutes);
its job is to catch import/signature drift between the service adapter and `inference/`.

    cd ml && python -m pytest -m slow tests/test_inference_real_slow.py
"""
import json
import shutil

import pytest

from app.config import REPO_ROOT, settings
from app.schemas.internal import AnalyzeRequest


@pytest.mark.slow
def test_real_pipeline_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "mock_inference", False)

    samples = REPO_ROOT / "assets" / "samples"
    up, pano = samples / "intraoral.jpg", samples / "panoramic.png"
    if not up.exists() or not pano.exists():
        pytest.skip("sample images not present")

    from app.services import inference_adapter

    req = AnalyzeRequest(
        case_id="case-slow-smoke", images={"up": str(up), "panoramic": str(pano)}
    )

    # Exercises the real adapter -> inference/run_all wiring (Ctx build + process()). It
    # catches import/signature drift against inference/. The heavy models load here, so where
    # the weights are present detections.json is produced; where they are not, run_all's
    # per-step `_safe` swallows the failure but the pipeline call must still complete cleanly.
    dataset_id = inference_adapter.run_inference(req)
    assert dataset_id == req.case_id

    result_dir = settings.results_dir / dataset_id
    assert result_dir.exists()          # Ctx created the public results dir

    detections = result_dir / "detections.json"
    if detections.exists():
        assert "teeth" in json.loads(detections.read_text(encoding="utf-8"))
    shutil.rmtree(result_dir, ignore_errors=True)
