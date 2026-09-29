"""Internal ML API — the only surface the Go gateway talks to.

Two long-running operations, deliberately shaped differently:

* **`POST /internal/analyze` streams NDJSON.** The vision pipeline takes tens of seconds to
  minutes on CPU and reports meaningful intermediate stages. Streaming them means the
  gateway persists real progress instead of inventing a spinner, without either side having
  to hold job state for the other. One JSON object per line: `progress` events, then exactly
  one terminal `result` or `error`.
* **`POST /internal/advisory` is a plain request/response.** It is short by comparison and
  has nothing useful to report mid-flight.

The pipeline runs on a **single-slot** executor: RF-DETR on CPU must not be run
concurrently, and the gateway's queue is what smooths burst load.
"""
from __future__ import annotations

import json
import logging
import queue
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from ..schemas.internal import (
    AdvisoryRequest,
    AdvisoryResponse,
    AnalyzeRequest,
    ModerationRequest,
    ModerationResponse,
)
from ..security import require_internal_key
from ..services import advisory, inference_adapter
from ..llm import openai_client

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_key)]
)

# One heavy job at a time: the vision models must not thrash the CPU.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")
_SENTINEL = object()


def _analyze_stream(req: AnalyzeRequest) -> Iterator[str]:
    """Run the pipeline on the worker and yield its progress as NDJSON lines.

    The worker pushes onto a queue that this generator drains, so progress reaches the
    client while the job is still running rather than all at once at the end.
    """
    events: queue.Queue = queue.Queue()

    def on_progress(pct: int, stage: str) -> None:
        events.put({"type": "progress", "pct": int(pct), "stage": stage})

    def work() -> None:
        try:
            dataset_id = inference_adapter.run_inference(req, on_progress=on_progress)
            events.put({"type": "result", "dataset_id": dataset_id})
        except Exception as exc:  # noqa: BLE001 — surface it as a terminal event
            log.exception("analyze failed for case %s", req.case_id)
            events.put({"type": "error", "message": str(exc)})
        finally:
            events.put(_SENTINEL)

    # Submitted, then drained. If the client disconnects mid-stream the job is deliberately
    # left running: a half-written results/ directory is worse than a wasted CPU minute.
    _executor.submit(work)
    while True:
        event = events.get()
        if event is _SENTINEL:
            break
        yield json.dumps(event, ensure_ascii=False) + "\n"


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Run detection + 3D reconstruction for one capture. Streams NDJSON progress."""
    if not req.images:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimal satu gambar diperlukan",
        )
    return StreamingResponse(
        _analyze_stream(req),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/advisory", response_model=AdvisoryResponse)
def run_advisory(req: AdvisoryRequest) -> AdvisoryResponse:
    """Diagnosis + treatment recommendation + consistency check for an analysed case."""
    fields, meta = advisory.run(req)
    return AdvisoryResponse(**fields, meta=meta)


@router.post("/moderate", response_model=ModerationResponse)
def moderate(req: ModerationRequest) -> ModerationResponse:
    """Screen free-text patient input before it is stored or sent to a clinical prompt."""
    return ModerationResponse(**openai_client.moderate(req.text))
