"""Diagnosis agent — with `anthropic` mocked. No live API call in the suite.

Covers the three things that can silently rot:
  1. the **disabled path** still returns the exact Phase-8 stub (jobs/seed/E2E depend on it);
  2. the **prompt** actually carries the ICD-10 table, the per-tooth priors and the retrieved
     passages as citable `document` blocks;
  3. **citations** come back as footnotes with the verbatim `cited_text` a dentist can audit.
"""
import pytest

from app.config import settings
from app.llm import agents, claude, prompts

DETECTIONS = {
    "meta": {"missing_fdi": ["28"], "hidden_fdi": ["46"]},
    "teeth": {
        "11": {"fdi": 11, "severity": 6, "grade_source": "rfdetr+seg"},
        "16": {"fdi": 16, "severity": 3, "grade_source": "seg"},
        "46": {"fdi": 46, "severity": 2, "hidden": True, "grade_source": "panoramic"},
        "21": {"fdi": 21, "severity": 0},
    },
}
ANAMNESA = {"lokasi": "Gigi depan atas", "quality": "Ngilu", "alasan_kuat": "Nyeri saat makan"}
PASSAGES = [
    {"doc_id": "1", "title": "Impact of untreated caries", "ref": "DOI: 10.1111/jphd.12259",
     "context": "Hasil studi kohort.", "score": 0.9,
     "text": "Children with untreated caries report difficulty eating and disturbed sleep."},
    {"doc_id": "2", "title": "PUFA index and OHRQoL", "ref": "URL: jimc.ir",
     "context": "Definisi PUFA.", "score": 0.8,
     "text": "PUFA scores pulpal involvement, ulceration, fistula and abscess."},
]


# ── fake anthropic SDK ───────────────────────────────────────────────────────────

class _Citation:
    def __init__(self, document_index, cited_text):
        self.document_index = document_index
        self.cited_text = cited_text


class _TextBlock:
    type = "text"

    def __init__(self, text, citations=None):
        self.text = text
        self.citations = citations or []


class _Usage:
    input_tokens = 1200
    output_tokens = 800
    cache_creation_input_tokens = 900
    cache_read_input_tokens = 0


class _Message:
    def __init__(self, content):
        self.content = content
        self.usage = _Usage()


class _FakeClient:
    def __init__(self, captured, content):
        self._captured = captured
        self._content = content
        self.messages = self

    def create(self, **kwargs):
        self._captured.update(kwargs)
        return _Message(self._content)


DEFAULT_CONTENT = [
    _TextBlock("# Diagnosis\n\n## Ringkasan Klinis\nKaries rampan pada lengkung atas. "),
    _TextBlock(
        "Anak diperkirakan sulit makan dan tidurnya terganggu.",
        [_Citation(0, "difficulty eating and disturbed sleep")],
    ),
    _TextBlock(
        " Lesi D6 berisiko berkembang menjadi abses.",
        [_Citation(1, "PUFA scores pulpal involvement, ulceration, fistula and abscess.")],
    ),
]


@pytest.fixture
def live_llm(monkeypatch):
    """Turn the agent on and swap the SDK client for a capturing fake."""
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")
    captured: dict = {}

    def _fake_get_client(content=DEFAULT_CONTENT):
        return _FakeClient(captured, content)

    monkeypatch.setattr(claude, "get_client", _fake_get_client)
    return captured


def _state():
    return {"patient_name": "Anak A", "anamnesa": ANAMNESA,
            "detections": DETECTIONS, "rag": list(PASSAGES)}


# ── disabled path ────────────────────────────────────────────────────────────────

