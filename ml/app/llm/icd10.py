"""ICD-10 reference table + ICDAS→ICD-10 mapping heuristic.

Pure data + pure functions — no LLM, no I/O. Two consumers:

1. `render_table()` goes into the diagnosis agent's **cached system prompt** so Claude
   answers against the exact code set the dentist supplied (K02.x caries by tissue depth,
   K03.x other hard-tissue disease, K04.x pulp & periapical).
2. `map_detections()` turns `detections.json` into a per-tooth *prior*: a suggested primary
   code plus a differential. It is a starting point the agent may override with clinical
   reasoning — never the final answer. Keeping it pure means the mapping is unit-testable
   without a key.

Depth mapping (ICDAS → tissue): D1–D2 are non-cavitated enamel lesions (white/brown spot,
localized enamel breakdown) → **K02.0**. D3–D6 have reached dentine → **K02.1**. Pulp
involvement is *possible* from D5 and *likely* at D6, so those carry a K04.x differential
rather than a hard code — only the clinician (or a periapical finding) can confirm pulpitis
vs necrosis. Panoramic-only (`hidden`) lesions are radiographic dentine caries: the surface
is intact, so K02.0 is not appropriate even at low grades.
"""
from __future__ import annotations

from typing import Any, Iterable

# code -> (English determination, Indonesian gloss)
ICD10_CARIES: dict[str, tuple[str, str]] = {
    "K02.0": ("Caries limited to enamel; white spot lesions (initial caries)",
              "Karies terbatas pada email; lesi bercak putih (karies inisial)"),
    "K02.1": ("Caries of dentine", "Karies dentin"),
    "K02.2": ("Caries of cementum", "Karies sementum"),
    "K02.3": ("Arrested dental caries", "Karies terhenti (arrested)"),
    "K02.4": ("Odontoclasia; infantile melanodontia; melanodontoclasia",
              "Odontoklasia; melanodontia infantil; melanodontoklasia"),
    "K02.8": ("Other dental caries", "Karies gigi lainnya"),
    "K02.9": ("Dental caries, unspecified", "Karies gigi, tidak spesifik"),
}

ICD10_HARD_TISSUE: dict[str, tuple[str, str]] = {
    "K03": ("Other diseases of hard tissues of teeth", "Penyakit jaringan keras gigi lainnya"),
    "K03.0": ("Excessive attrition of teeth (approximal/occlusal wear)",
              "Atrisi berlebihan (keausan aproksimal/oklusal)"),
    "K03.1": ("Abrasion of teeth (dentifrice, habitual, occupational, ritual, traditional)",
              "Abrasi gigi (pasta gigi, kebiasaan, pekerjaan, ritual, tradisional)"),
    "K03.2": ("Erosion of teeth", "Erosi gigi"),
}

ICD10_PULP: dict[str, tuple[str, str]] = {
    "K04": ("Diseases of pulp and periapical tissues", "Penyakit pulpa dan jaringan periapikal"),
    "K04.0": ("Pulpitis: NOS, acute, chronic (hyperplastic/ulcerative), irreversible, reversible",
              "Pulpitis: NOS, akut, kronis (hiperplastik/ulseratif), ireversibel, reversibel"),
    "K04.1": ("Necrosis of pulp; pulpal gangrene", "Nekrosis pulpa; gangren pulpa"),
    "K04.2": ("Pulp degeneration; denticles; pulpal calcifications; pulp stones",
              "Degenerasi pulpa; dentikel; kalsifikasi pulpa; batu pulpa"),
    "K04.3": ("Abnormal hard tissue formation in pulp; secondary or irregular dentine",
              "Pembentukan jaringan keras abnormal dalam pulpa; dentin sekunder/ireguler"),
    "K04.4": ("Acute apical periodontitis of pulpal origin; acute apical periodontitis NOS",
              "Periodontitis apikalis akut asal pulpa"),
    "K04.5": ("Chronic apical periodontitis; apical/periapical granuloma",
              "Periodontitis apikalis kronis; granuloma periapikal"),
    "K04.6": ("Periapical abscess with sinus; dental/dentoalveolar abscess with sinus",
              "Abses periapikal dengan sinus (fistula)"),
    "K04.7": ("Periapical abscess without sinus; dental/dentoalveolar/periapical abscess NOS",
              "Abses periapikal tanpa sinus"),
}

