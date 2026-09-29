"""The clinical agents, with the OpenAI SDK faked. No live API call in the suite.

Covers what can silently rot:
  1. the **disabled path** returns a deterministic stub (the offline demo depends on it);
  2. the **prompt** carries the ICD-10 table, the per-tooth quantitative profiles and the
     retrieved passages as numbered document blocks;
  3. the **anti-Idem contract** is actually in the prompt and actually enforced afterwards;
  4. **failures are contained** — a rate limit degrades the card, it never fails the case.
"""
import pytest

from app.config import settings
from app.llm import agents, openai_client, prompts
from tests.fakes import FakeClient

ANAMNESA = {"lokasi": "Gigi depan atas", "quality": "Ngilu",
            "alasan_kuat": "Nyeri saat makan"}

PASSAGES = [
    {"doc_id": "1", "title": "Impact of untreated caries", "ref": "DOI: 10.1111/jphd.12259",
     "context": "Hasil studi kohort.",
     "text": "Children with untreated caries report difficulty eating and disturbed sleep."},
    {"doc_id": "2", "title": "PUFA index and OHRQoL", "ref": "URL: jimc.ir",
     "context": "Definisi PUFA.",
     "text": "PUFA scores pulpal involvement, ulceration, fistula and abscess."},
]

TREATMENT_PASSAGES = [
    {"doc_id": "12", "title": "SDF guideline", "ref": "AAPD 2017", "context": "Panduan SDF.",
     "text": "Silver diamine fluoride arrests caries lesions in primary teeth."},
]

ANSWER = (
    "# Diagnosis\n\n## Ringkasan Klinis\nKaries rampan pada lengkung atas.\n\n"
    "Anak diperkirakan sulit makan dan tidurnya terganggu.[^1]\n\n"
    "<!--SITASI\n1|1|report difficulty eating and disturbed sleep\n-->"
)

PLAN_ANSWER = (
    "# Rekomendasi Penanganan\n\n## Rencana Perawatan per Gigi\n"
    "| Gigi | Nama gigi | ICDAS | Tindakan utama |\n| --- | --- | --- | --- |\n"
    "| 11 | insisivus | D6 | evaluasi pulpa |\n| 21 | insisivus | D6 | restorasi |\n"
    "| 22 | insisivus | D2 | pemantauan |\n| 36 | molar | D4 | restorasi |\n"
)


@pytest.fixture
def captured(monkeypatch):
    """Turn the agents on and swap the SDK client for a capturing fake."""
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    box: dict = {}
    state = {"text": ANSWER}

    monkeypatch.setattr(openai_client, "get_client",
                        lambda: FakeClient(box, state["text"]))
    box["_set_text"] = lambda t: state.__setitem__("text", t)
    return box


def _state(detections):
    return {"patient_name": "Anak A", "anamnesa": ANAMNESA, "detections": detections,
            "rag": list(PASSAGES), "rag_treatment": list(TREATMENT_PASSAGES)}


# ── disabled path ────────────────────────────────────────────────────────────────

def test_disabled_diagnosis_returns_a_deterministic_stub(monkeypatch, sample_detections):
    monkeypatch.setattr(settings, "llm_enabled", False)
    md = agents.diagnosis_agent(_state(sample_detections))
    assert md.lstrip().startswith("#")
    assert "Gigi 11 (insisivus sentral rahang atas kanan): ICDAS D6" in md
    assert agents.diagnosis_agent(_state(sample_detections)) == md


def test_disabled_recommendation_still_covers_every_affected_tooth(
    monkeypatch, sample_detections
):
    monkeypatch.setattr(settings, "llm_enabled", False)
    md = agents.recommendation_agent(_state(sample_detections))
    for fdi in (11, 21, 22, 36):
        assert f"| {fdi} |" in md
    assert "47" not in md.split("## ")[0]      # healthy tooth is not planned for


def test_enabled_without_a_key_still_uses_the_stub(monkeypatch, sample_detections):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "")
    assert openai_client.is_enabled() is False
    assert "Anak A" in agents.diagnosis_agent(_state(sample_detections))


# ── prompt construction ──────────────────────────────────────────────────────────

def test_system_prompt_is_byte_stable_across_patients():
    """It is the cache prefix — a patient name leaking in would blow the cache every call."""
    assert prompts.diagnosis.build_system() == prompts.diagnosis.build_system()
    assert "Anak A" not in prompts.diagnosis.build_system()
    assert prompts.recommendation.build_system() == prompts.recommendation.build_system()


def test_diagnosis_instructions_carry_the_icd10_table_and_template(
    captured, sample_detections
):
    agents.diagnosis_agent(_state(sample_detections))
    system = captured["instructions"]
    assert "**K02.1**" in system and "**K04.7**" in system
    assert "Diagnosis per Gigi" in system
    assert "Analisis Mendalam Gigi Prioritas" in system
    assert "Korelasi dengan Keluhan Pasien" in system


def test_diagnosis_prompt_forbids_idem_answers(captured, sample_detections):
    agents.diagnosis_agent(_state(sample_detections))
    system = captured["instructions"]
    assert "Idem" in system and "DILARANG" in system


