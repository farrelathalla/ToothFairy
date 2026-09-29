"""The eval harness's deterministic checks.

Regression guard for a real bug: an early `depth_consistency` required a `K02.x` code on
every row, so a D6 tooth correctly coded `K04.4` (acute apical periodontitis of pulpal
origin) scored as a *failure*. An eval that punishes the right answer is worse than no eval.

The per-tooth specificity checks are here for the same reason in reverse: a table can be
100% ICD-valid and still be useless if every row says the same thing.
"""
from evals.run_evals import (
    check_icd,
    check_recommendation,
    check_specificity,
    check_template,
    parse_icd_rows,
    section,
)

DETECTIONS = {
    "teeth": {
        "11": {"fdi": 11, "severity": 6},   # deep — pulp escalation allowed
        "15": {"fdi": 15, "severity": 5},
        "16": {"fdi": 16, "severity": 4},
        "26": {"fdi": 26, "severity": 2},   # shallow — K04.x forbidden
        "17": {"fdi": 17, "severity": 2, "hidden": True},  # radiolucent ⇒ K02.1
    }
}

HEADER = (
    "| Gigi (FDI) | Nama gigi | ICDAS | Kode ICD-10 | Pola kerusakan | Dasar penetapan "
    "| Keyakinan |\n| --- | --- | --- | --- | --- | --- | --- |\n"
)


def _row(fdi, grade, codes, pattern="kavitasi luas, cokelat gelap", basis="dentin",
         confidence="Tinggi", name="insisivus"):
    return f"| {fdi} | {name} | D{grade} | {codes} | {pattern} | {basis} | {confidence} |"


def _table(*rows: str) -> str:
    return "## Diagnosis per Gigi\n" + HEADER + "\n".join(rows) + "\n"


# ── parsing ──────────────────────────────────────────────────────────────────────

def test_parses_fdi_grade_codes_and_pattern():
    md = _table(_row(11, 6, "K02.1, K04.0", pattern="destruksi mahkota, 2 fokus"))
    assert parse_icd_rows(md) == [{
        "fdi": 11, "grade": 6, "codes": ["K02.1", "K04.0"],
        "pattern": "destruksi mahkota, 2 fokus",
    }]


def test_columns_are_located_by_header_name_not_position():
    """Adding a column to the template must not silently break the eval."""
    md = ("## Diagnosis per Gigi\n"
          "| Gigi (FDI) | Kode ICD-10 | ICDAS | Pola kerusakan |\n| --- | --- | --- | --- |\n"
          "| 11 | K02.1 | D6 | kavitasi luas |\n")
    assert parse_icd_rows(md) == [
        {"fdi": 11, "grade": 6, "codes": ["K02.1"], "pattern": "kavitasi luas"}
    ]


def test_section_extraction_stops_at_the_next_heading():
    md = "## Diagnosis per Gigi\nisi tabel\n\n## Batasan & Ketidakpastian\nlain\n"
    assert "isi tabel" in section(md, "## Diagnosis per Gigi")
    assert "lain" not in section(md, "## Diagnosis per Gigi")


# ── ICD-10 checks ────────────────────────────────────────────────────────────────

def test_prior_matching_codes_score_full():
    md = _table(
        _row(11, 6, "K02.1"), _row(15, 5, "K02.1"), _row(16, 4, "K02.1"),
        _row(26, 2, "K02.0"), _row(17, 2, "K02.1"),
    )
    r = check_icd(md, DETECTIONS)
    assert r["depth_consistency"] == 1.0
    assert r["code_validity"] == 1.0
    assert r["tooth_coverage"] == 1.0
    assert r["pulp_escalations"] == 0


def test_deep_lesion_may_escalate_to_a_pulpal_code_instead_of_k02():
    """A D6 coded K04.4 with no K02 code is correct, not a miss."""
    md = _table(_row(11, 6, "K04.4"), _row(15, 5, "K04.0"))
    r = check_icd(md, DETECTIONS)
    assert r["depth_consistency"] == 1.0
    assert r["pulp_escalations"] == 2
    assert r["pulp_code_gated"] == 1.0


def test_escalation_outside_the_differential_is_not_credited():
    # K04.2 (pulp degeneration) is not in the D6 differential.
    assert check_icd(_table(_row(11, 6, "K04.2")), DETECTIONS)["depth_consistency"] == 0.0


def test_pulp_code_on_a_shallow_lesion_is_flagged():
    r = check_icd(_table(_row(26, 2, "K02.0, K04.0")), DETECTIONS)
    assert r["pulp_code_gated"] == 0.0     # K04.x below D5
    assert r["depth_consistency"] == 0.0   # and it doesn't count as consistent


def test_wrong_depth_code_is_flagged():
    assert check_icd(_table(_row(16, 4, "K02.0")), DETECTIONS)["depth_consistency"] == 0.0


def test_hidden_lesion_coded_as_enamel_is_flagged():
    assert check_icd(_table(_row(17, 2, "K02.0")), DETECTIONS)["depth_consistency"] == 0.0


