"""LLM-as-judge scorers (the cheap model).

RAGAS-style, adapted to this agent's actual contract. Standard faithfulness asks "is every
claim entailed by the retrieved context?" — that is the wrong question here, because the
diagnosis is deliberately the model's *clinical reasoning*, merely **grounded** by the
corpus. Judging it as pure extraction would score every correct textbook statement as a
hallucination.

So each atomic claim is labelled into one of four buckets instead:

    DOKUMEN   — entailed by a retrieved passage
    INPUT     — entailed by the detections/anamnesa handed to the agent
    KLINIS    — general dental knowledge, no source needed
    SALAH     — contradicts the documents or the input   ← the only real failure

`faithfulness = 1 - SALAH/total`. `document_grounding = DOKUMEN/total` reports how much of the
answer the corpus is actually carrying.

Note what is **not** judged here: whether a quote is really in its source document. That is
verified deterministically by `citations.parse_and_verify` before the answer is ever shown,
so it needs no judge and carries no judge variance.

The judge runs on the cheap model at low reasoning effort — this is bounded verification, not
open-ended reasoning. Token budgets are generous because reasoning tokens bill against
`max_output_tokens`, and a truncated judge silently scores zero.
"""
from __future__ import annotations

import re

from app.llm import openai_client

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

RELEVANCE_SYSTEM = """Anda menilai apakah sebuah keluaran menjawab tugas yang diberikan.
Skala 1-5:
5 = menjawab seluruh tugas, relevan, tanpa isi di luar cakupan.
3 = menjawab sebagian, atau menyisipkan bagian yang bukan tugasnya.
1 = tidak menjawab tugas.
Jawab HANYA satu angka."""

SPECIFICITY_SYSTEM = """Anda menilai apakah sebuah tabel klinis benar-benar membahas
tiap gigi secara spesifik, atau hanya mengulang kalimat yang sama.

Skala 1-5:
5 = setiap baris menyebut temuan khas gigi itu (luas, warna, pola/letak lesi, radiografis).
3 = sebagian baris spesifik, sebagian generik.
1 = hampir semua baris identik atau memakai "idem"/"sda".
Jawab HANYA satu angka."""


def extract_claims(markdown: str, *, max_claims: int = 40) -> list[str]:
    """Atomic claims from the answer markdown (Rujukan section stripped)."""
    body = markdown.split("## Rujukan")[0]
    raw = openai_client.helper(CLAIM_SYSTEM, body, max_tokens=4000)
    claims = [re.sub(r"^[-*]\s*", "", line).strip() for line in raw.splitlines()]
    return [c for c in claims if len(c) > 15][:max_claims]


def label_claims(claims: list[str], passages: list[dict], patient_block: str) -> list[str]:
    """One batched call → a label per claim. Unparseable lines default to KLINIS."""
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
    raw = openai_client.helper(LABEL_SYSTEM, user, max_tokens=32 * len(claims) + 2000)

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
    """Does the (already verbatim-verified) quote actually *support* the statement?"""
    answer = openai_client.helper(
        CITATION_SYSTEM,
        f"PERNYATAAN:\n{statement}\n\nKUTIPAN:\n{quote}",
        max_tokens=800,
    )
    return answer.strip().upper().startswith("YA")


def _score_1_to_5(system: str, user: str) -> int:
    answer = openai_client.helper(system, user, max_tokens=800)
    m = re.search(r"[1-5]", answer)
    return int(m.group()) if m else 0


def score_relevance(task: str, markdown: str) -> int:
    return _score_1_to_5(
        RELEVANCE_SYSTEM,
        f"## TUGAS\n{task}\n\n## KELUARAN\n{markdown.split('## Rujukan')[0]}",
    )


def score_specificity(table_markdown: str) -> int:
    """How per-tooth the diagnosis table really is — the judged half of the anti-Idem check."""
    return _score_1_to_5(SPECIFICITY_SYSTEM, f"## TABEL\n{table_markdown}")
