"""The consistency checker.

It is deliberately **deterministic** — the guard on a clinical output must not itself be
able to hallucinate an approval — so every rule here is directly testable.
"""
from app.llm import agents

GOOD_DIAGNOSIS = (
    "# Diagnosis\n\n| Gigi | ICDAS | Kode |\n"
    "| 11 | D6 | K02.1 |\n| 21 | D6 | K02.1 |\n| 22 | D2 | K02.0 |\n| 36 | D4 | K02.1 |\n"
)
GOOD_PLAN = (
    "# Rekomendasi\n\n| Gigi | Tindakan |\n"
    "| 11 | evaluasi pulpa |\n| 21 | restorasi |\n| 22 | pemantauan |\n| 36 | restorasi |\n"
)


def _state(detections, diagnosis=GOOD_DIAGNOSIS, plan=GOOD_PLAN):
    return {"detections": detections, "diagnosis_md": diagnosis, "recommendation_md": plan}


def test_consistent_outputs_pass(sample_detections):
    state = _state(sample_detections)
    md, ok = agents.sanity_agent(state)
    assert ok is True
    assert "Tidak ada kontradiksi" in md
    assert state["sanity_feedback"] == []


def test_a_tooth_missing_from_the_plan_is_a_fixable_defect(sample_detections):
    plan = GOOD_PLAN.replace("| 36 | restorasi |\n", "")
    state = _state(sample_detections, plan=plan)
    md, ok = agents.sanity_agent(state)
    assert ok is False
    assert any("36" in f for f in state["sanity_feedback"])
    assert "36" in md


def test_a_tooth_missing_from_the_diagnosis_is_reported_but_not_retried(sample_detections):
    diagnosis = GOOD_DIAGNOSIS.replace("| 36 | D4 | K02.1 |\n", "")
    _, ok = agents.sanity_agent(_state(sample_detections, diagnosis=diagnosis))
    assert ok is False
    # The retry only re-runs the recommendation, so a diagnosis gap must not enter feedback.
    state = _state(sample_detections, diagnosis=diagnosis)
    agents.sanity_agent(state)
    assert state["sanity_feedback"] == []


def test_planning_treatment_for_an_absent_tooth_is_caught(sample_detections):
    plan = GOOD_PLAN + "| 28 | restorasi |\n"      # 28 is in meta.missing_fdi
    state = _state(sample_detections, plan=plan)
    _, ok = agents.sanity_agent(state)
    assert ok is False
    assert any("ompong" in f for f in state["sanity_feedback"])


def test_codes_outside_the_official_table_are_flagged(sample_detections):
    diagnosis = GOOD_DIAGNOSIS + "| 11 | D6 | K09.1 |\n"
    md, ok = agents.sanity_agent(_state(sample_detections, diagnosis=diagnosis))
    assert ok is False
    assert "K09.1" in md


def test_pulp_codes_require_a_deep_lesion():
    shallow = {"teeth": {"22": {"fdi": 22, "severity": 2}}}
    diagnosis = "# Diagnosis\n| 22 | D2 | K04.0 |\n"
    plan = "# Rencana\n| 22 | pemantauan |\n"
    md, ok = agents.sanity_agent(_state(shallow, diagnosis=diagnosis, plan=plan))
    assert ok is False
    assert "K04.x" in md


def test_idem_answers_are_rejected(sample_detections):
    plan = GOOD_PLAN.replace("| 21 | restorasi |", "| 21 | Idem |")
    state = _state(sample_detections, plan=plan)
    _, ok = agents.sanity_agent(state)
    assert ok is False
    assert any("berulang" in f for f in state["sanity_feedback"])


def test_idem_detection_does_not_fire_on_ordinary_prose(sample_detections):
    plan = GOOD_PLAN + "\nPerawatan idempoten bukan istilah klinis di sini.\n"
    _, ok = agents.sanity_agent(_state(sample_detections, plan=plan))
    assert ok is True


def test_empty_plan_is_a_fixable_defect(sample_detections):
    state = _state(sample_detections, plan="")
    _, ok = agents.sanity_agent(state)
    assert ok is False
    assert any("kosong" in f for f in state["sanity_feedback"])


def test_citation_verification_rate_is_reported(sample_detections):
    state = _state(sample_detections)
    state["diagnosis_citation_stats"] = {"claimed": 4, "verified": 3, "rejected": 1}
    md, _ = agents.sanity_agent(state)
    assert "3 dari 4 kutipan" in md and "1 dibuang" in md