def test_disabled_returns_the_deterministic_stub(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", False)
    md = agents.diagnosis_agent(_state())
    assert "TODO(LLM)" in md
    assert "Gigi 11: ICDAS D6" in md
    assert agents.diagnosis_agent(_state()) == md


def test_enabled_without_a_key_still_uses_the_stub(monkeypatch):
    monkeypatch.setattr(settings, "llm_enabled", True)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert claude.is_enabled() is False
    assert "TODO(LLM)" in agents.diagnosis_agent(_state())


# ── prompt construction ──────────────────────────────────────────────────────────

def test_system_prompt_is_cached_and_carries_the_icd10_table(live_llm):
    agents.diagnosis_agent(_state())
    system = live_llm["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert "**K02.1**" in system[0]["text"] and "**K04.7**" in system[0]["text"]
    assert "Diagnosis per Gigi" in system[0]["text"]


def test_system_prompt_is_byte_stable_across_patients():
    """It's the cache prefix — a patient name leaking in would blow the cache every call."""
    assert prompts.build_system() == prompts.build_system()
    assert "Anak A" not in prompts.build_system()


def test_user_turn_carries_detections_priors_and_anamnesa(live_llm):
    agents.diagnosis_agent(_state())
    blocks = live_llm["messages"][0]["content"]
    user_text = blocks[-1]["text"]
    assert "| 11 | D6 |" in user_text
    assert "K04.1" in user_text                      # D6 differential reached the prompt
    assert "| 46 | D2 |" in user_text and "ya" in user_text  # hidden lesion flagged
    assert "| 21 |" not in user_text                          # healthy tooth omitted
    assert "Gigi hilang (ompong)" in user_text and "28" in user_text
    assert "Ngilu" in user_text


def test_passages_become_citable_document_blocks(live_llm):
    agents.diagnosis_agent(_state())
    blocks = live_llm["messages"][0]["content"]
    docs = [b for b in blocks if b["type"] == "document"]
    assert len(docs) == 2
    assert all(d["citations"] == {"enabled": True} for d in docs)
    assert docs[0]["source"]["data"].startswith("Children with untreated caries")
    assert docs[0]["context"] == "Hasil studi kohort."   # blurb is context, never cited text
    assert docs[0]["title"] == "Impact of untreated caries"


def test_no_passages_tells_the_model_not_to_cite(live_llm):
    state = _state()
    state["rag"] = []
    agents.diagnosis_agent(state)
    user_text = live_llm["messages"][0]["content"][-1]["text"]
    assert "jangan menyebut sumber apa pun" in user_text


def test_model_params_match_sonnet_5_contract(live_llm):
    agents.diagnosis_agent(_state())
    assert live_llm["model"] == settings.llm_model
    assert live_llm["thinking"] == {"type": "adaptive"}
    assert live_llm["output_config"] == {"effort": settings.llm_effort}
    # budget_tokens / temperature are rejected by Sonnet 5 — must never be sent.
    assert "temperature" not in live_llm and "top_p" not in live_llm


# ── citation rendering ───────────────────────────────────────────────────────────

def test_citations_render_as_footnotes_with_verbatim_quotes(live_llm):
    state = _state()
    md = agents.diagnosis_agent(state)

    assert "sulit makan dan tidurnya terganggu.[^1]" in md
    assert "abses.[^2]" in md
    assert "## Rujukan" in md
    assert "[^1]: **Impact of untreated caries** — DOI: 10.1111/jphd.12259" in md
    assert "> difficulty eating and disturbed sleep" in md

    sources = state["diagnosis_sources"]
    assert [s["doc_id"] for s in sources] == ["1", "2"]
    assert state["diagnosis_usage"]["cache_creation_input_tokens"] == 900


def test_uncited_output_renders_without_a_rujukan_section(live_llm, monkeypatch):
    monkeypatch.setattr(claude, "get_client",
                        lambda: _FakeClient(live_llm, [_TextBlock("# Diagnosis\n\nTanpa sitasi.")]))
    md = agents.diagnosis_agent(_state())
    assert "## Rujukan" not in md
    assert "[^" not in md


# ── failure containment ──────────────────────────────────────────────────────────

def test_api_failure_falls_back_to_the_stub(live_llm, monkeypatch):
    def _boom():
        raise RuntimeError("rate limited")

    monkeypatch.setattr(claude, "get_client", _boom)
    state = _state()
    md = agents.diagnosis_agent(state)
    assert "TODO(LLM)" in md                     # the case still gets an advisory card
    assert "rate limited" in state["diagnosis_error"]
