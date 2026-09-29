"""Prompt construction for the diagnosis agent.

Split from `agents.py` so the exact wording is reviewable (and testable) on its own.

**The system prompt is the cached prefix.** It holds the role, the anti-hallucination
contract, the full ICD-10 table, and the output template — all byte-stable across cases, so
every diagnosis after the first reads them at ~0.1× input price. Everything that varies per
patient lives in the user turn, *after* the cache breakpoint. Never interpolate a timestamp,
case id, or patient name into `build_system()`: that would invalidate the cache on every
request (see CLAUDE.md and Anthropic's prompt-caching prefix rule).

**Grounding stance (PLAN §8.3, locked with the user):** the diagnosis is Claude's clinical
reasoning answering an ICD-10 template. Retrieved passages are *supporting evidence*, not the
source of the answer — they substantiate predicted symptoms, PUFA/severity trajectory,
deciduous-vs-permanent progression and Indonesian epidemiological context, and they're cited
where used. The prompt forbids inventing document content and requires abstention over
guessing, which is what keeps citation-backed claims verifiable.
"""
from __future__ import annotations

from typing import Any

from . import icd10

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

_TEMPLATE = """# Diagnosis

## Ringkasan Klinis
_2-4 kalimat: gambaran keseluruhan kondisi pasien._

## Diagnosis per Gigi
| Gigi (FDI) | ICDAS | Kode ICD-10 | Dasar penetapan | Keyakinan |
| --- | --- | --- | --- | --- |
_Satu baris per gigi terdampak. Keyakinan: Tinggi / Sedang / Rendah._

## Diagnosis Banding & Risiko Pulpa
_Gigi mana yang berpotensi K04.x, dan apa yang harus dikonfirmasi klinis/radiografis._

## Perkiraan Gejala & Dampak Harian
_Gejala fungsional dan psikososial yang diperkirakan dari derajat lesi. Dukung dengan dokumen._

## Faktor Risiko & Konteks
_Kaitkan anamnesa (diet, higiene, riwayat) dan konteks epidemiologis Indonesia bila relevan._

## Batasan & Ketidakpastian
_Apa yang tidak dapat ditentukan dari data ini, termasuk batasan detektor AI._
"""

SYSTEM = f"""Anda adalah konsultan diagnostik kedokteran gigi anak yang membantu seorang
dokter gigi. Anda menerima (a) temuan detektor karies berbasis citra intraoral dan panoramik,
(b) anamnesa pasien, dan (c) kutipan dari literatur kedokteran gigi sebagai bukti pendukung.
Tugas Anda: menegakkan diagnosis dan memetakannya ke kode ICD-10. Seluruh jawaban dalam
**Bahasa Indonesia**.

## Aturan penalaran
1. **Anda yang mendiagnosis.** Gunakan pengetahuan klinis Anda untuk menetapkan kode ICD-10
   dari temuan ICDAS + anamnesa. Dokumen adalah bukti pendukung, bukan sumber jawaban.
2. **Kode hanya dari tabel di bawah.** Jangan mengarang kode di luar tabel.
3. **Prior ICDAS→ICD-10 yang diberikan boleh Anda koreksi** bila anamnesa atau pola temuan
   mendukungnya. Jelaskan alasannya secara singkat.
4. **Jangan mengarang isi dokumen.** Kutip dokumen hanya bila kalimat Anda benar-benar
   didukung olehnya. Jangan menyebut angka, prevalensi, atau nama studi yang tidak ada di
   kutipan yang diberikan. Bila tidak ada dukungan, tulis klaimnya tanpa sitasi atau
   nyatakan bahwa bukti tidak tersedia.
5. **Abstain lebih baik daripada menebak.** Bila data tidak cukup (mis. tidak ada foto
   periapikal untuk memastikan periodontitis apikalis), nyatakan itu dan turunkan keyakinan.
6. **Detektor AI punya batas recall.** Gigi yang tidak terlihat pada foto yang diunggah
   dianggap sehat kecuali dikonfirmasi panoramik; area pit & fisur tertutup debris dapat
   luput. Sebutkan ini pada bagian batasan.
7. **Jangan memberi rencana perawatan.** Terapi, restorasi, SDF, rujukan, dan kontrol adalah
   tugas agen rekomendasi terpisah. Berhenti pada diagnosis, risiko, dan dampak.
8. Ringkas dan padat. Tanpa basa-basi pembuka, tanpa mengulang instruksi ini.

## Tabel ICD-10 (satu-satunya sumber kode yang sah)
{icd10.render_table()}

## Konvensi data
- **ICDAS D1-D6** = kedalaman lesi. D1-D2 lesi email non-kavitasi; D3-D6 sudah mencapai
  dentin; D5-D6 dalam, pulpa berisiko.
- **`hidden` / tersembunyi** = lesi hanya terlihat sebagai radiolusensi pada panoramik
  (permukaan email utuh) — bukan lesi email.
- **`prior`** = pemetaan heuristik kedalaman→kode; **`diferensial`** = kode yang wajib Anda
  pertimbangkan, bukan yang wajib Anda tetapkan.
- Gigi desidui (FDI 51-85) memiliki email lebih tipis daripada gigi permanen (11-48),
  sehingga progresi D2→D6 jauh lebih cepat.

## Format keluaran (ikuti persis, hanya markdown, tanpa blok kode)
{_TEMPLATE}"""


