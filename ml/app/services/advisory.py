"""Run the LLM/RAG advisory graph for one already-analysed case.

The graph reasons over the per-tooth detections the vision pipeline just wrote, so this
loads `detections.json` from the results directory and hands it to `graph.run` together with
the anamnesa. The detections file **is** the store — the gateway never copies it into its
database, and the web app reads it statically from its own origin.

Failure policy: a missing or unreadable detections file degrades the advisory to
anamnesa-only reasoning rather than failing the case, because by the time this runs the
clinically valuable part (detection + 3D reconstruction) already succeeded.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from ..config import settings
from ..llm import graph, openai_client

log = logging.getLogger(__name__)


def load_detections(dataset_id: str) -> dict | None:
    path = settings.results_dir / dataset_id / "detections.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — advisory input is best-effort
        log.warning("could not read %s: %s", path, exc)
        return None


def _flatten_anamnesa(anamnesa: dict) -> str:
    return "\n".join(str(v) for v in (anamnesa or {}).values() if v)


def run(req) -> tuple[dict[str, str], dict]:
    """→ (`{diagnosis_md, recommendation_md, sanity_md}`, telemetry meta)."""
    detections = load_detections(req.dataset_id)

    # Free-text anamnesa is patient-authored; screen it before it reaches a clinical prompt.
    moderation = openai_client.moderate(_flatten_anamnesa(req.anamnesa))

    case = SimpleNamespace(
        patient_name=req.patient_name,
        anamnesa=req.anamnesa or {},
        detections=detections,
    )
    state = graph.run_state(case)

    meta = {
        "llm_enabled": openai_client.is_enabled(),
        "model": settings.llm_model if openai_client.is_enabled() else None,
        "rag_diagnosis_passages": len(state.get("rag") or []),
        "rag_treatment_passages": len(state.get("rag_treatment") or []),
        "diagnosis_usage": state.get("diagnosis_usage") or {},
        "recommendation_usage": state.get("recommendation_usage") or {},
        "diagnosis_citations": state.get("diagnosis_citation_stats") or {},
        "recommendation_citations": state.get("recommendation_citation_stats") or {},
        "sanity_ok": bool(state.get("sanity_ok")),
        "sanity_feedback": state.get("sanity_feedback") or [],
        "moderation": moderation,
        "errors": {
            key: state[key]
            for key in ("diagnosis_error", "recommendation_error")
            if state.get(key)
        },
    }
    fields = {
        "diagnosis_md": state["diagnosis_md"],
        "recommendation_md": state["recommendation_md"],
        "sanity_md": state["sanity_md"],
    }
    return fields, meta
