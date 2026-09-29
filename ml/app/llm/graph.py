"""Advisory graph.

    rag(diagnosis slice) → diagnosis → rag(treatment slice) → recommendation → sanity
                                              ▲                    │
                                              └──── (loop once) ───┘   (if sanity fails)

Typed state flows through the nodes; each node fills one field.

**Two retrievals, not one.** The diagnosis agent needs symptom/severity/epidemiology
evidence; the recommendation agent needs treatment guidelines. Retrieving once and sharing
the passages would let one agent's evidence crowd out the other's in a small top-N, so each
gets its own query against its own corpus slice.

**The sanity node is deterministic** (`agents.sanity_agent`) and its findings are fed back
into a single recommendation retry via `state["sanity_feedback"]`, so the retry is told what
to fix rather than merely asked to try again.

`run(case)` is the stable entry used by `jobs` + `seed`.
"""
from __future__ import annotations

from typing import Any, TypedDict

from ..config import settings
from . import agents, icd10, rag

MAX_SANITY_LOOPS = 1
MAX_QUERY_CHARS = 1200


class GraphState(TypedDict, total=False):
    # inputs
    patient_name: str | None
    anamnesa: dict
    detections: dict | None
    # working / outputs
    rag: list[dict]                 # passages for the diagnosis agent
    rag_query: str
    rag_treatment: list[dict]       # passages for the recommendation agent
    rag_treatment_query: str
    diagnosis_md: str
    recommendation_md: str
    sanity_md: str
    sanity_ok: bool
    sanity_feedback: list[str]
    _sanity_loops: int


# ── query construction ───────────────────────────────────────────────────────────

# The anamnesa fields that carry retrieval signal. `alasan_kuat` / `pernah_ke_drg_lain` are
# administrative and mostly add noise to a dense query, so they're left out.
_QUERY_ANAMNESA_KEYS = (
    "lokasi", "quality", "severity", "setting",
    "aggravating_alleviating", "associated", "penyakit_sistemik",
)


def build_rag_query(state: GraphState) -> str:
    """A retrieval query from the detections + anamnesa.

    Anamnesa alone retrieves poorly — it never names ICDAS, PUFA, or "untreated caries", which
    is exactly the vocabulary the corpus uses. So the query is *composed*: the lesion picture
    (grades, count, dentition, hidden lesions) supplies the clinical terms, the anamnesa
    supplies the patient's own words, and a fixed tail names the outcome constructs the
    diagnosis section is expected to reason about (daily activities, PUFA, ECOHIS, risk
    factors). BGE-M3 is multilingual, so mixing Indonesian and English terms is fine.
    """
    parts: list[str] = []
    rows = icd10.map_detections(state.get("detections"))

    if rows:
        grades = sorted({r["grade"] for r in rows}, reverse=True)
        parts.append(
            "Karies gigi tidak terawat pada anak, derajat ICDAS "
            + ", ".join(f"D{g}" for g in grades)
            + f", {len(rows)} gigi terdampak"
        )
        if any(r["grade"] >= 5 for r in rows):
            parts.append(
                "lesi dalam mencapai dentin dan mendekati pulpa, risiko pulpa terekspos, "
                "indeks PUFA/pufa, ulserasi, fistula, abses periapikal"
            )
        if any(r["hidden"] for r in rows):
            parts.append("lesi karies tersembunyi terlihat sebagai radiolusensi pada panoramik")
        deciduous = any(51 <= r["fdi"] <= 85 for r in rows)
        parts.append(
            "patogenesis gigi desidui, email tipis, progresi cepat"
            if deciduous
            else "gigi permanen muda"
        )
    else:
        parts.append("skrining karies anak, tidak ada lesi terdeteksi pada citra")

    parts.append(
        "dampak karies tidak terawat pada aktivitas harian anak: kesulitan makan dan "
        "mengunyah, gangguan tidur, nyeri, kualitas hidup ECOHIS"
    )
    parts.append(
        "faktor risiko konsumsi makanan kariogenik dan kebiasaan menyikat gigi, "
        "prevalensi karies anak di Indonesia"
    )

    anamnesa = state.get("anamnesa") or {}
    said = [str(anamnesa[k]).strip() for k in _QUERY_ANAMNESA_KEYS if anamnesa.get(k)]
    if said:
        parts.append("Keluhan pasien: " + "; ".join(said))

    return ". ".join(parts)[:MAX_QUERY_CHARS]


