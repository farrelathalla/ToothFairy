"""Lazy singletons for BGE-M3 (dense bi-encoder) and bge-reranker-v2-m3 (cross-encoder).

**Nothing here is imported at module import time.** torch + the two checkpoints are ~4.5 GB;
the backend's unit tests must never pay that. Every entry point loads on first use and caches
the instance. Load failures (no weights, no network) are swallowed and surfaced as `None`, so
retrieval degrades to BM25-only / no-rerank rather than taking a request down.

**Why plain `transformers` and not `FlagEmbedding`:** FlagEmbedding 1.4.0's reranker calls
`tokenizer.prepare_for_model()`, which `transformers>=5` removed — `compute_score()` dies with
`AttributeError: XLMRobertaTokenizer has no attribute prepare_for_model`. Pinning transformers
down is not an option: `inference/` shares this environment with ultralytics + rfdetr. Both
models are ordinary XLM-RoBERTa checkpoints, so we run them directly:

* **dense** — BGE-M3's `dense_vecs` *is* the L2-normalized CLS token of the last hidden state.
* **rerank** — the cross-encoder emits one logit per (query, passage) pair; `sigmoid` maps it
  to a 0..1 relevance score (verified: a matching passage scores 0.43, a mismatched one 3e-4).

**CPU performance (8-core laptop, no GPU) — measured, warmed, median of 3:**

    encoder  fp32 @384: 2079 ms/chunk      reranker  fp32 @384: 2393 ms/passage
    encoder  int8 @384:  847 ms/chunk      reranker  int8 @384: 1139 ms/passage

So the **encoder stays fp32** and the **reranker is dynamically quantized to int8**. The split is
deliberate: int8 shifts BGE-M3's dense vectors enough to matter (cosine 0.94-0.96 vs fp32 — a
different embedding function, and the index would have to be rebuilt to match), while the
reranker only has to *order* 16 candidates, where int8 preserves the ranking and buys 2×. The
encoder runs once per query (~2 s); the reranker runs 16× (~18 s), so that's where the 2× lands.
Indexing is fp32 and one-time (~45 min for ~1300 chunks) — it defines the vectors, so it gets the
accurate model.
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

# A chunk is ~280 tok + a ~60 tok context blurb, so 384 covers it without truncation.
EMBED_MAX_LEN = 384
RERANK_MAX_LEN = 384
EMBED_BATCH = 8
RERANK_BATCH = 8
# Dynamic int8 on the reranker only — see the module docstring for why not the encoder.
RERANK_QUANTIZE = True

_lock = threading.Lock()
_embedder = None   # (tokenizer, model)
_reranker = None   # (tokenizer, model)
_embedder_failed = False
_reranker_failed = False


def _device() -> str:
    import torch  # noqa: PLC0415

    # torch defaults to half the cores on Windows; on a CPU-only box that halves throughput.
    if torch.get_num_threads() < (os.cpu_count() or 1):
        torch.set_num_threads(os.cpu_count() or 1)
    return "cuda" if torch.cuda.is_available() else "cpu"


def get_embedder():
    """`(tokenizer, model)` for BGE-M3, or None if the weights can't be loaded."""
    global _embedder, _embedder_failed
    if _embedder is not None or _embedder_failed:
        return _embedder
    with _lock:
        if _embedder is None and not _embedder_failed:
            try:
                from transformers import AutoModel, AutoTokenizer  # noqa: PLC0415

                tok = AutoTokenizer.from_pretrained(EMBED_MODEL)
                mdl = AutoModel.from_pretrained(EMBED_MODEL).to(_device()).eval()
                _embedder = (tok, mdl)
            except Exception as exc:  # noqa: BLE001
                _embedder_failed = True
                log.warning("BGE-M3 unavailable, falling back to BM25-only: %s", exc)
    return _embedder


def get_reranker():
    """`(tokenizer, model)` for bge-reranker-v2-m3, or None if unavailable."""
    global _reranker, _reranker_failed
    if _reranker is not None or _reranker_failed:
        return _reranker
    with _lock:
        if _reranker is None and not _reranker_failed:
            try:
                from transformers import (  # noqa: PLC0415
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                tok = AutoTokenizer.from_pretrained(RERANK_MODEL)
                mdl = (
                    AutoModelForSequenceClassification.from_pretrained(RERANK_MODEL)
                    .to(_device())
                    .eval()
                )
                if RERANK_QUANTIZE and _device() == "cpu":
                    import torch  # noqa: PLC0415
                    from torch import nn  # noqa: PLC0415

                    mdl = torch.ao.quantization.quantize_dynamic(
                        mdl, {nn.Linear}, dtype=torch.qint8
                    )
                _reranker = (tok, mdl)
            except Exception as exc:  # noqa: BLE001
                _reranker_failed = True
                log.warning("bge-reranker-v2-m3 unavailable, skipping rerank: %s", exc)
    return _reranker


def embed(texts: list[str]) -> list[list[float]] | None:
    """L2-normalized dense vectors (CLS pooling), or None when the embedder is unavailable."""
    pair = get_embedder()
    if pair is None or not texts:
        return None
    import torch  # noqa: PLC0415

    tok, mdl = pair
    device = _device()
    out: list[list[float]] = []
    with torch.inference_mode():
        for i in range(0, len(texts), EMBED_BATCH):
            batch = tok(
                texts[i : i + EMBED_BATCH],
                padding=True, truncation=True, max_length=EMBED_MAX_LEN, return_tensors="pt",
            ).to(device)
            cls = mdl(**batch).last_hidden_state[:, 0]
            vecs = torch.nn.functional.normalize(cls, dim=-1)
            out.extend(vecs.cpu().float().tolist())
    return out


def rerank(query: str, passages: list[str]) -> list[float] | None:
    """Cross-encoder relevance in 0..1 (higher is better), or None if unavailable."""
    pair = get_reranker()
    if pair is None or not passages:
        return None
    import torch  # noqa: PLC0415

    tok, mdl = pair
    device = _device()
    scores: list[float] = []
    with torch.inference_mode():
        for i in range(0, len(passages), RERANK_BATCH):
            chunk = passages[i : i + RERANK_BATCH]
            batch = tok(
                [[query, p] for p in chunk],
                padding=True, truncation=True, max_length=RERANK_MAX_LEN, return_tensors="pt",
            ).to(device)
            logits = mdl(**batch).logits.view(-1).float()
            scores.extend(torch.sigmoid(logits).cpu().tolist())
    return scores
