"""inference_adapter: turns an AnalyzeRequest into a pipeline `Ctx` and (in MOCK mode)
copies a precomputed demo dataset into results/<case_id>/, reporting monotonic progress."""
from pathlib import Path

from app.config import settings
from app.schemas.internal import AnalyzeRequest
from app.services import inference_adapter


def _req(case_id="case-adapter", views=("up", "panoramic"), tmp_path=None):
    images = {}
    for view in views:
        path = tmp_path / f"{view}.jpg"
        path.write_bytes(b"\xff\xd8fakejpeg")
        images[view] = str(path)
    return AnalyzeRequest(case_id=case_id, images=images)


def test_build_ctx_splits_panoramic_from_intraoral_views(tmp_path):
    ctx = inference_adapter.build_ctx(
        _req(views=("up", "front", "panoramic"), tmp_path=tmp_path)
    )
    assert set(ctx.angles) == {"up", "front"}
    assert ctx.panoramic is not None and Path(ctx.panoramic).exists()
    assert ctx.name == "case-adapter"
    for path in ctx.angles.values():
        assert Path(path).is_absolute() and Path(path).exists()


def test_build_ctx_accepts_an_intraoral_only_capture(tmp_path):
    ctx = inference_adapter.build_ctx(_req(views=("up",), tmp_path=tmp_path))
    assert ctx.panoramic is None and set(ctx.angles) == {"up"}


def test_mock_run_copies_a_dataset_and_reports_progress(tmp_path):
    seen: list[tuple[int, str]] = []
    dataset_id = inference_adapter.run_inference(
        _req(tmp_path=tmp_path), on_progress=lambda p, s: seen.append((p, s))
    )

    assert (settings.results_dir / dataset_id / "detections.json").exists()

    pcts = [p for p, _ in seen]
    assert pcts == sorted(pcts) and pcts[-1] == 100
    assert all(isinstance(stage, str) and stage for _, stage in seen)


def test_mock_source_is_deterministic_per_case(tmp_path):
    first = inference_adapter._pick_mock_source("case-abc")
    assert first == inference_adapter._pick_mock_source("case-abc")
    assert first in inference_adapter._demo_sources()


def test_rerunning_a_case_replaces_its_previous_results(tmp_path):
    req = _req(case_id="case-rerun", tmp_path=tmp_path)
    inference_adapter.run_inference(req)
    stray = settings.results_dir / "case-rerun" / "stale.txt"
    stray.write_text("old", encoding="utf-8")

    inference_adapter.run_inference(req)
    assert not stray.exists()
    assert (settings.results_dir / "case-rerun" / "detections.json").exists()
