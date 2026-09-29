"""Per-tooth clinical descriptors derived from `detections.json`. Pure data, no LLM, no I/O.

**Why this module exists.** The detector already knows far more about each tooth than its
ICDAS grade: how much of the crown the lesion covers, how dark it is relative to sound
enamel across the arch, how many separate lesions there are and whether they are cavitated
or cracked, where in the crown they sit, whether the panoramic corroborates the photo, and
how strong the evidence is. Feeding the agent only `(fdi, grade)` gave every tooth of the
same grade an identical justification — the model, correctly, wrote "Idem" down the table.

So each tooth is turned into a **distinct, quantitative profile** first. Two teeth that are
both D6 differ in extent, discolouration, lesion count and evidence strength, so the agent
now has something specific to say about each one, and the "damage pattern" it reports is
traceable to numbers a dentist can check rather than to prose the model invented.

Everything here is derived from fields the pipeline already writes, and every band is a
documented cut-off, so the descriptors are reproducible and unit-testable.
"""
from __future__ import annotations

import math
from typing import Any

# ── FDI → anatomy ────────────────────────────────────────────────────────────────

QUADRANT_NAME: dict[int, str] = {
    1: "rahang atas kanan", 2: "rahang atas kiri",
    3: "rahang bawah kiri", 4: "rahang bawah kanan",
    5: "rahang atas kanan (sulung)", 6: "rahang atas kiri (sulung)",
    7: "rahang bawah kiri (sulung)", 8: "rahang bawah kanan (sulung)",
}

_PERMANENT_POSITION: dict[int, str] = {
    1: "insisivus sentral", 2: "insisivus lateral", 3: "kaninus",
    4: "premolar satu", 5: "premolar dua",
    6: "molar satu", 7: "molar dua", 8: "molar tiga",
}

_DECIDUOUS_POSITION: dict[int, str] = {
    1: "insisivus sentral sulung", 2: "insisivus lateral sulung", 3: "kaninus sulung",
    4: "molar satu sulung", 5: "molar dua sulung",
}


