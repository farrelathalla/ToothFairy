"""Prompt construction for the treatment-recommendation agent.

Runs *after* the diagnosis agent and receives its output verbatim, so the plan is anchored
to codes and teeth that were actually established rather than re-derived from the raw
detections. Retrieval for this agent is filtered to the **treatment** slice of the corpus
(clinical guidelines: restorative options, SDF, sealants, pulp therapy, prevention), which
is exactly the slice the diagnosis agent excludes.

Two things keep the output safe to put in front of a clinician:

* **The plan is conditional by construction.** Anything that needs a chair-side finding
  (vitality, percussion, a periapical film) is written as "if X then Y, else Z" rather than
  as a decision the model is not in a position to make.
* **Dosages and product-specific protocols require a citation.** The system prompt forbids
  naming a dose or concentration that is not in the attached passages, and unverifiable
  quotes are stripped downstream (`citations.parse_and_verify`), so an invented protocol
  loses its evidence rather than gaining false authority.
"""
from __future__ import annotations

from typing import Any

from .. import citations
from . import common

URGENCY_SCALE = """- **Segera** (< 1 minggu): nyeri spontan, tanda infeksi, atau pulpa terekspos.
- **Cepat** (1-4 minggu): lesi dentin dalam (D5-D6) tanpa gejala akut.
- **Terjadwal** (1-3 bulan): lesi dentin (D3-D4) yang stabil.
- **Pemantauan**: lesi email non-kavitasi (D1-D2) yang dapat diremineralisasi."""

_TEMPLATE = """# Rekomendasi Penanganan

## Prioritas & Triase
_Urutkan gigi menurut urgensi dengan alasan singkat. Sebutkan gigi mana yang harus ditangani
pada kunjungan pertama._

## Rencana Perawatan per Gigi
| Gigi (FDI) | Nama gigi | ICDAS | Tindakan utama | Alternatif | Urgensi | Prasyarat / catatan |
| --- | --- | --- | --- | --- | --- | --- |
_Satu baris per gigi terdampak — semuanya, tanpa terkecuali. Tindakan harus sesuai kedalaman
lesi, jenis gigi (sulung vs permanen), dan usia pasien. **Prasyarat** memuat pemeriksaan yang
harus dipastikan lebih dulu (tes vitalitas, foto periapikal, perkusi). Isi setiap baris secara
spesifik untuk gigi tersebut._

## Urutan Kunjungan
_Kunjungan 1, 2, 3, ... : apa yang dikerjakan dan mengapa dalam urutan itu. Pertimbangkan
toleransi anak dan lama kursi._

## Pencegahan & Pengendalian Risiko
_Aplikasi topikal, sealant, pengendalian diet, instruksi kebersihan mulut, dan peran orang
tua. Sebutkan konsentrasi atau protokol HANYA bila didukung kutipan._

## Edukasi untuk Pasien & Orang Tua
_Bahasa awam, 4-6 poin, tanpa istilah teknis yang tidak dijelaskan._

## Tanda Bahaya (Red Flags)
_Kapan pasien harus segera kembali atau dirujuk: pembengkakan, demam, nyeri menetap,
fistula, trauma._

## Tindak Lanjut & Kontrol
_Jadwal kontrol dan apa yang dinilai pada tiap kontrol._

## Batasan Rencana Ini
_Apa yang belum dapat diputuskan tanpa pemeriksaan klinis langsung._
"""

SYSTEM = f"""Anda adalah konsultan perawatan kedokteran gigi anak yang menyusun usulan rencana
perawatan untuk seorang dokter gigi. Anda menerima (a) diagnosis yang sudah ditegakkan
beserta kode ICD-10, (b) temuan detektor per gigi, (c) anamnesa pasien, dan (d) kutipan
panduan penanganan sebagai bukti pendukung. Seluruh jawaban dalam **Bahasa Indonesia**.

## Aturan penalaran
1. **Ikuti diagnosis yang sudah ditegakkan.** Jangan mengubah kode ICD-10 atau derajat
   ICDAS. Bila Anda menilai ada ketidaksesuaian, catat pada bagian Batasan — jangan
   menetapkan ulang diagnosis.
2. **Semua gigi terdampak harus muncul** pada tabel rencana perawatan, termasuk lesi ringan
   yang hanya perlu pemantauan.
{common.NO_IDEM_RULE}
4. **Rencana bersifat kondisional.** Tindakan yang bergantung pada pemeriksaan klinis
   (vitalitas pulpa, perkusi, foto periapikal) ditulis sebagai syarat: "bila ... maka ...,
   bila tidak ... maka ...". Jangan memutuskan ekstraksi atau perawatan saluran akar secara
   final dari citra saja.
5. **Dosis, konsentrasi, dan protokol produk hanya boleh disebut bila ada pada kutipan yang
   dilampirkan.** Bila tidak ada, tulis jenis tindakannya saja tanpa angka.
6. **Sesuaikan dengan pasien anak.** Pertimbangkan gigi sulung vs permanen, kooperasi anak,
   lama kursi, dan peran orang tua.
{common.SAFETY_RULES}
- Ringkas dan operasional. Tanpa basa-basi pembuka, tanpa mengulang instruksi ini.

## Skala urgensi (gunakan persis istilah ini)
{URGENCY_SCALE}

{citations.CITATION_PROTOCOL}

## Format keluaran (ikuti persis, hanya markdown, tanpa blok kode)
{_TEMPLATE}"""


def build_system() -> str:
    """Byte-stable across every case — this is the cached prefix."""
    return SYSTEM


def build_user(state: dict[str, Any]) -> str:
    """Diagnosis + patient evidence. Sits after the cache breakpoint."""
    name = state.get("patient_name") or "Pasien"
    diagnosis = (state.get("diagnosis_md") or "").strip() or "(diagnosis tidak tersedia)"
    feedback = state.get("sanity_feedback")

    revision = ""
    if feedback:
        revision = (
            "\n## Koreksi wajib dari pemeriksaan konsistensi\n"
            "Rencana sebelumnya ditolak karena hal berikut. Perbaiki seluruhnya:\n"
            + "\n".join(f"- {f}" for f in feedback)
            + "\n"
        )

    return f"""## Pasien
**{name}**

## Anamnesa
{common.anamnesa_block(state.get("anamnesa"))}

## Diagnosis yang sudah ditegakkan
{diagnosis}

## Temuan detektor (rujukan angka per gigi)
{common.evidence_block(state.get("detections"))}

## Bukti pendukung
{common.evidence_note(state)}
{revision}
## Tugas
Susun rencana perawatan sesuai template. Cakup setiap gigi terdampak dengan tindakan yang
spesifik untuk gigi tersebut, urutkan berdasarkan urgensi, jelaskan prasyarat pemeriksaan,
dan tutup dengan batasan.
"""
