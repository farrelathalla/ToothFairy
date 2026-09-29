"""Hybrid index: BGE-M3 dense + BM25 sparse, fused with RRF, reranked by a cross-encoder.

On-disk layout under `corpus/index/` (committed, so the app runs without a rebuild):

    chunks.json        [{chunk_id, doc_id, title, ref, category, context, text}, ...]
    dense.npy          (N, 1024) float32, L2-normalized, row i ↔ chunks[i]
    meta.json          {embed_model, dim, n_chunks, built_at}
    context_cache.json sha1(chunk) -> Haiku blurb   (see ingest.py)

`retrieve()` is the only thing the agent calls. It degrades rather than raises:

    no index dir      -> []                     (Phase-8 behavior; keeps tests green)
    no BGE-M3 weights -> BM25-only              (still useful, just lower recall)
    no reranker       -> RRF order              (skip the final precision pass)

**Category filtering matters.** The diagnosis agent retrieves over `{diagnosis, context}`
only — treatment guidelines are out of scope for a diagnosis and would push genuinely
relevant symptom/severity passages out of a small top-N.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from ...config import settings
from . import ingest, models

log = logging.getLogger(__name__)

RRF_K = 60  # standard Reciprocal Rank Fusion damping
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
EMBED_CHECKPOINT_EVERY = 16  # chunks — small so a short/interrupted window still banks progress

_lock = threading.Lock()
_loaded: dict | None = None


# ── build ────────────────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _vec_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _embed_cached(texts: list[str]) -> list[list[float]] | None:
    """Embed with a **resumable** on-disk cache keyed by `sha1(indexable_text)`.

    The fp32 encoder needs ~45 min for the full corpus on CPU. Without a checkpoint, any
    interruption — a killed shell, a laptop sleep — re-pays the whole thing. Vectors are
    flushed every `EMBED_CHECKPOINT_EVERY` chunks, so a resumed build only embeds what's new
    (and a chunker tweak only re-embeds the chunks that actually changed). Mirrors the Haiku
    blurb cache in `ingest.py`.
    """
    import numpy as np  # noqa: PLC0415

    path = settings.rag_index_dir / "dense_cache.npz"
    cache: dict[str, list[float]] = {}
    if path.exists():
        blob = np.load(path, allow_pickle=False)
        cache = dict(zip(blob["keys"].tolist(), blob["vecs"].tolist()))
        log.info("resuming: %d vectors already cached", len(cache))

    def _flush() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        keys = list(cache)
        np.savez(
            path,
            keys=np.array(keys, dtype=object).astype("U40"),
            vecs=np.asarray([cache[k] for k in keys], dtype="float32"),
        )

    todo = [t for t in dict.fromkeys(texts) if _vec_key(t) not in cache]
    if todo:
        log.info("embedding %d new chunks (%d cached)", len(todo), len(cache))
    done = 0
    for i in range(0, len(todo), EMBED_CHECKPOINT_EVERY):
        batch = todo[i : i + EMBED_CHECKPOINT_EVERY]
        vecs = models.embed(batch)
        if vecs is None:
            return None
        for text, vec in zip(batch, vecs):
            cache[_vec_key(text)] = vec
        _flush()
        done += len(batch)
        log.info("embedded %d/%d", done, len(todo))
    if todo:
        _flush()

    return [cache[_vec_key(t)] for t in texts]


def build(doc_ids: list[str] | None = None) -> dict:
    """Full rebuild (resumable). Requires BGE-M3 for the dense half; BM25 is always built."""
    import numpy as np  # noqa: PLC0415

    records = ingest.build_chunks(doc_ids)
    if not records:
        raise RuntimeError("no chunks produced — check corpus/pdfs and manifest.json")

    texts = [ingest.indexable(r) for r in records]
    vectors = _embed_cached(texts)
    if vectors is None:
        raise RuntimeError(
            "BGE-M3 unavailable: cannot build the dense index. Install transformers and allow "
            "the BAAI/bge-m3 download, or run retrieval BM25-only by not building."
        )

    out = settings.rag_index_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "chunks.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    arr = np.asarray(vectors, dtype="float32")
    arr /= np.clip(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9, None)
    np.save(out / "dense.npy", arr)

    meta = {
        "embed_model": models.EMBED_MODEL,
        "rerank_model": models.RERANK_MODEL,
        "dim": int(arr.shape[1]),
        "n_chunks": len(records),
        "n_docs": len({r["doc_id"] for r in records}),
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    _invalidate()
    return meta


def _invalidate() -> None:
    global _loaded
    with _lock:
        _loaded = None


# ── load ─────────────────────────────────────────────────────────────────────────

def _index_dir() -> Path:
    return settings.rag_index_dir


def is_available() -> bool:
    return (_index_dir() / "chunks.json").exists()


def _load() -> dict | None:
    """Lazy, cached, thread-safe. Returns None when there is no index on disk."""
    global _loaded
    if _loaded is not None:
        return _loaded
    with _lock:
        if _loaded is not None:
            return _loaded
        chunks_path = _index_dir() / "chunks.json"
        if not chunks_path.exists():
            return None

        records = json.loads(chunks_path.read_text(encoding="utf-8"))
        dense = None
        dense_path = _index_dir() / "dense.npy"
        if dense_path.exists():
            import numpy as np  # noqa: PLC0415

            dense = np.load(dense_path)
            if dense.shape[0] != len(records):
                log.warning("dense.npy/chunks.json length mismatch — ignoring dense index")
                dense = None

        corpus_tokens = [tokenize(ingest.indexable(r)) for r in records]
        from rank_bm25 import BM25Okapi  # noqa: PLC0415

        _loaded = {"records": records, "dense": dense, "bm25": BM25Okapi(corpus_tokens)}
    return _loaded


# ── search ───────────────────────────────────────────────────────────────────────

def _rrf(*rankings: Sequence[int]) -> dict[int, float]:
    """Fuse ranked id lists: score(i) = Σ 1/(RRF_K + rank_of_i_in_list)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
    return fused