def is_deciduous(fdi: int) -> bool:
    return 5 <= (int(fdi) // 10) <= 8


def tooth_name(fdi: int) -> str:
    """`24` → "premolar satu rahang atas kiri"."""
    fdi = int(fdi)
    quadrant, position = fdi // 10, fdi % 10
    table = _DECIDUOUS_POSITION if is_deciduous(fdi) else _PERMANENT_POSITION
    base = table.get(position, f"gigi posisi {position}")
    return f"{base} {QUADRANT_NAME.get(quadrant, '')}".strip()


def is_anterior(fdi: int) -> bool:
    return (int(fdi) % 10) <= 3


# ── banded descriptors (documented cut-offs) ─────────────────────────────────────

def extent_band(caries_ratio: float) -> str:
    """Share of the tooth's own crown area covered by caries masks."""
    r = float(caries_ratio or 0.0)
    if r <= 0:
        return "luas lesi tidak terukur dari citra"
    if r < 0.05:
        return "lesi terlokalisir (<5% permukaan mahkota)"
    if r < 0.15:
        return "lesi sedang (5–15% permukaan mahkota)"
    if r < 0.30:
        return "lesi luas (15–30% permukaan mahkota)"
    return "destruksi mahkota ekstensif (>30% permukaan mahkota)"


def discoloration_band(rel_dark: float) -> str:
    """Lesion darkness relative to sound enamel across the whole arch (exposure-invariant)."""
    d = float(rel_dark or 0.0)
    if d <= 0:
        return "tanpa data warna"
    if d < 0.20:
        return "diskolorasi ringan, warna mendekati email sehat (kesan bercak kapur)"
    if d < 0.45:
        return "diskolorasi cokelat muda"
    if d < 0.70:
        return "diskolorasi cokelat gelap"
    return "diskolorasi sangat gelap/kehitaman, kesan jaringan nekrotik"


def _site(u: float, v: float) -> str:
    """Where in the crown box the lesion centroid sits (radial, view-agnostic)."""
    d = math.hypot(float(u) - 0.5, float(v) - 0.5) / 0.7071
    if d < 0.25:
        return "sentral"
    if d < 0.55:
        return "pertengahan mahkota"
    return "tepi mahkota"


def lesion_pattern(lesions: list[dict] | None) -> str:
    """Count, kind and spread of the individual lesions on one tooth."""
    lesions = [l for l in (lesions or []) if isinstance(l, dict)]
    if not lesions:
        return "tidak ada lesi terpisah yang terpetakan pada citra"

    kinds: dict[str, int] = {}
    for l in lesions:
        label = {"Cavity": "kavitasi terbuka", "Crack": "retak/fraktur email",
                 "Caries": "lesi karies"}.get(str(l.get("type") or "Caries"), "lesi karies")
        kinds[label] = kinds.get(label, 0) + 1
    kind_text = ", ".join(f"{n}× {k}" for k, n in sorted(kinds.items(), key=lambda x: -x[1]))

    sites = sorted({_site(l.get("u", 0.5), l.get("v", 0.5)) for l in lesions})
    biggest = max((float(l.get("r") or 0.0) for l in lesions), default=0.0)

    if len(lesions) == 1:
        spread = f"fokus tunggal di {sites[0]}"
    else:
        spread = (
            f"{len(lesions)} fokus yang menyatu di {sites[0]}"
            if len(sites) == 1
            else f"{len(lesions)} fokus tersebar ({', '.join(sites)})"
        )
    size = (f"; fokus terbesar mencakup ±{round(biggest * 100)}% lebar mahkota"
            if biggest > 0 else "")
    return f"{kind_text}; {spread}{size}"


def confidence(tooth: dict[str, Any]) -> tuple[str, str]:
    """Evidence strength for this tooth → (Tinggi|Sedang|Rendah, short reason).

    Scored from *which detectors agreed*, their confidence, whether the tooth's FDI box had
    to be interpolated, and whether the panoramic corroborates. This is what the agent's
    "Keyakinan" column reports, so a tooth carried by one weak detector is never presented
    with the same certainty as one three detectors agree on.
    """
    sources = [str(s) for s in (tooth.get("sources") or [])]
    lesions = tooth.get("lesions") or []
    confs = [float(l.get("conf") or 0.0) for l in lesions if isinstance(l, dict)]
    mean_conf = sum(confs) / len(confs) if confs else 0.0

    score, why = 0, []
    if "rfdetr" in sources:
        score += 2
        why.append("grader ICDAS")
    if "seg" in sources:
        score += 1
        why.append("segmentasi lesi")
    if float(tooth.get("pano_grade") or 0) > 0:
        score += 1
        why.append("korroborasi panoramik")
    if tooth.get("fdi_predicted"):
        score -= 1
        why.append("kotak FDI hasil interpolasi")
    if mean_conf >= 0.40:
        score += 1
    elif 0 < mean_conf < 0.20:
        score -= 1
        why.append("skor deteksi rendah")

    tier = "Tinggi" if score >= 3 else "Sedang" if score >= 1 else "Rendah"
    return tier, ", ".join(why) or "bukti tunggal"


def radiographic_note(tooth: dict[str, Any]) -> str:
    ratio = float(tooth.get("pano_ratio") or 0.0)
    grade = int(tooth.get("pano_grade") or 0)
    if tooth.get("hidden"):
        return (f"radiolusensi panoramik setara D{grade} "
                f"(±{ratio * 100:.1f}% area gigi) di bawah email yang utuh")
    if grade > 0:
        return f"panoramik mengonfirmasi lesi setara D{grade} (±{ratio * 100:.1f}% area gigi)"
    return "tidak ada temuan panoramik terpisah"


# ── assembly ─────────────────────────────────────────────────────────────────────

def profile(tooth: dict[str, Any]) -> dict[str, Any]:
    """One affected tooth → the full descriptor set."""
    fdi = int(tooth.get("fdi", 0))
    grade = int(tooth.get("severity", 0) or 0)
    tier, reason = confidence(tooth)
    return {
        "fdi": fdi,
        "name": tooth_name(fdi),
        "grade": grade,
        "deciduous": is_deciduous(fdi),
        "anterior": is_anterior(fdi),
        "hidden": bool(tooth.get("hidden")),
        "extent": extent_band(tooth.get("caries_ratio")),
        "caries_ratio": round(float(tooth.get("caries_ratio") or 0.0), 3),
        "discoloration": discoloration_band(tooth.get("rel_dark")),
        "rel_dark": round(float(tooth.get("rel_dark") or 0.0), 2),
        "pattern": lesion_pattern(tooth.get("lesions")),
        "n_lesions": len(tooth.get("lesions") or []),
        "radiographic": radiographic_note(tooth),
        "confidence": tier,
        "confidence_reason": reason,
        "grade_source": tooth.get("grade_source") or "—",
    }


def profiles(detections: dict | None) -> list[dict[str, Any]]:
    """Every affected tooth, worst grade first."""
    teeth = (detections or {}).get("teeth")
    if not isinstance(teeth, dict):
        return []
    rows = [profile(t) for t in teeth.values() if int(t.get("severity", 0) or 0) > 0]
    rows.sort(key=lambda r: (-r["grade"], r["fdi"]))
    return rows


def render_profiles(rows: list[dict[str, Any]]) -> str:
    """Per-tooth evidence blocks for the prompt.

    Deliberately **not** a table: one block per tooth, each carrying that tooth's own
    numbers, is what makes a per-tooth answer the path of least resistance for the model.
    """
    if not rows:
        return "Tidak ada gigi terdampak pada citra yang diunggah."
    out: list[str] = []
    for r in rows:
        out.append(
            f"### Gigi {r['fdi']} — {r['name']}\n"
            f"- ICDAS: **D{r['grade']}** (sumber grade: {r['grade_source']})\n"
            f"- Luas: {r['extent']} (rasio karies {r['caries_ratio']})\n"
            f"- Warna: {r['discoloration']} (kegelapan relatif {r['rel_dark']})\n"
            f"- Pola lesi: {r['pattern']}\n"
            f"- Radiografis: {r['radiographic']}\n"
            f"- Kekuatan bukti: {r['confidence']} ({r['confidence_reason']})"
        )
    return "\n\n".join(out)