def test_invented_code_fails_validity():
    assert check_icd(_table(_row(11, 6, "K99.9")), DETECTIONS)["code_validity"] == 0.0


def test_partial_tooth_coverage_is_measured():
    r = check_icd(_table(_row(11, 6, "K02.1")), DETECTIONS)
    assert r["rows"] == 1 and r["affected_teeth"] == 5
    assert r["tooth_coverage"] == 0.2


# ── per-tooth specificity ────────────────────────────────────────────────────────

def test_specificity_rewards_distinct_damage_patterns():
    md = _table(
        _row(11, 6, "K02.1", pattern="destruksi mahkota >30%, kehitaman, 2 fokus menyatu"),
        _row(15, 5, "K02.1", pattern="lesi sedang 8%, cokelat muda, fokus tunggal oklusal"),
    )
    r = check_specificity(md)
    assert r["distinct_patterns"] == 1.0
    assert r["idem_rows"] == 0


def test_specificity_penalises_repeated_and_idem_rows():
    md = _table(
        _row(11, 6, "K02.1", pattern="karies dalam"),
        _row(15, 5, "K02.1", pattern="karies dalam"),
        _row(16, 4, "K02.1", pattern="Idem"),
    )
    r = check_specificity(md)
    assert r["distinct_patterns"] < 1.0
    assert r["idem_rows"] == 1


def test_specificity_counts_narrated_teeth_and_the_complaint_section():
    md = _table(_row(11, 6, "K02.1")) + (
        "\n## Analisis Mendalam Gigi Prioritas\n"
        "**Gigi 11 (insisivus)** — kavitasi luas.\n\n"
        "**Gigi 15 (premolar)** — lesi dentin.\n\n"
        "## Korelasi dengan Keluhan Pasien\nGigi 11 menjelaskan nyeri depan atas.\n"
    )
    r = check_specificity(md)
    assert r["teeth_narrated"] == 2
    assert r["has_complaint_correlation"] is True


# ── recommendation checks ────────────────────────────────────────────────────────

RX_HEADER = ("| Gigi (FDI) | Nama gigi | ICDAS | Tindakan utama | Alternatif | Urgensi "
             "| Prasyarat / catatan |\n| --- | --- | --- | --- | --- | --- | --- |\n")


def _plan(*rows: str, extra: str = "") -> str:
    return "## Rencana Perawatan per Gigi\n" + RX_HEADER + "\n".join(rows) + "\n" + extra


def test_recommendation_measures_coverage_and_distinct_actions():
    plan = _plan(
        "| 11 | insisivus | D6 | pulpektomi bila non-vital | ekstraksi | Segera | tes vitalitas |",
        "| 15 | premolar | D5 | restorasi + evaluasi pulpa | SSC | Cepat | foto periapikal |",
        "| 16 | molar | D4 | restorasi GIC | ART | Terjadwal | isolasi |",
        "| 26 | molar | D2 | fluoride varnish | SDF | Pemantauan | kontrol 3 bulan |",
        "| 17 | premolar | D2 | restorasi proksimal | — | Terjadwal | bitewing |",
    )
    r = check_recommendation(plan, DETECTIONS)
    assert r["tooth_coverage"] == 1.0
    assert r["plans_absent_teeth"] == 0
    assert r["distinct_actions"] == 1.0
    assert r["urgency_terms_used"] == 4


def test_recommendation_flags_missing_teeth_and_repeated_actions():
    plan = _plan(
        "| 11 | insisivus | D6 | restorasi | — | Segera | — |",
        "| 15 | premolar | D5 | restorasi | — | Cepat | — |",
    )
    r = check_recommendation(plan, DETECTIONS)
    assert r["tooth_coverage"] == 0.4
    assert r["distinct_actions"] == 0.5


def test_recommendation_flags_planning_for_an_unaffected_tooth():
    plan = _plan("| 48 | molar | D0 | restorasi | — | Segera | — |")
    assert check_recommendation(plan, DETECTIONS)["plans_absent_teeth"] == 1


# ── templates ────────────────────────────────────────────────────────────────────

def test_diagnosis_template_compliance():
    partial = "## Ringkasan Klinis\n## Diagnosis per Gigi\n"
    assert 0 < check_template(partial) < 1

    full = "\n".join([
        "## Ringkasan Klinis", "## Diagnosis per Gigi",
        "## Analisis Mendalam Gigi Prioritas", "## Korelasi dengan Keluhan Pasien",
        "## Diagnosis Banding & Risiko Pulpa", "## Perkiraan Gejala & Dampak Harian",
        "## Batasan & Ketidakpastian",
    ])
    assert check_template(full) == 1.0


def test_recommendation_template_compliance():
    full = "\n".join([
        "## Prioritas & Triase", "## Rencana Perawatan per Gigi", "## Urutan Kunjungan",
        "## Pencegahan & Pengendalian Risiko", "## Edukasi untuk Pasien & Orang Tua",
        "## Tanda Bahaya (Red Flags)", "## Tindak Lanjut & Kontrol",
    ])
    assert check_recommendation(full, DETECTIONS)["template_compliance"] == 1.0