def _dense_ranking(query: str, rows: list[int], dense, limit: int) -> list[int]:
    import numpy as np  # noqa: PLC0415

    qv = models.embed([query])
    if qv is None:
        return []
    q = np.asarray(qv[0], dtype="float32")
    q /= max(float(np.linalg.norm(q)), 1e-9)
    sims = dense[rows] @ q
    order = np.argsort(-sims)[:limit]
    return [rows[i] for i in order]


def _bm25_ranking(query: str, rows: list[int], bm25, limit: int) -> list[int]:
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(rows, key=lambda i: -scores[i])
    return [i for i in ranked[:limit] if scores[i] > 0]


def retrieve(
    query: str,
    k: int | None = None,
    categories: Iterable[str] | None = None,
    *,
    candidates: int | None = None,
    rerank: bool = True,
) -> list[dict]:
    """Top-`k` passages for `query`, restricted to `categories`.

    Returns `[{doc_id, chunk_id, title, ref, category, context, text, score}]`, most
    relevant first. Empty list when there is no index (the disabled/offline path).
    """
    idx = _load()
    if idx is None or not query.strip():
        return []

    k = k or settings.rag_top_n
    candidates = candidates or settings.rag_candidates
    records = idx["records"]

    allowed = set(categories) if categories else None
    rows = [i for i, r in enumerate(records) if allowed is None or r["category"] in allowed]
    if not rows:
        return []

    rankings: list[list[int]] = []
    if idx["dense"] is not None:
        dense_rank = _dense_ranking(query, rows, idx["dense"], candidates)
        if dense_rank:
            rankings.append(dense_rank)
    rankings.append(_bm25_ranking(query, rows, idx["bm25"], candidates))

    fused = _rrf(*[r for r in rankings if r])
    if not fused:
        return []
    shortlist = sorted(fused, key=lambda i: -fused[i])[:candidates]

    scores: list[float] | None = None
    if rerank:
        scores = models.rerank(query, [ingest.indexable(records[i]) for i in shortlist])

    if scores is not None:
        ranked = sorted(zip(shortlist, scores), key=lambda p: -p[1])[:k]
    else:
        # RRF scores are tiny (~0.03); expose them on a comparable 0..1-ish scale.
        best = max(fused.values())
        ranked = [(i, fused[i] / best) for i in shortlist[:k]]

    out = []
    for i, score in ranked:
        rec = dict(records[i])
        rec["score"] = round(float(score), 4)
        out.append(rec)
    return out


def stats() -> dict:
    meta_path = _index_dir() / "meta.json"
    if not meta_path.exists():
        return {"available": False}
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["available"] = True
    return meta


def token_estimate(passages: list[dict]) -> int:
    """Rough prompt cost of a passage set (for the eval report)."""
    return math.ceil(sum(len(p["text"]) + len(p.get("context", "")) for p in passages) / 4)