def test_user_turn_carries_per_tooth_numbers_priors_and_anamnesa(
    captured, sample_detections
):
    agents.diagnosis_agent(_state(sample_detections))
    user = captured["input"][0]["content"][0]["text"]
    assert "| 11 | insisivus sentral rahang atas kanan | D6 |" in user
    assert "K04.1" in user                                  # D6 differential reached it
    assert "### Gigi 11 — insisivus sentral rahang atas kanan" in user
    assert "rasio karies 0.34" in user and "rasio karies 0.08" in user
    assert "Gigi hilang (ompong)" in user and "28" in user
    assert "Ngilu" in user
    assert "| 47 |" not in user                             # healthy tooth omitted


def test_passages_become_numbered_document_blocks(captured, sample_detections):
    agents.diagnosis_agent(_state(sample_detections))
    user = captured["input"][0]["content"][0]["text"]
    assert 'nomor="1"' in user and 'nomor="2"' in user
    assert "Children with untreated caries" in user
    assert "[konteks: Hasil studi kohort.]" in user


def test_no_passages_tells_the_model_not_to_cite(captured, sample_detections):
    state = _state(sample_detections)
    state["rag"] = []
    agents.diagnosis_agent(state)
    user = captured["input"][0]["content"][0]["text"]
    assert "jangan menyebut sumber apa pun" in user
    assert "<dokumen" not in user


def test_model_params_match_the_responses_api_contract(captured, sample_detections):
    agents.diagnosis_agent(_state(sample_detections))
    assert captured["model"] == settings.llm_model
    assert captured["reasoning"] == {"effort": settings.llm_effort}
    assert captured["max_output_tokens"] == settings.llm_max_tokens
    assert captured["prompt_cache_key"] == "toothfairy-diagnosis"
    # Reasoning models reject sampling params — they must never be sent.
    assert "temperature" not in captured and "top_p" not in captured


def test_recommendation_reads_the_treatment_passages_and_the_diagnosis(
    captured, sample_detections
):
    state = _state(sample_detections)
    state["diagnosis_md"] = "# Diagnosis\n\nGigi 11 K02.1."
    captured["_set_text"](PLAN_ANSWER)
    agents.recommendation_agent(state)

    user = captured["input"][0]["content"][0]["text"]
    assert "Silver diamine fluoride" in user          # treatment slice, not the diagnosis one
    assert "Children with untreated caries" not in user
    assert "Gigi 11 K02.1" in user                    # anchored to the established diagnosis
    assert captured["prompt_cache_key"] == "toothfairy-recommendation"


def test_sanity_feedback_is_injected_into_the_retry(captured, sample_detections):
    state = _state(sample_detections)
    state["diagnosis_md"] = "# Diagnosis"
    state["sanity_feedback"] = ["Gigi terdampak belum muncul pada rencana perawatan: 36."]
    captured["_set_text"](PLAN_ANSWER)
    agents.recommendation_agent(state)

    user = captured["input"][0]["content"][0]["text"]
    assert "Koreksi wajib" in user and "36" in user


# ── citation rendering ───────────────────────────────────────────────────────────

def test_verified_citations_render_as_footnotes(captured, sample_detections):
    state = _state(sample_detections)
    md = agents.diagnosis_agent(state)
    assert "terganggu.[^1]" in md
    assert "## Rujukan" in md
    assert "> report difficulty eating and disturbed sleep" in md
    assert state["diagnosis_citation_stats"] == {"claimed": 1, "verified": 1, "rejected": 0}
    assert state["diagnosis_usage"]["cached_input_tokens"] == 3100


def test_fabricated_citation_is_stripped_from_the_answer(captured, sample_detections):
    captured["_set_text"](
        "# Diagnosis\n\nPrevalensi 93%.[^1]\n\n<!--SITASI\n1|1|prevalence was 93 percent\n-->"
    )
    state = _state(sample_detections)
    md = agents.diagnosis_agent(state)
    assert "[^1]" not in md and "## Rujukan" not in md
    assert state["diagnosis_citation_stats"]["rejected"] == 1


# ── failure containment ──────────────────────────────────────────────────────────

def test_api_failure_falls_back_to_the_stub(captured, monkeypatch, sample_detections):
    def _boom():
        raise RuntimeError("rate limited")

    monkeypatch.setattr(openai_client, "get_client", _boom)
    state = _state(sample_detections)
    md = agents.diagnosis_agent(state)
    assert "Gigi 11" in md                       # the case still gets an advisory card
    assert "rate limited" in state["diagnosis_error"]


def test_truncated_response_is_treated_as_a_failure(monkeypatch, sample_detections):
    """A half-written clinical table is worse than the stub."""
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(openai_client, "get_client",
                        lambda: FakeClient({}, "# Diagnosis\n\n| 11 |", status="incomplete"))
    state = _state(sample_detections)
    md = agents.diagnosis_agent(state)
    assert "max_output_tokens" in state["diagnosis_error"]
    assert md.lstrip().startswith("# Diagnosis (sementara)")
