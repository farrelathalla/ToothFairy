"""Agents for the advisory graph.

Three agents, each `(state) -> markdown` (sanity also returns a pass/fail flag):

* **`diagnosis_agent`** — RAG-grounded ICD-10 diagnosis over the `{diagnosis, context}`
  corpus slice.
* **`recommendation_agent`** — RAG-grounded treatment plan over the `{treatment}` slice,
  anchored to the diagnosis the previous node produced.
* **`sanity_agent`** — a **deterministic** consistency checker (no model call, so it cannot
  hallucinate an approval). It returns the concrete defects it found; the graph feeds those
  back into one recommendation retry.

Both clinical agents dispatch on `openai_client.is_enabled()`:

    LLM_ENABLED=0 or no key  ->  the deterministic stub   (pytest, E2E, offline demo)
    LLM_ENABLED=1 + key      ->  the real call            (falls back to the stub on error)

That fallback is deliberate: a network blip, a rate limit or a truncated response must
degrade the advisory card, never fail a case whose image inference already succeeded.
"""
from __future__ import annotations

import logging
import re

from . import citations, icd10, openai_client, prompts, toothprofile

log = logging.getLogger(__name__)

# Phrases meaning "same as the row above" — the failure mode this pipeline is built to
# avoid. Checked by the sanity agent, forbidden by both system prompts.
_IDEM_RE = re.compile(
    r"(?:^|\|)\s*(idem|sda|s\.d\.a\.?|sama seperti di atas|sama dengan di atas|ditto)"
    r"\s*(?:\||$)",
    re.IGNORECASE | re.MULTILINE,
)
_ICD_RE = re.compile(r"\bK0\d(?:\.\d)?\b")


# ── shared helpers ───────────────────────────────────────────────────────────────

def _grade_lines(detections: dict | None) -> list[str]:
    """Summarize affected teeth from a detections.json-shaped dict (best-effort)."""
    return [
        f"- Gigi {r['fdi']} ({r['name']}): ICDAS D{r['grade']} — {r['extent']}"
        for r in toothprofile.profiles(detections)
    ]


def _anamnesa_lines(anamnesa: dict | None) -> list[str]:
    labels = {
        "lokasi": "Lokasi keluhan",
        "quality": "Kualitas nyeri",
        "severity": "Keparahan",
        "chronology": "Kronologi",
        "alasan_kuat": "Alasan kunjungan",
    }
    return [f"- **{label}:** {(anamnesa or {})[key]}"
            for key, label in labels.items() if (anamnesa or {}).get(key)]


def _passages_as_documents(state: dict, field: str = "rag") -> list[dict]:
    """Retrieved chunks → document blocks (the raw chunk is what gets cited)."""
    return [
        {
            "doc_id": p.get("doc_id"),
            "title": p.get("title") or "",
            "ref": p.get("ref") or "",
            "context": p.get("context") or "",
            "text": p.get("text") or "",
        }
        for p in (state.get(field) or [])
        if (p.get("text") or "").strip()
    ]


def _run_clinical(state: dict, *, system: str, user: str, documents: list[dict],
                  cache_key: str, prefix: str) -> str:
    """One clinical call + verified-citation rendering, recording usage on the state."""
    response = openai_client.answer_with_documents(
        system, documents, user, cache_key=cache_key
    )
    markdown, sources, stats = citations.parse_and_verify(
        openai_client.text_of(response), documents
    )
    # Side channel for the evals (and any future UI that wants the raw citation objects).
    state[f"{prefix}_sources"] = sources
    state[f"{prefix}_usage"] = openai_client.usage_of(response)
    state[f"{prefix}_citation_stats"] = stats
    return markdown


# ── diagnosis ────────────────────────────────────────────────────────────────────

def _diagnosis_stub(state: dict) -> str:
    """Deterministic placeholder — the offline/disabled path."""
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
        "_Analisis diagnostik lengkap dihasilkan ketika layer LLM diaktifkan "
        "(`LLM_ENABLED=1`)._",
    ]
    return "\n".join(body) + "\n"


def diagnosis_agent(state: dict) -> str:
    """ICD-10 diagnosis grounded in the retrieved passages (or the stub when disabled)."""
    if not openai_client.is_enabled():
        return _diagnosis_stub(state)
    try:
        return _run_clinical(
            state,
            system=prompts.diagnosis.build_system(),
            user=prompts.diagnosis.build_user(state),
            documents=_passages_as_documents(state, "rag"),
            cache_key="toothfairy-diagnosis",
            prefix="diagnosis",
        )
    except Exception as exc:  # noqa: BLE001 — never fail a case over the advisory layer
        log.exception("diagnosis agent failed, falling back to stub: %s", exc)
        state["diagnosis_error"] = str(exc)
        return _diagnosis_stub(state)


# ── recommendation ───────────────────────────────────────────────────────────────

_STUB_ACTION = {
    1: "pemantauan + aplikasi fluoride topikal",
    2: "pemantauan + aplikasi fluoride topikal",
    3: "restorasi minimal invasif",
    4: "restorasi definitif",
    5: "restorasi definitif + evaluasi vitalitas pulpa",
    6: "evaluasi vitalitas pulpa; perawatan pulpa atau ekstraksi sesuai temuan klinis",
}