ICD10: dict[str, tuple[str, str]] = {**ICD10_CARIES, **ICD10_HARD_TISSUE, **ICD10_PULP}

# ICDAS grade → primary code by lesion depth.
_PRIMARY_BY_GRADE: dict[int, str | None] = {
    0: None,
    1: "K02.0", 2: "K02.0",          # non-cavitated enamel
    3: "K02.1", 4: "K02.1",          # into dentine
    5: "K02.1", 6: "K02.1",          # deep dentine, pulp at risk
}

# Codes the agent must *consider* (not assume) once the lesion is deep.
_DIFFERENTIAL_BY_GRADE: dict[int, list[str]] = {
    5: ["K04.0"],
    6: ["K04.0", "K04.1", "K04.4", "K04.7"],
}

_RATIONALE_ID: dict[int, str] = {
    1: "lesi email non-kavitasi (bercak putih/cokelat)",
    2: "kerusakan email terlokalisir, belum mencapai dentin",
    3: "kavitas email dengan bayangan dentin di bawahnya",
    4: "bayangan dentin gelap, dentin terlibat",
    5: "kavitas jelas dengan dentin terekspos; pulpa berisiko",
    6: "kavitas luas menembus dentin; keterlibatan pulpa sangat mungkin",
}


def render_table() -> str:
    """The full code table as markdown — goes into the cached system prompt."""
    lines = ["| Kode | Determination (EN) | Keterangan (ID) |", "| --- | --- | --- |"]
    for code, (en, idn) in ICD10.items():
        lines.append(f"| **{code}** | {en} | {idn} |")
    return "\n".join(lines)


def map_grade(grade: int, *, hidden: bool = False) -> dict[str, Any]:
    """Suggested ICD-10 prior for one ICDAS grade.

    `hidden` marks a panoramic-only (radiolucent) lesion: the enamel surface is intact but
    the radiolucency sits in dentine, so an enamel-only code is never right.
    """
    grade = max(0, min(6, int(grade)))
    if grade == 0:
        return {"primary": None, "differential": [], "rationale": "tidak ada lesi terdeteksi"}

    primary = _PRIMARY_BY_GRADE[grade]
    rationale = _RATIONALE_ID[grade]
    if hidden and primary == "K02.0":
        primary = "K02.1"
        rationale = "radiolusensi pada dentin (temuan panoramik), permukaan email utuh"

    return {
        "primary": primary,
        "differential": list(_DIFFERENTIAL_BY_GRADE.get(grade, [])),
        "rationale": rationale,
    }


def map_detections(detections: dict | None) -> list[dict[str, Any]]:
    """Per-affected-tooth priors, worst grade first. Returns [] when nothing is affected."""
    teeth = (detections or {}).get("teeth")
    if not isinstance(teeth, dict):
        return []

    rows: list[dict[str, Any]] = []
    for tooth in teeth.values():
        grade = int(tooth.get("severity", 0) or 0)
        if grade <= 0:
            continue
        hidden = bool(tooth.get("hidden"))
        row = map_grade(grade, hidden=hidden)
        row.update(
            fdi=int(tooth.get("fdi", 0)),
            grade=grade,
            hidden=hidden,
            source=tooth.get("grade_source") or "",
        )
        rows.append(row)
    rows.sort(key=lambda r: (-r["grade"], r["fdi"]))
    return rows


def missing_fdi(detections: dict | None) -> list[int]:
    """FDI numbers both detectors agree are absent (gigi ompong)."""
    meta = (detections or {}).get("meta") or {}
    return sorted(int(f) for f in meta.get("missing_fdi", []))


def describe(codes: Iterable[str]) -> list[str]:
    """`["K02.1"] -> ["K02.1 — Karies dentin"]` (unknown codes pass through)."""
    out = []
    for c in codes:
        gloss = ICD10.get(c)
        out.append(f"{c} — {gloss[1]}" if gloss else c)
    return out
