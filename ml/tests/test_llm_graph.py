"""The advisory graph (scaffold) runs end-to-end: rag → diagnosis → recommendation →
sanity_check, producing both markdown fields deterministically, with the sanity node
executed (and the loop-once edge available)."""
from app.llm import graph
from app.llm.graph import run_graph

DETECTIONS = {
    "teeth": {
        "11": {"fdi": 11, "severity": 6},
        "16": {"fdi": 16, "severity": 3},
        "21": {"fdi": 21, "severity": 0},
    }
}

ANAMNESA = {"lokasi": "Gigi depan atas", "quality": "Ngilu", "severity": "Skala 5",
            "chronology": "2 minggu", "alasan_kuat": "Nyeri saat makan"}


def test_run_graph_end_to_end():
    state = run_graph({"patient_name": "Anak A", "anamnesa": ANAMNESA, "detections": DETECTIONS})
    assert state["diagnosis_md"].lstrip().startswith("#")
    assert state["recommendation_md"].lstrip().startswith("#")
    assert state["sanity_md"].lstrip().startswith("#")
    assert state["sanity_ok"] is True
    # rag node executed (stub returns empty list)
    assert state["rag"] == []
    # diagnosis reflects the detected grades, worst-first
    assert "Gigi 11: ICDAS D6" in state["diagnosis_md"]


def test_graph_is_deterministic():
    args = {"patient_name": "Anak A", "anamnesa": ANAMNESA, "detections": DETECTIONS}
    assert run_graph(dict(args)) == run_graph(dict(args))


def test_sanity_loop_bounded_when_incomplete():
    # Force sanity to fail (no recommendation ever) by stubbing the agent → loop must be bounded.
    from app.llm import agents

    orig = agents.recommendation_agent
    try:
        agents.recommendation_agent = lambda state: ""  # produces empty rec → sanity not ok
        state = run_graph({"patient_name": "X", "anamnesa": ANAMNESA, "detections": None})
        assert state["_sanity_loops"] == 1  # looped exactly once, then stopped
        assert state["sanity_ok"] is False
    finally:
        agents.recommendation_agent = orig


class _Case:
    patient_name = "Anak A"
    anamnesa = ANAMNESA


def test_run_public_entry_returns_three_fields():
    out = graph.run(_Case())
    assert set(out) == {"diagnosis_md", "recommendation_md", "sanity_md"}
    assert all(out.values())