def build_treatment_query(state: GraphState) -> str:
    """A retrieval query for the *treatment* corpus slice.

    Deliberately different vocabulary from `build_rag_query`: guidelines are indexed under
    the names of procedures and materials, not under symptoms. The lesion depth mix decides
    which procedures are even relevant, so the query names them explicitly instead of
    re-describing the complaint.
    """
    rows = icd10.map_detections(state.get("detections"))
    parts: list[str] = ["Tata laksana dan rencana perawatan karies gigi anak"]

    if not rows:
        parts.append(
            "pencegahan karies anak, aplikasi fluoride topikal, fissure sealant, "
            "instruksi kebersihan mulut, kontrol diet"
        )
    else:
        grades = {r["grade"] for r in rows}
        if grades & {1, 2}:
            parts.append(
                "lesi email non-kavitasi, remineralisasi, fluoride varnish, "
                "silver diamine fluoride SDF, fissure sealant, karies terhenti"
            )
        if grades & {3, 4}:
            parts.append(
                "restorasi gigi anak, preparasi minimal invasif, glass ionomer cement, "
                "atraumatic restorative treatment ART, resin komposit, Hall technique"
            )
        if grades & {5, 6}:
            parts.append(
                "karies dentin dalam, pulpotomi, pulpektomi, perawatan pulpa gigi sulung, "
                "stainless steel crown, indikasi ekstraksi, space maintainer"
            )
        if any(r["hidden"] for r in rows):
            parts.append("lesi proksimal terdeteksi radiografis, indikasi restorasi")
        if any(51 <= r["fdi"] <= 85 for r in rows):
            parts.append("perawatan gigi sulung, manajemen perilaku anak")
        parts.append(f"{len(rows)} gigi terdampak, prioritas dan urutan kunjungan")

    parts.append(
        "edukasi orang tua, kontrol berkala, rujukan spesialis kedokteran gigi anak"
    )

    anamnesa = state.get("anamnesa") or {}
    if anamnesa.get("penyakit_sistemik"):
        parts.append(f"pertimbangan penyakit sistemik: {anamnesa['penyakit_sistemik']}")
    return ". ".join(parts)[:MAX_QUERY_CHARS]


# ── nodes ────────────────────────────────────────────────────────────────────────

def _node_rag(state: GraphState) -> GraphState:
    query = build_rag_query(state)
    state["rag_query"] = query
    state["rag"] = rag.retrieve(
        query, k=settings.rag_top_n, categories=rag.DIAGNOSIS_CATEGORIES
    )
    return state


def _node_rag_treatment(state: GraphState) -> GraphState:
    query = build_treatment_query(state)
    state["rag_treatment_query"] = query
    state["rag_treatment"] = rag.retrieve(
        query, k=settings.rag_top_n, categories=rag.TREATMENT_CATEGORIES
    )
    return state


def _node_diagnosis(state: GraphState) -> GraphState:
    state["diagnosis_md"] = agents.diagnosis_agent(state)
    return state


def _node_recommendation(state: GraphState) -> GraphState:
    state["recommendation_md"] = agents.recommendation_agent(state)
    return state


def _node_sanity(state: GraphState) -> GraphState:
    md, ok = agents.sanity_agent(state)
    state["sanity_md"] = md
    state["sanity_ok"] = ok
    return state


def run_graph(state: GraphState) -> GraphState:
    """Thread the state through the nodes, honoring the sanity loop-once edge."""
    state.setdefault("_sanity_loops", 0)
    state = _node_rag(state)
    state = _node_diagnosis(state)
    state = _node_rag_treatment(state)
    state = _node_recommendation(state)
    state = _node_sanity(state)
    # sanity_check may loop back to recommendation ONCE if it flags a problem
    while not state.get("sanity_ok") and state["_sanity_loops"] < MAX_SANITY_LOOPS:
        state["_sanity_loops"] += 1
        state = _node_recommendation(state)
        state = _node_sanity(state)
    return state


def run_state(case: Any) -> GraphState:
    """Run the graph for a case and return the **whole** state.

    Accepts anything with `.patient_name` and `.anamnesa`. `.detections` is optional — the
    advisory service attaches the freshly written `detections.json` before calling; without
    it the agents fall back to anamnesa-only reasoning. The full state carries the retrieval,
    usage and citation-verification telemetry the caller reports.
    """
    state: GraphState = {
        "patient_name": getattr(case, "patient_name", None),
        "anamnesa": getattr(case, "anamnesa", None) or {},
        "detections": getattr(case, "detections", None),
    }
    return run_graph(state)


def run(case: Any) -> dict:
    """Public entry: run the advisory graph for a case, return the markdown fields."""
    out = run_state(case)
    return {
        "diagnosis_md": out["diagnosis_md"],
        "recommendation_md": out["recommendation_md"],
        "sanity_md": out["sanity_md"],
    }
