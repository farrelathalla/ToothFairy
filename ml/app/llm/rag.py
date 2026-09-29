"""RAG entry point for the graph.

Delegates to `retrieval.index.retrieve()` **only** when `RAG_ENABLED=1` *and* an index
exists on disk. Otherwise returns `[]` — the Phase-8 contract, which is what keeps
`test_llm_graph`'s `state["rag"] == []` green and lets the demo run fully offline.

The heavy modules (torch, FlagEmbedding, numpy, rank_bm25) are imported inside the
function, so importing `app.llm.rag` costs nothing.
"""
from __future__ import annotations

import logging

from ..config import settings

log = logging.getLogger(__name__)

# The diagnosis agent grounds itself in symptom/severity/epidemiology evidence.
# `treatment` is deliberately excluded — that corpus belongs to the recommendation agent,
# and in a small top-N it would crowd out the passages a diagnosis actually needs.
DIAGNOSIS_CATEGORIES = ("diagnosis", "context")

# The recommendation agent reads the treatment guidelines, plus the same Indonesian context
# (access to care, parental factors) that shapes what is realistic to prescribe.
TREATMENT_CATEGORIES = ("treatment", "context")


def is_enabled() -> bool:
    if not settings.rag_enabled:
        return False
    from .retrieval import index  # noqa: PLC0415

    return index.is_available()


def retrieve(query: str, k: int | None = None, categories=None) -> list[dict]:
    """Top-k supporting passages, or `[]` when RAG is disabled / unbuilt / broken."""
    if not settings.rag_enabled:
        return []
    try:
        from .retrieval import index  # noqa: PLC0415

        if not index.is_available():
            log.warning(
                "RAG_ENABLED=1 but no index at %s - run: python -m app.llm.retrieval.build",
                settings.rag_index_dir,
            )
            return []
        return index.retrieve(query, k=k or settings.rag_top_n, categories=categories)
    except Exception as exc:  # noqa: BLE001 — retrieval must never take a case down
        log.exception("retrieval failed, continuing without passages: %s", exc)
        return []
