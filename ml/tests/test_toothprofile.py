"""Per-tooth descriptors — the input that makes a per-tooth answer possible.

The point of `toothprofile` is that two teeth with the **same ICDAS grade** still get
different prose, because their measurements differ. These tests pin that property down
directly: if the profiles of the two D6 teeth in the fixture ever collapse to the same text,
the "Idem" failure mode is back.
"""
from app.llm import toothprofile


def test_tooth_names_cover_both_dentitions_and_all_quadrants():
    assert toothprofile.tooth_name(24) == "premolar satu rahang atas kiri"
    assert toothprofile.tooth_name(11) == "insisivus sentral rahang atas kanan"
    assert toothprofile.tooth_name(47) == "molar dua rahang bawah kanan"
    assert toothprofile.tooth_name(74) == "molar satu sulung rahang bawah kiri (sulung)"
    assert toothprofile.is_deciduous(74) is True
    assert toothprofile.is_deciduous(34) is False


def test_anterior_classification_follows_fdi_position():
    assert toothprofile.is_anterior(13) is True     # canine
    assert toothprofile.is_anterior(14) is False    # first premolar


def test_extent_and_discoloration_bands_are_monotonic():
    bands = [toothprofile.extent_band(r) for r in (0.02, 0.10, 0.20, 0.40)]
    assert len(set(bands)) == 4
    assert "ekstensif" in bands[-1]

    colours = [toothprofile.discoloration_band(d) for d in (0.10, 0.30, 0.55, 0.85)]
    assert len(set(colours)) == 4
    assert "nekrotik" in colours[-1]


def test_absent_measurements_render_as_nothing_not_as_a_zero():
    """A grader-only tooth has no polygon; printing "0.0" would read as "no disease"."""
    assert toothprofile.extent_band(None) == ""
    assert toothprofile.discoloration_band(0) == ""
    assert toothprofile.lesion_pattern([]) == ""
    assert toothprofile.radiographic_note({"pano_grade": 0}) == ""


def test_lesion_pattern_reports_count_kind_and_spread():
    single = toothprofile.lesion_pattern(
        [{"u": 0.5, "v": 0.5, "r": 0.4, "type": "Cavity"}]
    )
    assert "kavitasi terbuka" in single and "fokus tunggal" in single

    multi = toothprofile.lesion_pattern([
        {"u": 0.5, "v": 0.5, "r": 0.4, "type": "Cavity"},
        {"u": 0.95, "v": 0.05, "r": 0.2, "type": "Crack"},
    ])
    assert "2 fokus" in multi and "retak/fraktur email" in multi


def test_confidence_rises_with_agreeing_detectors(sample_detections):
    teeth = sample_detections["teeth"]
    strong, _ = toothprofile.confidence(teeth["11"])   # rfdetr + seg, high conf
    weak, reason = toothprofile.confidence(teeth["22"])  # seg only, interpolated box, low conf
    assert strong == "Tinggi"
    assert weak == "Rendah"
    assert "interpolasi" in reason


def test_hidden_lesions_are_described_as_radiographic(sample_detections):
    note = toothprofile.radiographic_note(sample_detections["teeth"]["36"])
    assert "radiolusensi panoramik" in note and "email yang utuh" in note


def test_profiles_are_sorted_by_severity_and_skip_healthy_teeth(sample_detections):
    rows = toothprofile.profiles(sample_detections)
    assert [r["fdi"] for r in rows] == [11, 21, 36, 22]
    assert all(r["grade"] > 0 for r in rows)


def test_two_teeth_of_the_same_grade_get_different_descriptions(sample_detections):
    """The whole reason this module exists."""
    rows = {r["fdi"]: r for r in toothprofile.profiles(sample_detections)}
    a, b = rows[11], rows[21]
    assert a["grade"] == b["grade"] == 6
    assert a["extent"] != b["extent"]
    assert a["discoloration"] != b["discoloration"]
    assert a["pattern"] != b["pattern"]


def test_rendered_block_omits_absent_measurements_and_names_the_gap_once(sample_detections):
    """Repeating "not measurable" per field is how uniform, uninformative rows come back."""
    grader_only = {"fdi": 13, "severity": 6, "grade_source": "rfdetr",
                   "caries_ratio": 0.0, "rel_dark": 0.0, "lesions": [],
                   "sources": ["rfdetr"], "pano_grade": 0}
    text = toothprofile.render_profiles([toothprofile.profile(grader_only)])
    assert text.count("Tidak terukur pada citra ini") == 1
    assert "- Luas:" not in text and "- Warna:" not in text and "- Pola lesi:" not in text
    assert "bukan bukti jaringan normal" in text
    assert "ICDAS: **D6**" in text


def test_rendered_block_names_each_tooth_and_carries_its_numbers(sample_detections):
    text = toothprofile.render_profiles(toothprofile.profiles(sample_detections))
    assert "### Gigi 11 — insisivus sentral rahang atas kanan" in text
    assert "### Gigi 21 — insisivus sentral rahang atas kiri" in text
    assert "rasio karies 0.34" in text and "rasio karies 0.08" in text
    assert "Kekuatan bukti: Tinggi" in text


def test_render_handles_a_healthy_patient():
    assert "Tidak ada gigi terdampak" in toothprofile.render_profiles([])
