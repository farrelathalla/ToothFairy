"""LLM-as-judge scorers (Haiku 4.5).

RAGAS-style, adapted to this agent's actual contract. Standard faithfulness asks "is every
claim entailed by the retrieved context?" — that is the wrong question here, because the
diagnosis is deliberately Claude's *clinical reasoning*, merely **grounded** by the corpus
(PLAN §8.3). Judging it as pure extraction would score every correct textbook statement as a
hallucination.

So each atomic claim is labelled into one of four buckets instead:

    DOKUMEN   — entailed by a retrieved passage
    INPUT     — entailed by the detections/anamnesa handed to the agent
    KLINIS    — general dental knowledge, no source needed
    SALAH     — contradicts the documents or the input   ← the only real failure

`faithfulness = 1 - SALAH/total`. `document_grounding = DOKUMEN/total` reports how much of the
answer the corpus is actually carrying. A separate **citation precision** check verifies each
cited span against the exact `cited_text` Claude quoted — that's the auditable half.

The judge is Haiku (~1/3 the cost of Sonnet, and this is a bounded verification task, not
open-ended reasoning). Judge prompts are prompt-cached: the rubric is stable across claims.
"""
from __future__ import annotations

import re

from app.llm import claude

_LABELS = ("DOKUMEN", "INPUT", "KLINIS", "SALAH")

CLAIM_SYSTEM = """Anda memecah teks diagnosis kedokteran gigi menjadi klaim atomik.

Klaim atomik = satu pernyataan faktual yang dapat diverifikasi sendiri. Abaikan judul,
kalimat instruksi, penanda sitasi seperti [^1], dan isi bagian "Rujukan".

Keluarkan HANYA daftar klaim, satu per baris, diawali "- ". Tanpa nomor, tanpa komentar."""

LABEL_SYSTEM = """Anda adalah auditor klinis. Untuk setiap klaim, tentukan SATU label:

- DOKUMEN : klaim didukung secara eksplisit oleh salah satu KUTIPAN LITERATUR.
- INPUT   : klaim mengulang/menyimpulkan langsung DATA PASIEN (temuan detektor, anamnesa).
- KLINIS  : klaim adalah pengetahuan kedokteran gigi umum yang benar, tidak butuh sumber.
- SALAH   : klaim bertentangan dengan kutipan atau data pasien, ATAU menyebut angka,
            persentase, nama studi, atau statistik yang tidak ada di kutipan mana pun.

Aturan penting: sebuah pernyataan umum yang benar secara klinis TIDAK boleh diberi label
SALAH hanya karena tidak ada di kutipan. SALAH hanya untuk kontradiksi atau spesifik
kuantitatif yang tidak berdasar.

Jawab HANYA dengan baris "<nomor>: <LABEL>", satu per klaim, tanpa penjelasan."""

CITATION_SYSTEM = """Anda memverifikasi sitasi. Diberikan sebuah PERNYATAAN dan KUTIPAN
verbatim dari sebuah makalah. Jawab HANYA "YA" bila kutipan tersebut benar-benar mendukung
pernyataan itu, atau "TIDAK" bila tidak mendukung / tidak relevan."""

RELEVANCE_SYSTEM = """Anda menilai apakah sebuah keluaran diagnosis menjawab tugas yang
diberikan. Skala 1-5:
5 = menjawab seluruh tugas (kode ICD-10 per gigi, risiko pulpa, perkiraan gejala, batasan),
    relevan, tanpa isi di luar cakupan.
3 = menjawab sebagian, atau menyisipkan rencana perawatan yang bukan tugasnya.
1 = tidak menjawab tugas.
Jawab HANYA satu angka."""


def extract_claims(markdown: str, *, max_claims: int = 40) -> list[str]:
    """Atomic claims from the diagnosis markdown (Rujukan section stripped)."""
    body = markdown.split("## Rujukan")[0]
    raw = claude.helper(CLAIM_SYSTEM, body, max_tokens=1600)
    claims = [re.sub(r"^[-*]\s*", "", line).strip() for line in raw.splitlines()]
    return [c for c in claims if len(c) > 15][:max_claims]


def label_claims(claims: list[str], passages: list[dict], patient_block: str) -> list[str]:
    """One batched Haiku call → a label per claim. Unparseable lines default to KLINIS."""
    if not claims:
        return []
    quotes = "\n\n".join(
        f"[{i + 1}] {p.get('title', '')}\n{p.get('text', '')}" for i, p in enumerate(passages)
    ) or "(tidak ada kutipan)"
    numbered = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(claims))

    user = (
        f"## KUTIPAN LITERATUR\n{quotes}\n\n"
        f"## DATA PASIEN\n{patient_block}\n\n"
        f"## KLAIM\n{numbered}\n\nBeri label setiap klaim."
    )
    raw = claude.helper(LABEL_SYSTEM, user, max_tokens=16 * len(claims) + 200)

    labels = ["KLINIS"] * len(claims)
    for line in raw.splitlines():
        m = re.match(r"\s*(\d+)\s*[:.\)]\s*([A-Z]+)", line)
        if not m:
            continue
        idx, label = int(m.group(1)) - 1, m.group(2)
        if 0 <= idx < len(claims) and label in _LABELS:
            labels[idx] = label
    return labels


def verify_citation(statement: str, quote: str) -> bool:
    answer = claude.helper(
        CITATION_SYSTEM,
        f"PERNYATAAN:\n{statement}\n\nKUTIPAN:\n{quote}",
        max_tokens=8,
    )
    return answer.strip().upper().startswith("YA")


def score_relevance(task: str, markdown: str) -> int:
    answer = claude.helper(
        RELEVANCE_SYSTEM,
        f"## TUGAS\n{task}\n\n## KELUARAN\n{markdown.split('## Rujukan')[0]}",
        max_tokens=8,
    )
    m = re.search(r"[1-5]", answer)
    return int(m.group()) if m else 0
