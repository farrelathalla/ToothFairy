"""Agents for the advisory graph.

**`diagnosis_agent` is real** (Phase 10): a RAG-grounded, ICD-10 Claude call. Recommendation
and sanity are still deterministic stubs (Phase 11).

Every agent is `(state) -> markdown`. The diagnosis agent dispatches on `claude.is_enabled()`:

    LLM_ENABLED=0 or no key  ->  _diagnosis_stub()   (pytest, E2E, offline demo)
    LLM_ENABLED=1 + key      ->  _diagnosis_llm()    (falls back to the stub on any error)

That fallback is deliberate: a network blip or a rate limit must degrade the advisory card,
never fail a case whose inference already succeeded.

    # TODO(LLM): recommendation + sanity agents (Phase 11) — same dispatch, `{treatment}` corpus.
"""
from __future__ import annotations

import logging

from . import claude, prompts

log = logging.getLogger(__name__)


def _grade_lines(detections: dict | None) -> list[str]:
    """Summarize affected teeth from a detections.json-shaped dict (best-effort)."""
    if not detections or not isinstance(detections.get("teeth"), dict):
        return []
    affected = [
        (int(t.get("fdi", 0)), int(t.get("severity", 0)))
        for t in detections["teeth"].values()
        if t.get("severity", 0) > 0
    ]
    affected.sort(key=lambda x: (-x[1], x[0]))
    return [f"- Gigi {fdi}: ICDAS D{grade}" for fdi, grade in affected]


def _anamnesa_lines(anamnesa: dict | None) -> list[str]:
    labels = {
        "lokasi": "Lokasi keluhan",
        "quality": "Kualitas nyeri",
        "severity": "Keparahan",
        "chronology": "Kronologi",
        "alasan_kuat": "Alasan kunjungan",
    }
    out = []
    for key, label in labels.items():
        val = (anamnesa or {}).get(key)
        if val:
            out.append(f"- **{label}:** {val}")
    return out


def _diagnosis_stub(state: dict) -> str:
    """Deterministic placeholder — the offline/disabled path. Keeps the `TODO(LLM)` marker."""
    name = state.get("patient_name") or "Pasien"
    grades = _grade_lines(state.get("detections"))
    anamnesa = _anamnesa_lines(state.get("anamnesa"))
    body = [
        "# Diagnosis (sementara)",
        "",
        f"Analisis awal untuk **{name}**:",
        "",
        "**Anamnesa:**",
        *(anamnesa or ["- (anamnesa belum lengkap)"]),
    ]
    if grades:
        body += ["", "**Temuan karies (dari deteksi):**", *grades]
    body += [
        "",
        "<!-- TODO(LLM): analisis keparahan & kondisi oleh agen diagnosis -->",
    ]
    return "\n".join(body) + "\n"


def _passages_as_documents(state: dict) -> list[dict]:
    """Retrieved chunks → Claude `document` blocks (raw chunk cited, blurb as `context`)."""
    return [
        {
            "doc_id": p.get("doc_id"),
            "title": p.get("title") or "",
            "ref": p.get("ref") or "",
            "context": p.get("context") or "",
            "text": p.get("text") or "",
        }
        for p in (state.get("rag") or [])
        if (p.get("text") or "").strip()
    ]


def _diagnosis_llm(state: dict) -> str:
    documents = _passages_as_documents(state)
    message = claude.answer_with_citations(
        prompts.build_system(), documents, prompts.build_user(state)
    )
    markdown, sources = claude.render_cited_markdown(message, documents)
    # Side channel for the evals (and any future UI that wants the raw citation objects).
    state["diagnosis_sources"] = sources
    state["diagnosis_usage"] = claude.usage_of(message)
    return markdown


def diagnosis_agent(state: dict) -> str:
    """ICD-10 diagnosis grounded in the retrieved passages (or the stub when disabled)."""
    if not claude.is_enabled():
        return _diagnosis_stub(state)
    try:
        return _diagnosis_llm(state)
    except Exception as exc:  # noqa: BLE001 — never fail a case over the advisory layer
        log.exception("diagnosis agent failed, falling back to stub: %s", exc)
        state["diagnosis_error"] = str(exc)
        return _diagnosis_stub(state)


def recommendation_agent(state: dict) -> str:
    """Treatment plan. # TODO(LLM) + # TODO(RAG) — Phase 11 retrieves over `{treatment}`."""
    grades = _grade_lines(state.get("detections"))
    prio = grades[0] if grades else "gigi dengan derajat tertinggi"
    body = [
        "# Rekomendasi Penanganan (sementara)",
        "",
        f"1. Prioritaskan penanganan {prio.replace('- ', '')}.",
        "2. Konsultasikan rencana perawatan dengan dokter gigi penanggung jawab.",
        "3. Edukasi kebersihan mulut & diet rendah gula untuk pasien anak.",
        "4. Jadwalkan kontrol ulang untuk memantau lesi awal (D1–D2).",
        "",
        "<!-- TODO(LLM): rencana perawatan oleh agen rekomendasi -->",
        "<!-- TODO(RAG): sitasi panduan penanganan karies profesional -->",
    ]
    return "\n".join(body) + "\n"


def sanity_agent(state: dict) -> tuple[str, bool]:
    """Validate/guard the two outputs. Returns (markdown, ok). # TODO(LLM).

    Deterministic stub: passes as long as both prior outputs exist.
    """
    ok = bool(state.get("diagnosis_md")) and bool(state.get("recommendation_md"))
    md = (
        "# Sanity check\n\n"
        + ("Tidak ada kontradiksi terdeteksi (placeholder)."
           if ok else "Output belum lengkap — perlu diulang.")
        + " <!-- TODO(LLM) -->\n"
    )
    return md, ok
