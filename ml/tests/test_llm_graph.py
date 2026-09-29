"""The advisory graph end-to-end, on the offline (stub) path.

Two retrievals, two clinical nodes, one deterministic guard, and a loop-back edge that fires
at most once. The query builders are what decide *which* passages each agent sees, so they
are pinned here too.
"""
from app.llm import agents, graph
from app.llm.graph import build_rag_query, build_treatment_query, run_graph

ANAMNESA = {
    "lokasi": "Geraham kiri bawah",
    "quality": "Cenut-cenut",
    "associated": "Gusi bengkak",
    "alasan_kuat": "Sulit tidur",   # administrative — deliberately not in the query
}


def _det(teeth):
    return {"teeth": {str(t["fdi"]): t for t in teeth}}


# ── diagnosis query ──────────────────────────────────────────────────────────────

def test_query_names_the_detected_grades_and_tooth_count():
    q = build_rag_query({"detections": _det([
        {"fdi": 11, "severity": 6}, {"fdi": 16, "severity": 3},
    ])})
    assert "D6" in q and "D3" in q and "2 gigi terdampak" in q


def test_deep_lesions_pull_in_pufa_and_abscess_vocabulary():
    assert "PUFA" in build_rag_query({"detections": _det([{"fdi": 11, "severity": 5}])})
    assert "PUFA" not in build_rag_query({"detections": _det([{"fdi": 11, "severity": 2}])})


def test_hidden_lesion_adds_panoramic_terms():
    q = build_rag_query({"detections": _det([{"fdi": 46, "severity": 3, "hidden": True}])})
    assert "panoramik" in q


def test_deciduous_dentition_is_detected_from_fdi_range():
    assert "desidui" in build_rag_query({"detections": _det([{"fdi": 74, "severity": 4}])})
    assert "desidui" not in build_rag_query({"detections": _det([{"fdi": 36, "severity": 4}])})


def test_query_includes_symptom_anamnesa_but_not_administrative_fields():
    q = build_rag_query({"anamnesa": ANAMNESA, "detections": None})
    assert "Cenut-cenut" in q and "Gusi bengkak" in q
    assert "Sulit tidur" not in q


def test_query_handles_no_detections_and_is_bounded():
    q = build_rag_query({"anamnesa": {"lokasi": "x" * 5000}})
    assert "tidak ada lesi terdeteksi" in q and len(q) <= 1200


# ── treatment query ──────────────────────────────────────────────────────────────

def test_treatment_query_names_procedures_not_symptoms():
    q = build_treatment_query({"detections": _det([{"fdi": 11, "severity": 6}])})
    assert "pulpotomi" in q or "pulpektomi" in q
    assert "PUFA" not in q


def test_shallow_lesions_ask_for_remineralisation_not_pulp_therapy():
    q = build_treatment_query({"detections": _det([{"fdi": 22, "severity": 2}])})
    assert "remineralisasi" in q and "SDF" in q
    assert "pulpektomi" not in q


def test_deciduous_teeth_add_child_behaviour_management():
    q = build_treatment_query({"detections": _det([{"fdi": 74, "severity": 4}])})
    assert "gigi sulung" in q


def test_treatment_query_without_lesions_asks_for_prevention():
    q = build_treatment_query({"detections": None})
    assert "pencegahan" in q and len(q) <= 1200


# ── graph wiring ─────────────────────────────────────────────────────────────────

def test_each_agent_gets_its_own_corpus_slice(monkeypatch):
    calls: list[dict] = []

    def _fake_retrieve(query, k=None, categories=None):
        calls.append({"query": query, "k": k, "categories": categories})
        return []

    monkeypatch.setattr("app.llm.graph.rag.retrieve", _fake_retrieve)
    state = run_graph({"anamnesa": ANAMNESA,
                       "detections": _det([{"fdi": 11, "severity": 6}])})

    assert [c["categories"] for c in calls] == [
        ("diagnosis", "context"), ("treatment", "context"),
    ]
    assert state["rag_query"] == calls[0]["query"]
    assert state["rag_treatment_query"] == calls[1]["query"]
    assert state["rag"] == [] and state["rag_treatment"] == []


def test_run_graph_end_to_end_produces_all_three_documents():
    state = run_graph({"patient_name": "Anak A", "anamnesa": ANAMNESA,
                       "detections": _det([{"fdi": 11, "severity": 6},
                                           {"fdi": 16, "severity": 3}])})
    for key in ("diagnosis_md", "recommendation_md", "sanity_md"):
        assert state[key].lstrip().startswith("#")
    assert state["sanity_ok"] is True


def test_run_is_deterministic_on_the_offline_path():
    case = type("C", (), {"patient_name": "Anak A", "anamnesa": ANAMNESA,
                          "detections": _det([{"fdi": 11, "severity": 6}])})()
    assert graph.run(case) == graph.run(case)


def test_sanity_failure_retries_the_recommendation_exactly_once(monkeypatch):
    """The loop-back edge must fire, and must not spin."""
    runs = {"n": 0}

    def _bad_plan(state):
        runs["n"] += 1
        return "# Rencana\n\nTidak menyebut gigi mana pun.\n"

    monkeypatch.setattr(agents, "recommendation_agent", _bad_plan)
    state = run_graph({"anamnesa": ANAMNESA,
                       "detections": _det([{"fdi": 11, "severity": 6}])})

    assert runs["n"] == 2           # initial + one retry
    assert state["sanity_ok"] is False
    assert state["_sanity_loops"] == 1


def test_run_returns_only_the_three_markdown_fields():
    case = type("C", (), {"patient_name": "A", "anamnesa": {}, "detections": None})()
    assert set(graph.run(case)) == {"diagnosis_md", "recommendation_md", "sanity_md"}
