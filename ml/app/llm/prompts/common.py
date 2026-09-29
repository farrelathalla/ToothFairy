"""Prompt fragments shared by the diagnosis and recommendation agents.

Split out so the two agents describe the same patient with the same words, and so the
exact wording is reviewable (and testable) on its own.
"""
from __future__ import annotations

from typing import Any

from .. import icd10, toothprofile

ANAMNESA_LABELS: list[tuple[str, str]] = [
    ("lokasi", "Lokasi keluhan / penjalaran"),
    ("quality", "Kualitas nyeri"),
    ("severity", "Keparahan (skala & dampak)"),
    ("chronology", "Kronologi"),
    ("setting", "Kondisi saat nyeri muncul"),
    ("aggravating_alleviating", "Memperparah / meredakan"),
    ("associated", "Gejala penyerta"),
    ("pernah_ke_drg_lain", "Pernah ke drg lain"),
    ("obat_digunakan", "Obat yang digunakan"),
    ("tindakan_sebelumnya", "Tindakan drg sebelumnya"),
    ("penyakit_sistemik", "Penyakit sistemik"),
    ("pernah_menunda", "Pernah menunda kunjungan"),
    ("alasan_kuat", "Alasan kuat datang"),
]

# Rules both clinical agents obey. Kept here so the two system prompts cannot drift apart.
SAFETY_RULES = """- **Jangan mengarang isi dokumen.** Sitasi hanya bila kalimat Anda benar-benar didukung
  kutipan yang dilampirkan. Jangan menyebut angka, prevalensi, dosis, atau nama studi yang
  tidak ada pada kutipan tersebut.
- **Abstain lebih baik daripada menebak.** Bila data tidak cukup, nyatakan itu secara
  eksplisit dan turunkan tingkat keyakinan; jangan mengisi kekosongan dengan asumsi.
- **Detektor AI punya batas recall.** Gigi yang tidak terlihat pada foto yang diunggah
  dianggap sehat kecuali dikonfirmasi panoramik; pit & fisur yang tertutup debris, lesi
  proksimal, dan lesi di bawah restorasi dapat luput. Nyatakan ini pada bagian batasan.
- **Keputusan akhir ada pada dokter gigi.** Tulis sebagai masukan untuk klinisi, bukan
  sebagai instruksi kepada pasien, dan jangan menjanjikan hasil."""

NO_IDEM_RULE = """- **Setiap gigi dianalisis sendiri-sendiri.** DILARANG menulis "Idem", "sda",
  "sama seperti di atas", "—", tanda kutip berulang, atau kalimat yang identik dengan baris
  lain. Bila dua gigi memang serupa, tetap bedakan dengan menyebut angka spesifik gigi itu
  (luas lesi, kegelapan relatif, jumlah dan letak fokus, temuan radiografis). Data per gigi
  sudah disediakan di bawah — gunakan angka tersebut, jangan mengarang angka baru."""


def anamnesa_block(anamnesa: dict | None) -> str:
    rows = [f"- **{label}:** {anamnesa[key]}"
            for key, label in ANAMNESA_LABELS
            if (anamnesa or {}).get(key)]
    return "\n".join(rows) if rows else "- (anamnesa tidak tersedia)"


def prior_table(detections: dict | None) -> str:
    """Compact ICDAS→ICD-10 prior per affected tooth (a starting point, not the answer)."""
    rows = icd10.map_detections(detections)
    if not rows:
        return "Tidak ada lesi karies terdeteksi pada foto yang diunggah."
    lines = [
        "| Gigi | Nama gigi | ICDAS | Tersembunyi | Prior ICD-10 | Diferensial |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        diff = ", ".join(r["differential"]) or "—"
        lines.append(
            f"| {r['fdi']} | {toothprofile.tooth_name(r['fdi'])} | D{r['grade']} | "
            f"{'ya' if r['hidden'] else 'tidak'} | {r['primary']} | {diff} |"
        )
    return "\n".join(lines)


def dentition_note(detections: dict | None) -> str:
    """Whole-mouth context: missing teeth, hidden lesions, which views were captured."""
    meta = (detections or {}).get("meta") or {}
    notes: list[str] = []

    views = meta.get("views") or []
    if views:
        notes.append(f"Foto intraoral yang tersedia: {', '.join(str(v) for v in views)}.")
    notes.append(
        "Panoramik tersedia." if meta.get("has_panoramic")
        else "Tidak ada panoramik — lesi tersembunyi tidak dapat dinilai."
    )

    missing = icd10.missing_fdi(detections)
    if missing:
        notes.append("Gigi hilang (ompong), disepakati kedua detektor: "
                     + ", ".join(str(f) for f in missing) + ".")
    hidden = meta.get("hidden_fdi") or []
    if hidden:
        notes.append("Lesi tersembunyi (hanya terlihat pada panoramik): "
                     + ", ".join(str(h) for h in hidden) + ".")
    predicted = meta.get("predicted_fdi") or []
    if predicted:
        notes.append("Posisi FDI hasil interpolasi geometris (bukan deteksi langsung): "
                     + ", ".join(str(p) for p in predicted) + ".")
    return "\n".join(f"- {n}" for n in notes)


def evidence_block(detections: dict | None) -> str:
    """The full per-patient evidence: prior table + per-tooth quantitative profiles."""
    rows = toothprofile.profiles(detections)
    return (
        "### Ringkasan & prior ICD-10\n"
        f"{prior_table(detections)}\n\n"
        "### Konteks rongga mulut\n"
        f"{dentition_note(detections)}\n\n"
        "### Data kuantitatif per gigi terdampak\n"
        f"{toothprofile.render_profiles(rows)}"
    )


def evidence_note(state: dict[str, Any]) -> str:
    n_docs = len(state.get("rag") or [])
    return (
        f"{n_docs} kutipan literatur terlampir sebagai dokumen bernomor; "
        "sitasi dengan penanda bila dipakai."
        if n_docs
        else "Tidak ada kutipan literatur yang tersedia — jawab dari pengetahuan klinis saja, "
        "jangan menyebut sumber apa pun, dan kosongkan blok sitasi."
    )
