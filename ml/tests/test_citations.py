"""Verified citations.

A citation is only worth showing a dentist if the quote is really in the document, so the
renderer verifies every claimed span before it renders it. These tests pin down the
security-relevant half: a **fabricated quote must lose its marker**, not gain a footnote.
"""
from app.llm import citations

DOCS = [
    {"doc_id": "1", "title": "Impact of untreated caries", "ref": "DOI: 10.1111/jphd.12259",
     "context": "Hasil studi kohort.",
     "text": "Children with untreated caries report difficulty eating and disturbed sleep "
             "across all age groups studied."},
    {"doc_id": "2", "title": "PUFA index and OHRQoL", "ref": "URL: jimc.ir",
     "context": "Definisi PUFA.",
     "text": "PUFA scores pulpal involvement, ulceration, fistula and abscess in a single "
             "index."},
]


def _answer(body: str, block: str) -> str:
    return f"{body}\n\n<!--SITASI\n{block}\n-->"


def test_documents_render_numbered_with_context_outside_the_citable_body():
    text = citations.render_documents(DOCS)
    assert 'nomor="1"' in text and 'nomor="2"' in text
    assert "Children with untreated caries" in text
    # the ingest-time blurb is orientation, never quotable text
    assert "[konteks: Hasil studi kohort.]" in text


def test_no_documents_renders_nothing():
    assert citations.render_documents([]) == ""


def test_verified_quote_becomes_a_footnote_with_the_verbatim_text():
    md, sources, stats = citations.parse_and_verify(
        _answer("Anak sulit makan dan tidurnya terganggu.[^1]",
                "1|1|report difficulty eating and disturbed sleep"),
        DOCS,
    )
    assert "terganggu.[^1]" in md
    assert "## Rujukan" in md
    assert "[^1]: **Impact of untreated caries** — DOI: 10.1111/jphd.12259" in md
    assert "> report difficulty eating and disturbed sleep" in md
    assert [s["doc_id"] for s in sources] == ["1"]
    assert stats == {"claimed": 1, "verified": 1, "rejected": 0}
    assert "SITASI" not in md


def test_fabricated_quote_is_rejected_and_its_marker_removed():
    md, sources, stats = citations.parse_and_verify(
        _answer("Prevalensi karies anak Indonesia 93%.[^1]",
                "1|1|prevalence of caries in Indonesian children reached 93 percent"),
        DOCS,
    )
    assert "[^1]" not in md
    assert "## Rujukan" not in md
    assert sources == []
    assert stats == {"claimed": 1, "verified": 0, "rejected": 1}


def test_quote_attributed_to_the_wrong_document_is_rejected():
    _, _, stats = citations.parse_and_verify(
        _answer("Klaim.[^1]", "1|2|report difficulty eating and disturbed sleep"), DOCS
    )
    assert stats["verified"] == 0 and stats["rejected"] == 1


def test_punctuation_and_whitespace_differences_are_tolerated():
    """PDF extraction mangles dashes and ligatures; that must not fail a real quote."""
    md, _, stats = citations.parse_and_verify(
        _answer("Klaim.[^1]",
                "1|2|PUFA scores pulpal involvement — ulceration, fistula and abscess"),
        DOCS,
    )
    assert stats["verified"] == 1
    assert "[^1]" in md


def test_too_short_a_span_is_not_evidence():
    _, _, stats = citations.parse_and_verify(_answer("Klaim.[^1]", "1|1|sleep"), DOCS)
    assert stats["verified"] == 0


def test_footnotes_are_renumbered_by_first_use_and_deduplicated_per_document():
    body = ("Klaim A.[^2] Klaim B.[^1] Klaim C tentang dokumen dua lagi.[^2]")
    block = ("1|1|report difficulty eating and disturbed sleep\n"
             "2|2|PUFA scores pulpal involvement, ulceration, fistula and abscess")
    md, sources, stats = citations.parse_and_verify(_answer(body, block), DOCS)

    # doc 2 was cited first, so it becomes [^1]
    assert "Klaim A.[^1]" in md and "Klaim B.[^2]" in md and "Klaim C tentang dokumen dua lagi.[^1]" in md
    assert [s["doc_id"] for s in sources] == ["2", "1"]
    assert stats["verified"] == 2


def test_answer_without_a_citation_block_is_returned_clean():
    md, sources, stats = citations.parse_and_verify("# Diagnosis\n\nTanpa sitasi.", DOCS)
    assert md.strip() == "# Diagnosis\n\nTanpa sitasi."
    assert sources == [] and stats["claimed"] == 0


def test_malformed_citation_lines_are_skipped_not_raised():
    md, _, stats = citations.parse_and_verify(
        _answer("Klaim.[^1]", "garbage\n|\n1|1|report difficulty eating and disturbed sleep"),
        DOCS,
    )
    assert stats["verified"] == 1 and "[^1]" in md