def _recommendation_stub(state: dict) -> str:
    """Deterministic placeholder — the offline/disabled path."""
    rows = toothprofile.profiles(state.get("detections"))
    body = ["# Rekomendasi Penanganan (sementara)", ""]
    if rows:
        body += [
            "| Gigi | Nama gigi | ICDAS | Tindakan yang diusulkan |",
            "| --- | --- | --- | --- |",
            *(f"| {r['fdi']} | {r['name']} | D{r['grade']} | "
              f"{_STUB_ACTION.get(r['grade'], 'evaluasi klinis')} |" for r in rows),
            "",
        ]
    body += [
        "1. Prioritaskan gigi dengan derajat terberat pada kunjungan pertama.",
        "2. Konsultasikan rencana perawatan dengan dokter gigi penanggung jawab.",
        "3. Edukasi kebersihan mulut & diet rendah gula untuk pasien anak.",
        "4. Jadwalkan kontrol ulang untuk memantau lesi awal (D1–D2).",
        "",
        "_Rencana perawatan lengkap dihasilkan ketika layer LLM diaktifkan "
        "(`LLM_ENABLED=1`)._",
    ]
    return "\n".join(body) + "\n"


def recommendation_agent(state: dict) -> str:
    """Treatment plan grounded in the treatment-guideline passages (or the stub)."""
    if not openai_client.is_enabled():
        return _recommendation_stub(state)
    try:
        return _run_clinical(
            state,
            system=prompts.recommendation.build_system(),
            user=prompts.recommendation.build_user(state),
            documents=_passages_as_documents(state, "rag_treatment"),
            cache_key="toothfairy-recommendation",
            prefix="recommendation",
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("recommendation agent failed, falling back to stub: %s", exc)
        state["recommendation_error"] = str(exc)
        return _recommendation_stub(state)


# ── sanity check (deterministic) ─────────────────────────────────────────────────

def _teeth_mentioned(markdown: str) -> set[int]:
    """FDI numbers named anywhere in the text (table cells or prose)."""
    return {int(n) for n in re.findall(r"\b([1-8][1-8])\b", markdown or "")}


def _check(state: dict) -> tuple[list[str], list[str]]:
    """→ (defects the recommendation retry can fix, defects only worth reporting)."""
    diagnosis = state.get("diagnosis_md") or ""
    plan = state.get("recommendation_md") or ""
    rows = toothprofile.profiles(state.get("detections"))
    affected = {r["fdi"] for r in rows}
    deep = {r["fdi"] for r in rows if r["grade"] >= 5}

    fixable: list[str] = []
    reported: list[str] = []

    if not diagnosis.strip():
        reported.append("Diagnosis kosong.")
    if not plan.strip():
        fixable.append("Rencana perawatan kosong.")

    # Every affected tooth must be planned for, and must appear in the diagnosis.
    missing_plan = sorted(affected - _teeth_mentioned(plan))
    if missing_plan:
        fixable.append("Gigi terdampak belum muncul pada rencana perawatan: "
                       + ", ".join(str(f) for f in missing_plan) + ".")
    missing_dx = sorted(affected - _teeth_mentioned(diagnosis))
    if missing_dx:
        reported.append("Gigi terdampak belum muncul pada diagnosis: "
                        + ", ".join(str(f) for f in missing_dx) + ".")

    # No treatment for a tooth both detectors call absent.
    planned_missing = sorted(set(icd10.missing_fdi(state.get("detections")))
                             & _teeth_mentioned(plan))
    if planned_missing:
        fixable.append("Rencana menyebut gigi yang sudah hilang (ompong): "
                       + ", ".join(str(f) for f in planned_missing) + ".")

    # Only codes from the sanctioned table.
    unknown = sorted({c for c in _ICD_RE.findall(diagnosis) if c not in icd10.ICD10})
    if unknown:
        reported.append("Kode ICD-10 di luar tabel: " + ", ".join(unknown) + ".")

    # K04.x (pulp/periapical) is only defensible once a lesion is deep.
    if "K04" in diagnosis and not deep:
        reported.append(
            "Kode K04.x dipakai padahal tidak ada lesi D5-D6; perlu konfirmasi klinis."
        )

    # The failure mode this pipeline exists to prevent.
    for label, text, bucket in (("diagnosis", diagnosis, reported),
                                ("rencana perawatan", plan, fixable)):
        if _IDEM_RE.search(text):
            bucket.append(f"Ditemukan jawaban berulang ('idem'/'sda') pada {label}; "
                          "setiap gigi harus diuraikan spesifik.")

    return fixable, reported


def sanity_agent(state: dict) -> tuple[str, bool]:
    """Deterministic cross-check of the two clinical outputs → (markdown, ok).

    No model call: the guard on a clinical output must not itself be able to hallucinate an
    approval. `state["sanity_feedback"]` carries the fixable defects into the retry.
    """
    fixable, reported = _check(state)
    state["sanity_feedback"] = fixable
    ok = not fixable and not reported

    lines = ["# Pemeriksaan Konsistensi", ""]
    if ok:
        lines += [
            "Tidak ada kontradiksi terdeteksi:",
            "",
            "- Semua gigi terdampak tercakup pada diagnosis dan rencana perawatan.",
            "- Seluruh kode ICD-10 berasal dari tabel resmi.",
            "- Tidak ada jawaban berulang antar gigi.",
        ]
    else:
        lines += ["Temuan yang perlu diperhatikan:", ""]
        lines += [f"- {item}" for item in (*fixable, *reported)]

    stats = state.get("diagnosis_citation_stats") or {}
    if stats.get("claimed"):
        rejected = stats.get("rejected") or 0
        lines += [
            "",
            f"Sitasi diagnosis: {stats.get('verified', 0)} dari {stats['claimed']} kutipan "
            "terverifikasi verbatim terhadap dokumen sumber"
            + (f"; {rejected} dibuang." if rejected else "."),
        ]

    return "\n".join(lines) + "\n", ok
