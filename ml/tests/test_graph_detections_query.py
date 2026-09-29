"""The RAG query builder + the graph's detections plumbing.

The query is what decides whether the diagnosis agent sees the PUFA paper or the SDF
guideline. Anamnesa alone never names ICDAS/PUFA/"untreated caries", so the builder has to
compose the clinical vocabulary from the detections.
"""
import json

from app.llm.graph import build_rag_query, run_graph
from app.services import jobs

ANAMNESA = {
    "lokasi": "Geraham kiri bawah",
    "quality": "Cenut-cenut",
    "associated": "Gusi bengkak",
    "alasan_kuat": "Sulit tidur",  # administrative — deliberately not in the query
}


def _det(teeth):
    return {"teeth": {str(t["fdi"]): t for t in teeth}}


def test_query_names_the_detected_grades_and_tooth_count():
    q = build_rag_query({"detections": _det([
        {"fdi": 11, "severity": 6}, {"fdi": 16, "severity": 3},
    ])})
    assert "D6" in q and "D3" in q
    assert "2 gigi terdampak" in q


def test_deep_lesions_pull_in_pufa_and_abscess_vocabulary():
    q = build_rag_query({"detections": _det([{"fdi": 11, "severity": 5}])})
    assert "PUFA" in q and "abses periapikal" in q

    shallow = build_rag_query({"detections": _det([{"fdi": 11, "severity": 2}])})
    assert "PUFA" not in shallow


def test_hidden_lesion_adds_panoramic_terms():
    q = build_rag_query({"detections": _det([{"fdi": 46, "severity": 3, "hidden": True}])})
    assert "panoramik" in q


def test_deciduous_dentition_is_detected_from_fdi_range():
    deciduous = build_rag_query({"detections": _det([{"fdi": 74, "severity": 4}])})
    assert "desidui" in deciduous
    permanent = build_rag_query({"detections": _det([{"fdi": 36, "severity": 4}])})
    assert "desidui" not in permanent and "permanen" in permanent


def test_query_includes_symptom_anamnesa_but_not_administrative_fields():
    q = build_rag_query({"anamnesa": ANAMNESA, "detections": None})
    assert "Cenut-cenut" in q and "Gusi bengkak" in q
    assert "Sulit tidur" not in q


def test_query_handles_no_detections_and_is_bounded():
    q = build_rag_query({"anamnesa": {"lokasi": "x" * 5000}})
    assert "tidak ada lesi terdeteksi" in q
    assert len(q) <= 1200


def test_graph_stores_the_query_and_calls_rag_with_diagnosis_categories(monkeypatch):
    seen: dict = {}

    def _fake_retrieve(query, k=None, categories=None):
        seen.update(query=query, k=k, categories=categories)
        return []

    monkeypatch.setattr("app.llm.graph.rag.retrieve", _fake_retrieve)
    state = run_graph({"anamnesa": ANAMNESA, "detections": _det([{"fdi": 11, "severity": 6}])})

    assert seen["categories"] == ("diagnosis", "context")
    assert "D6" in seen["query"]
    assert state["rag_query"] == seen["query"]
    assert state["rag"] == []


# ── jobs → detections handoff ────────────────────────────────────────────────────

def test_load_detections_reads_the_dataset_written_by_inference(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "results_dir", tmp_path)
    (tmp_path / "case-1").mkdir()
    payload = {"teeth": {"11": {"fdi": 11, "severity": 6}}}
    (tmp_path / "case-1" / "detections.json").write_text(json.dumps(payload), encoding="utf-8")

    assert jobs.load_detections("case-1") == payload


def test_load_detections_returns_none_when_absent(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "results_dir", tmp_path)
    assert jobs.load_detections("nope") is None  # warned, not raised