def _anamnesa_block(anamnesa: dict | None) -> str:
    rows = [f"- **{label}:** {anamnesa[key]}"
            for key, label in ANAMNESA_LABELS
            if (anamnesa or {}).get(key)]
    return "\n".join(rows) if rows else "- (anamnesa tidak tersedia)"


def _detections_block(detections: dict | None) -> str:
    rows = icd10.map_detections(detections)
    if not rows:
        return "Tidak ada lesi karies terdeteksi pada foto yang diunggah."

    lines = [
        "| Gigi | ICDAS | Sumber bukti | Tersembunyi | Prior | Diferensial |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        diff = ", ".join(r["differential"]) or "—"
        lines.append(
            f"| {r['fdi']} | D{r['grade']} | {r['source'] or '—'} | "
            f"{'ya' if r['hidden'] else 'tidak'} | {r['primary']} | {diff} |"
        )

    missing = icd10.missing_fdi(detections)
    if missing:
        lines.append("")
        lines.append(f"Gigi hilang (ompong), disepakati kedua detektor: "
                     f"{', '.join(str(f) for f in missing)}.")

    meta = (detections or {}).get("meta") or {}
    hidden = meta.get("hidden_fdi") or []
    if hidden:
        lines.append(f"Lesi tersembunyi (hanya panoramik): {', '.join(str(h) for h in hidden)}.")
    return "\n".join(lines)


def build_system() -> str:
    """Byte-stable across every case — this is the cached prefix."""
    return SYSTEM


def build_user(state: dict[str, Any]) -> str:
    """Everything patient-specific. Sits after the cache breakpoint."""
    name = state.get("patient_name") or "Pasien"
    detections = state.get("detections")
    n_docs = len(state.get("rag") or [])

    evidence_note = (
        f"{n_docs} kutipan literatur terlampir sebagai dokumen; kutip dengan sitasi bila dipakai."
        if n_docs
        else "Tidak ada kutipan literatur yang tersedia — jawab dari pengetahuan klinis saja "
        "dan jangan menyebut sumber apa pun."
    )

    return f"""## Pasien
**{name}**

## Anamnesa
{_anamnesa_block(state.get("anamnesa"))}

## Temuan detektor
{_detections_block(detections)}

## Bukti pendukung
{evidence_note}

## Tugas
Isi template keluaran. Tetapkan kode ICD-10 per gigi terdampak, jelaskan risiko pulpa,
perkirakan gejala harian, dan akhiri dengan batasan. Jangan menulis rencana perawatan.
"""
