"""Async inference job orchestration.

A single-worker `ThreadPoolExecutor` runs one inference job at a time (RF-DETR on CPU
must not be run concurrently). `enqueue(db, case)` flips the case to `queued` and submits
`run_case_job` to the worker; `run_case_job` opens its OWN DB session (it runs off-request
in a background thread), drives the case queued→running→done, persists progress at each
stage, runs the LLM stub, and on any exception records `failed` + the error message.

`run_case_job` is also callable synchronously (tests) — it does not depend on the executor.
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from ..config import settings
from ..db import SessionLocal
from ..llm import graph
from ..models.case import Case, CaseStatus
from . import inference_adapter

log = logging.getLogger(__name__)

# One job at a time: heavy models must not thrash the CPU.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")


def load_detections(dataset_id: str) -> dict | None:
    """Read the detections the inference run just wrote, for the advisory graph.

    `Case` has no detections column — the file *is* the store, and the frontend loads it
    statically from its own origin. We attach it as a transient attribute so `graph.run(case)`
    keeps its Phase-8 signature.
    """
    path = settings.results_dir / dataset_id / "detections.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — advisory input is best-effort
        log.warning("could not read %s: %s", path, exc)
        return None


def run_case_job(case_id: str) -> None:
    """Synchronously run inference + LLM stub for one case, persisting all state.

    Opens its own session so it is safe to call from a background thread.
    """
    db = SessionLocal()
    try:
        case = db.get(Case, case_id)
        if case is None:
            return
        case.status = CaseStatus.running.value
        case.progress = 0
        case.stage = "Memulai analisis"
        case.error = None
        db.commit()

        def on_progress(pct: int, stage: str) -> None:
            case.progress = pct
            case.stage = stage
            db.commit()

        dataset_id = inference_adapter.run_inference(case, on_progress=on_progress)

        # LLM advisory — the diagnosis agent needs the per-tooth ICDAS grades, so hand it
        # the detections the run just produced (transient attribute, see load_detections).
        case.detections = load_detections(dataset_id)
        case.stage = "Menyusun diagnosis"
        db.commit()

        llm = graph.run(case)
        case.diagnosis_md = llm["diagnosis_md"]
        case.recommendation_md = llm["recommendation_md"]
        case.sanity_md = llm["sanity_md"]

        case.dataset_id = dataset_id
        case.status = CaseStatus.done.value
        case.progress = 100
        case.stage = "Selesai"
        db.commit()
    except Exception as exc:  # noqa: BLE001 - record any failure for the poller
        db.rollback()
        case = db.get(Case, case_id)
        if case is not None:
            case.status = CaseStatus.failed.value
            case.error = str(exc)
            case.stage = "Gagal"
            db.commit()
    finally:
        db.close()


def enqueue(db, case: Case):
    """Mark the case queued and schedule the background job. Returns the submitted future."""
    case.status = CaseStatus.queued.value
    case.progress = 0
    case.stage = "Menunggu antrean"
    case.error = None
    case.dataset_id = None
    db.commit()
    return _executor.submit(run_case_job, case.id)
