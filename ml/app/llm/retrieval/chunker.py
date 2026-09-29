"""Paragraph-packing chunker.

Token counts are approximated as `len(text) / CHARS_PER_TOKEN` — good enough to bound
chunk size, and it keeps the ingest path free of a tokenizer dependency. Chunks respect
paragraph boundaries where possible; a single oversized paragraph is split on sentence
boundaries rather than mid-word.
"""
from __future__ import annotations

import re

CHARS_PER_TOKEN = 4  # rough for mixed Indonesian/English academic prose

_PARA_RE = re.compile(r"\n\s*\n")
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def normalize(text: str) -> str:
    """Collapse the ragged whitespace pypdf produces, keep paragraph breaks."""
    # pypdf renders PDF bullet/dingbat glyphs it can't map as U+FFFD. They survive into the
    # chunk text and therefore into the verbatim `cited_text` a dentist reads — strip them.
    text = text.replace("�", " ").replace("\x00", " ")
    text = "".join(c for c in text if c == "\n" or c == "\t" or c.isprintable())
    # de-hyphenate words broken across lines: "cari-\nes" -> "caries"
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # a single newline inside a paragraph is a line wrap, not a break
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    text = _WS_RE.sub(" ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    sentences = _SENT_RE.split(paragraph)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) + 1 > max_chars:
            out.append(buf.strip())
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf.strip():
        out.append(buf.strip())
    # a single monstrous sentence: hard-cut it
    final: list[str] = []
    for piece in out:
        while len(piece) > max_chars:
            final.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            final.append(piece)
    return final


def chunk_text(text: str, *, target_tokens: int = 280, overlap_tokens: int = 50) -> list[str]:
    """Pack paragraphs into ~`target_tokens` chunks with `overlap_tokens` of carry-over."""
    max_chars = target_tokens * CHARS_PER_TOKEN
    overlap_chars = min(overlap_tokens * CHARS_PER_TOKEN, max_chars // 2)
    # A chunk starts with up to `overlap_chars` of carry-over, so a single paragraph may
    # occupy at most the remainder — otherwise tail + paragraph overflows `max_chars`.
    body_chars = max_chars - overlap_chars

    paragraphs: list[str] = []
    for para in _PARA_RE.split(normalize(text)):
        para = para.strip()
        if not para:
            continue
        paragraphs.extend(_split_long(para, body_chars) if len(para) > body_chars else [para])

    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if buf and len(buf) + len(para) + 2 > max_chars:
            chunks.append(buf)
            tail = buf[-overlap_chars:] if overlap_chars else ""
            # start the overlap at a word boundary
            if tail and " " in tail:
                tail = tail[tail.index(" ") + 1:]
            buf = f"{tail}\n\n{para}".strip() if tail else para
        else:
            buf = f"{buf}\n\n{para}".strip() if buf else para
    if buf:
        chunks.append(buf)

    # drop scraps (reference-list fragments, page furniture)
    return [c for c in chunks if len(c) >= 200]
