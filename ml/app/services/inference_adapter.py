"""Bridge between a persisted Case and the in-process `inference/` pipeline.

`build_ctx(case)` turns the case's uploaded CaseImage rows into an inference `Ctx`.
`run_inference(case, on_progress)` runs the pipeline and returns the `dataset_id`
(the results/<id>/ dir the frontend reads). With `MOCK_INFERENCE=1` it skips the heavy
models and copies a precomputed demo dataset instead, stepping progress so the UI is
exercisable in seconds (dev/E2E). Progress is reported via `on_progress(pct, stage)`.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from ..config import ML_DIR, settings
from ..models.case_image import ViewKey

# Make the inference package importable in-process (it ships inside this service).
_INFER_DIR = ML_DIR / "inference"
if str(_INFER_DIR) not in sys.path:
    sys.path.insert(0, str(_INFER_DIR))

ProgressCb = Callable[[int, str], None]

# Coarse stages for the MOCK path (real inference reports its own coarse stages).
_MOCK_STAGES = [
    (10, "Menyiapkan gambar"),
    (30, "Deteksi FDI & segmentasi gigi"),
    (55, "Grading karies (RF-DETR ICDAS)"),
    (78, "Analisis panoramik (karies tersembunyi)"),
    (92, "Menyusun rekonstruksi 3D"),
]


def _noop(pct: int, stage: str) -> None:  # pragma: no cover - default callback
    pass


def build_ctx(case):
    """Build an inference `Ctx` from the case's uploaded image rows."""
    from pipeline import OUT_ROOT, Ctx  # imported lazily (heavy sys.path juggling above)

    angles: dict[str, str] = {}
    panoramic: str | None = None
    for img in case.images:
        abs_path = str((settings.upload_dir / img.path).resolve())
        if img.view_key == ViewKey.panoramic.value:
            panoramic = abs_path
        else:
            angles[img.view_key] = abs_path

    return Ctx(
        name=case.id,
        angles=angles,
        panoramic=panoramic,
        out=OUT_ROOT / case.id,
        pub=settings.results_dir / case.id,
        do_xai=True,
    )


def _demo_sources() -> list[str]:
    """Precomputed demo datasets available as a MOCK copy source."""
    root = settings.demo_results_dir
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and (p / "detections.json").exists()
    )


def _pick_mock_source(case) -> str:
    sources = _demo_sources()
    if not sources:
        raise RuntimeError(f"no precomputed demo datasets in {settings.demo_results_dir}")
    # deterministic per case, but varied across cases
    idx = int(hashlib.sha1(case.id.encode()).hexdigest(), 16) % len(sources)
    return sources[idx]


def _run_mock(case, on_progress: ProgressCb) -> str:
    delay = max(0.0, settings.mock_step_delay)
    for pct, stage in _MOCK_STAGES:
        on_progress(pct, stage)
        if delay:
            time.sleep(delay)

    src = settings.demo_results_dir / _pick_mock_source(case)
    dataset_id = case.id
    dst = settings.results_dir / dataset_id
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)

    on_progress(100, "Selesai")
    return dataset_id


def _run_real(case, on_progress: ProgressCb) -> str:
    import run_all  # heavy: torch/ultralytics/rfdetr

    on_progress(10, "Menyiapkan gambar")
    ctx = build_ctx(case)
    on_progress(20, "Menjalankan model deteksi")
    run_all.process(ctx)
    on_progress(95, "Menyusun rekonstruksi 3D")
    on_progress(100, "Selesai")
    return case.id


def run_inference(case, on_progress: ProgressCb | None = None) -> str:
    """Run the pipeline for a case; return its dataset_id. Mock unless real models requested."""
    cb = on_progress or _noop
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    if settings.mock_inference:
        return _run_mock(case, cb)
    return _run_real(case, cb)
