"""ICDAS → ICD-10 mapping heuristic (pure, no key needed)."""
from app.llm import icd10


def test_table_covers_the_dentists_code_set():
    table = icd10.render_table()
    for code in ("K02.0", "K02.1", "K02.3", "K03.2", "K04.0", "K04.1", "K04.7"):
        assert f"**{code}**" in table


def test_enamel_grades_map_to_k02_0_without_pulp_differential():
    for grade in (1, 2):
        row = icd10.map_grade(grade)
        assert row["primary"] == "K02.0"
        assert row["differential"] == []


def test_dentine_grades_map_to_k02_1():
    for grade in (3, 4):
        row = icd10.map_grade(grade)
        assert row["primary"] == "K02.1"
        assert row["differential"] == []


def test_deep_grades_carry_a_pulp_differential():
    assert icd10.map_grade(5)["differential"] == ["K04.0"]
    d6 = icd10.map_grade(6)["differential"]
    assert d6[:2] == ["K04.0", "K04.1"]
    assert "K04.7" in d6  # periapical abscess must be considered at D6


def test_healthy_tooth_has_no_code():
    assert icd10.map_grade(0)["primary"] is None


def test_hidden_lesion_is_never_enamel_only():
    # A panoramic-only radiolucency sits in dentine even when the grade is low.
    assert icd10.map_grade(2, hidden=True)["primary"] == "K02.1"
    assert icd10.map_grade(2, hidden=False)["primary"] == "K02.0"


def test_map_detections_orders_worst_first_and_skips_healthy():
    det = {
        "teeth": {
            "16": {"fdi": 16, "severity": 3, "grade_source": "seg"},
            "11": {"fdi": 11, "severity": 6, "grade_source": "rfdetr+seg"},
            "21": {"fdi": 21, "severity": 0},
            "46": {"fdi": 46, "severity": 2, "hidden": True, "grade_source": "panoramic"},
        }
    }
    rows = icd10.map_detections(det)
    assert [r["fdi"] for r in rows] == [11, 16, 46]
    assert rows[0]["primary"] == "K02.1" and "K04.1" in rows[0]["differential"]
    assert rows[2]["hidden"] is True and rows[2]["primary"] == "K02.1"


def test_map_detections_tolerates_missing_input():
    assert icd10.map_detections(None) == []
    assert icd10.map_detections({}) == []


def test_missing_fdi_reads_meta():
    assert icd10.missing_fdi({"meta": {"missing_fdi": ["28", "18"]}}) == [18, 28]
    assert icd10.missing_fdi(None) == []


def test_describe_adds_indonesian_gloss():
    assert icd10.describe(["K02.1"]) == ["K02.1 — Karies dentin"]
    assert icd10.describe(["ZZZ"]) == ["ZZZ"]
