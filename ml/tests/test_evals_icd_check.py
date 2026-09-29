"""The eval harness's deterministic ICD-10 checks.

Regression guard for a real bug: the first version of `depth_consistency` required a `K02.x`
code on every row, so a D6 tooth correctly coded `K04.4` (acute apical periodontitis of pulpal
origin) scored as a *failure*. On the set3 demo that dragged a perfect answer down to 28.6%.
An eval that punishes the right answer is worse than no eval.
"""
from evals.run_evals import check_icd, check_template, parse_icd_rows

DETECTIONS = {
    "teeth": {
        "11": {"fdi": 11, "severity": 6},   # deep — pulp escalation allowed
        "15": {"fdi": 15, "severity": 5},
        "16": {"fdi": 16, "severity": 4},
        "26": {"fdi": 26, "severity": 2},   # shallow — K04.x forbidden
        "17": {"fdi": 17, "severity": 2, "hidden": True},  # radiolucent ⇒ K02.1
    }
}

HEADER = "| Gigi (FDI) | ICDAS | Kode ICD-10 | Dasar | Keyakinan |\n| --- | --- | --- | --- | --- |\n"


def _table(*rows: str) -> str:
    return "## Diagnosis per Gigi\n" + HEADER + "\n".join(rows) + "\n"


def test_parses_fdi_grade_and_codes():
    md = _table("| 11 | D6 | K02.1, K04.0 | dalam | Sedang |")
    assert parse_icd_rows(md) == [{"fdi": 11, "grade": 6, "codes": ["K02.1", "K04.0"]}]


def test_prior_matching_codes_score_full():
    md = _table(
        "| 11 | D6 | K02.1 | dentin | Tinggi |",
        "| 15 | D5 | K02.1 | dentin | Tinggi |",
        "| 16 | D4 | K02.1 | dentin | Tinggi |",
        "| 26 | D2 | K02.0 | email | Tinggi |",
        "| 17 | D2 | K02.1 | radiolusen | Sedang |",
    )
    r = check_icd(md, DETECTIONS)
    assert r["depth_consistency"] == 1.0
    assert r["code_validity"] == 1.0
    assert r["tooth_coverage"] == 1.0
    assert r["pulp_escalations"] == 0


def test_deep_lesion_may_escalate_to_a_pulpal_code_instead_of_k02():
    """The set3 case: D6 coded K04.4 with no K02 code is correct, not a miss."""
    md = _table(
        "| 11 | D6 | K04.4 | periodontitis apikalis | Sedang |",
        "| 15 | D5 | K04.0 | pulpitis | Sedang |",
    )
    r = check_icd(md, DETECTIONS)
    assert r["depth_consistency"] == 1.0
    assert r["pulp_escalations"] == 2
    assert r["pulp_code_gated"] == 1.0


def test_escalation_outside_the_differential_is_not_credited():
    # K04.2 (pulp degeneration) is not in the D6 differential.
    md = _table("| 11 | D6 | K04.2 | ? | Rendah |")
    assert check_icd(md, DETECTIONS)["depth_consistency"] == 0.0


def test_pulp_code_on_a_shallow_lesion_is_flagged():
    md = _table("| 26 | D2 | K02.0, K04.0 | ? | Rendah |")
    r = check_icd(md, DETECTIONS)
    assert r["pulp_code_gated"] == 0.0     # K04.x below D5
    assert r["depth_consistency"] == 0.0   # and it doesn't count as consistent


def test_wrong_depth_code_is_flagged():
    md = _table("| 16 | D4 | K02.0 | salah, D4 sudah dentin | Tinggi |")
    assert check_icd(md, DETECTIONS)["depth_consistency"] == 0.0


def test_hidden_lesion_coded_as_enamel_is_flagged():
    md = _table("| 17 | D2 | K02.0 | salah, ini radiolusensi dentin | Sedang |")
    assert check_icd(md, DETECTIONS)["depth_consistency"] == 0.0


def test_invented_code_fails_validity():
    md = _table("| 11 | D6 | K99.9 | ngarang | Rendah |")
    assert check_icd(md, DETECTIONS)["code_validity"] == 0.0


def test_partial_tooth_coverage_is_measured():
    md = _table("| 11 | D6 | K02.1 | dentin | Tinggi |")
    r = check_icd(md, DETECTIONS)
    assert r["rows"] == 1 and r["affected_teeth"] == 5
    assert r["tooth_coverage"] == 0.2


def test_template_compliance():
    assert check_template("## Ringkasan Klinis\n## Diagnosis per Gigi\n") == 0.4
    full = "\n".join(
        ["## Ringkasan Klinis", "## Diagnosis per Gigi", "## Diagnosis Banding & Risiko Pulpa",
         "## Perkiraan Gejala & Dampak Harian", "## Batasan & Ketidakpastian"]
    )
    assert check_template(full) == 1.0
