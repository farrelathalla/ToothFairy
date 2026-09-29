"""Verified citations: how retrieved literature enters the prompt and comes back auditable.

The clinical agents may cite the passages retrieved for them. A citation is only useful to
a dentist if the quote is **really in the document**, so this module does not take the
model's word for it:

    render_documents()   passages  ->  numbered <dokumen> blocks in the user turn
    parse_and_verify()   answer    ->  markdown footnotes, but ONLY for quotes that were
                                       machine-verified as verbatim substrings of the
                                       document they claim to come from

Protocol the agents are instructed to follow (see `prompts/common.py`):

* cite in the body with `[^1]`, `[^2]`, … ;
* end the answer with one machine-readable block

      <!--SITASI
      1|3|verbatim span copied character-for-character from Dokumen 3
      2|1|another verbatim span
      -->

`parse_and_verify` strips that block, checks every claimed span against the source text,
**drops the marker entirely** when a span cannot be found (so a fabricated citation shows
up as no citation rather than as a false one), renumbers what survives in first-use order,
and renders a `Rujukan` section carrying the verbatim quote a dentist audits the claim
against. The `stats` it returns (`claimed` / `verified` / `rejected`) is reported by the
evals — an unverifiable-quote rate is a direct, measurable hallucination signal.
"""
from __future__ import annotations

import re
from typing import Any

# A quote shorter than this is not evidence — it is a coincidence.
MIN_QUOTE_CHARS = 30
# Keep footnotes readable; the full span stays in the returned `sources` payload.
MAX_QUOTE_CHARS = 300
MAX_QUOTES_PER_SOURCE = 2

_SITASI_RE = re.compile(r"<!--\s*SITASI\s*(.*?)-->", re.DOTALL | re.IGNORECASE)
_MARKER_RE = re.compile(r"\[\^(\d+)\]")

CITATION_PROTOCOL = """## Cara menyitasi (wajib diikuti persis)
- Sitasi hanya dari dokumen yang dilampirkan, dengan penanda `[^1]`, `[^2]`, ... di akhir
  kalimat yang didukung dokumen tersebut.
- Jangan menyitasi kalimat yang berasal dari penalaran klinis Anda sendiri.
- Akhiri seluruh jawaban dengan SATU blok berikut (dan tidak ada teks setelahnya):

<!--SITASI
1|<nomor dokumen>|<kutipan verbatim, disalin persis karakter per karakter dari dokumen itu>
2|<nomor dokumen>|<kutipan verbatim lain>
-->

- Kutipan harus **disalin apa adanya** dari isi dokumen (minimal satu kalimat utuh).
  Kutipan yang tidak ditemukan di dokumen akan **dibuang otomatis** beserta penandanya,
  sehingga mengarang kutipan hanya menghilangkan sitasi Anda.
- Bila tidak ada dokumen yang benar-benar mendukung, tulis jawaban tanpa sitasi dan
  kosongkan blok tersebut."""


def render_documents(documents: list[dict[str, Any]]) -> str:
    """Passages → numbered, delimited source blocks for the user turn.

    The blurb written at ingest time (`context`) is shown as orientation, but it is kept
    outside the citable body so the model never quotes a sentence we generated.
    """
    if not documents:
        return ""
    blocks = ["## Dokumen rujukan"]
    for i, doc in enumerate(documents, start=1):
        title = (doc.get("title") or f"Dokumen {i}").replace('"', "'")
        ref = (doc.get("ref") or "").replace('"', "'")
        context = (doc.get("context") or "").strip()
        blocks.append(
            f'<dokumen nomor="{i}" judul="{title}" rujukan="{ref}">\n'
            + (f"[konteks: {context}]\n" if context else "")
            + (doc.get("text") or "").strip()
            + "\n</dokumen>"
        )
    return "\n\n".join(blocks)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _norm_hard(text: str) -> str:
    """Whitespace/case-insensitive *and* punctuation-insensitive.

    PDF extraction turns ligatures, soft hyphens and typographic dashes into characters a
    model will not reproduce byte-exactly. Ignoring punctuation tolerates that without
    tolerating paraphrase — every word must still match, in order.
    """
    # Collapse whitespace *after* stripping punctuation: dropping an em-dash leaves the two
    # spaces that surrounded it, which would otherwise fail an otherwise-exact match.
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _norm(text))).strip()


def _verify(quote: str, document: dict[str, Any]) -> bool:
    if len((quote or "").strip()) < MIN_QUOTE_CHARS:
        return False
    body = document.get("text") or ""
    return _norm(quote) in _norm(body) or _norm_hard(quote) in _norm_hard(body)


def _parse_block(raw: str) -> list[tuple[int, int, str]]:
    """`n|doc|quote` lines → tuples. Malformed lines are skipped, never raised on."""
    out: list[tuple[int, int, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            marker, doc_no = int(parts[0].strip()), int(parts[1].strip())
        except ValueError:
            continue
        quote = parts[2].strip().strip('"').strip("“”")
        if quote:
            out.append((marker, doc_no, quote))
    return out


def parse_and_verify(
    markdown: str, documents: list[dict[str, Any]]
) -> tuple[str, list[dict], dict[str, int]]:
    """Strip the SITASI block, verify each quote, renumber survivors, append `Rujukan`.

    Returns `(markdown, sources, stats)`.
    """
    stats = {"claimed": 0, "verified": 0, "rejected": 0}
    body = markdown or ""

    match = _SITASI_RE.search(body)
    claims = _parse_block(match.group(1)) if match else []
    body = _SITASI_RE.sub("", body).rstrip()
    stats["claimed"] = len(claims)

    # marker number -> (document index, verified quote)
    verified: dict[int, tuple[int, str]] = {}
    for marker, doc_no, quote in claims:
        idx = doc_no - 1
        if not (0 <= idx < len(documents)) or not _verify(quote, documents[idx]):
            stats["rejected"] += 1
            continue
        verified.setdefault(marker, (idx, quote))
        stats["verified"] += 1

    if not verified:
        return _strip_markers(body), [], stats

    # Renumber by first use in the body; collapse repeat citations of one document.
    order: list[int] = []                    # document indices, in first-cited order
    quotes: dict[int, list[str]] = {}

    def _replace(m: re.Match) -> str:
        entry = verified.get(int(m.group(1)))
        if entry is None:
            return ""                        # unverified marker -> silently dropped
        idx, quote = entry
        if idx not in order:
            order.append(idx)
            quotes[idx] = []
        if quote not in quotes[idx] and len(quotes[idx]) < MAX_QUOTES_PER_SOURCE:
            quotes[idx].append(quote)
        return f"[^{order.index(idx) + 1}]"

    body = _MARKER_RE.sub(_replace, body).rstrip()

    sources: list[dict] = []
    lines = ["", "", "## Rujukan", ""]
    for n, idx in enumerate(order, start=1):
        doc = documents[idx]
        ref = doc.get("ref") or ""
        lines.append(f"[^{n}]: **{doc.get('title', '')}**" + (f" — {ref}" if ref else ""))
        for quote in quotes[idx]:
            short = quote if len(quote) <= MAX_QUOTE_CHARS else quote[: MAX_QUOTE_CHARS - 1] + "…"
            lines.append(f"    > {short}")
        sources.append(
            {"n": n, "doc_id": doc.get("doc_id"), "title": doc.get("title"),
             "ref": ref, "quotes": quotes[idx]}
        )

    return body + "\n".join(lines) + "\n", sources, stats


def _strip_markers(body: str) -> str:
    """No verified citation survived — remove every marker so none dangles."""
    return _MARKER_RE.sub("", body).rstrip() + "\n"
