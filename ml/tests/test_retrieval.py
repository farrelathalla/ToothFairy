"""Retrieval pipeline against a tiny fixture index.

No model weights, no network: the fixture index ships `chunks.json` but no `dense.npy`, so
`retrieve()` exercises the BM25 half + RRF + the category filter, and the reranker is stubbed
out. The dense half is a pure add-on ranking — the fusion and filtering logic under test is
the part that decides what the diagnosis agent actually sees.
"""
import json

import pytest

from app.config import settings
from app.llm import rag
from app.llm.retrieval import chunker, index, models

FIXTURE_CHUNKS = [
    {
        "chunk_id": "1#0", "doc_id": "1", "category": "diagnosis",
        "title": "Impact of untreated dental caries on daily activities",
        "ref": "DOI: 10.1111/jphd.12259", "context": "Bagian hasil studi kohort anak.",
        "text": "Children with untreated dental caries reported difficulty eating and "
                "chewing, and disturbed sleep, far more often than caries-free children.",
    },
    {
        "chunk_id": "2#0", "doc_id": "2", "category": "diagnosis",
        "title": "PUFA index and oral health related quality of life",
        "ref": "URL: jimc.ir", "context": "Definisi skoring PUFA.",
        "text": "The PUFA index scores pulpal involvement, ulceration, fistula and abscess "
                "as visible consequences of untreated caries.",
    },
    {
        "chunk_id": "20#0", "doc_id": "20", "category": "context",
        "title": "Prevalence of dental caries among children in Indonesia",
        "ref": "meta-analysis", "context": "Ringkasan prevalensi.",
        "text": "Pooled caries prevalence among Indonesian children remains high across "
                "provinces, with strong socioeconomic gradients.",
    },
    {
        "chunk_id": "15#0", "doc_id": "15", "category": "treatment",
        "title": "AAPD guideline on silver diamine fluoride",
        "ref": "AAPD", "context": "Rekomendasi SDF.",
        "text": "Silver diamine fluoride arrests caries lesions and is recommended for "
                "management of cavitated lesions in primary teeth.",
    },
]


@pytest.fixture
def fixture_index(tmp_path, monkeypatch):
    """A BM25-only index on disk, with the cross-encoder disabled."""
    idx_dir = tmp_path / "index"
    idx_dir.mkdir()
    (idx_dir / "chunks.json").write_text(json.dumps(FIXTURE_CHUNKS), encoding="utf-8")

    monkeypatch.setattr(index, "_index_dir", lambda: idx_dir)
    monkeypatch.setattr(models, "rerank", lambda q, p: None)   # no cross-encoder weights
    monkeypatch.setattr(models, "embed", lambda t: None)       # no BGE-M3 weights
    index._invalidate()
    yield idx_dir
    index._invalidate()


def test_retrieve_finds_the_seeded_chunk(fixture_index):
    hits = index.retrieve("apa itu indeks PUFA abscess fistula", k=2)
    assert hits, "hybrid search returned nothing"
    assert hits[0]["doc_id"] == "2"
    assert hits[0]["score"] > 0


def test_retrieve_ranks_daily_activities_query_to_doc_1(fixture_index):
    hits = index.retrieve("difficulty eating chewing disturbed sleep children", k=1)
    assert hits[0]["doc_id"] == "1"


def test_category_filter_excludes_treatment(fixture_index):
    """The diagnosis agent must never see the SDF guideline, even on a lexical match."""
    query = "silver diamine fluoride arrests caries lesions primary teeth"
    unfiltered = index.retrieve(query, k=4)
    assert any(h["doc_id"] == "15" for h in unfiltered)

    filtered = index.retrieve(query, k=4, categories=("diagnosis", "context"))
    assert all(h["category"] in {"diagnosis", "context"} for h in filtered)
    assert not any(h["doc_id"] == "15" for h in filtered)


def test_retrieve_returns_empty_for_blank_query(fixture_index):
    assert index.retrieve("   ", k=3) == []


def test_is_available_reflects_the_index_on_disk(fixture_index, monkeypatch, tmp_path):
    assert index.is_available()
    monkeypatch.setattr(index, "_index_dir", lambda: tmp_path / "nope")
    assert not index.is_available()


def test_rag_retrieve_returns_empty_when_disabled(fixture_index, monkeypatch):
    """The Phase-8 contract: RAG off ⇒ no passages, no imports, no network."""
    monkeypatch.setattr(settings, "rag_enabled", False)
    assert rag.retrieve("indeks PUFA") == []
    assert rag.is_enabled() is False


def test_rag_retrieve_delegates_when_enabled(fixture_index, monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", True)
    hits = rag.retrieve("indeks PUFA abscess", k=2, categories=rag.DIAGNOSIS_CATEGORIES)
    assert [h["doc_id"] for h in hits][0] == "2"


def test_rag_retrieve_survives_a_broken_index(monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", True)
    monkeypatch.setattr(index, "is_available", lambda: True)
    monkeypatch.setattr(index, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert rag.retrieve("apa saja") == []  # logged, not raised


# ── chunker ──────────────────────────────────────────────────────────────────────

def test_chunker_packs_paragraphs_and_overlaps():
    para = "Kalimat panjang tentang karies gigi anak. " * 40
    chunks = chunker.chunk_text("\n\n".join([para, para, para]), target_tokens=200)
    assert len(chunks) > 1
    assert all(len(c) <= 200 * chunker.CHARS_PER_TOKEN for c in chunks)


def test_chunker_dehyphenates_and_unwraps_lines():
    assert "caries" in chunker.normalize("cari-\nes lesions")
    assert chunker.normalize("line one\nline two") == "line one line two"


def test_chunker_drops_scraps():
    assert chunker.chunk_text("too short") == []
