"""PDF → chunks → Anthropic **Contextual Retrieval** blurbs.

A bare chunk ("…risk rose 11.6-fold…") is nearly unretrievable: it names neither the study
nor the exposure. Anthropic's contextual-retrieval recipe fixes this by having a cheap model
write a 1–2 sentence blurb situating each chunk in its document, and **prepending that blurb
to the chunk before indexing** (dense *and* BM25). Reported effect: ~49% fewer failed
retrievals, ~67% with reranking on top.

Two cost controls make this a one-time expense:
  * the document body is sent once per PDF as a **prompt-cached** system block, so the 30–60
    blurb calls for that PDF read it at ~0.1× input price;
  * every blurb is memoized on disk by `sha1(doc_id + chunk text)`, so a re-build after a
    chunker tweak only pays for chunks that actually changed.

The blurb is stored separately from the chunk text: indexing sees `blurb + "\\n\\n" + chunk`,
but the **prompt** sends the raw chunk as the citable body with the blurb in the document
block's `context` field — so Claude never cites a sentence we wrote.
"""
from __future__ import annotations

import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ...config import settings
from .. import claude
from . import chunker

log = logging.getLogger(__name__)

CONTEXT_SYSTEM = """Anda membantu membangun indeks pencarian untuk basis pengetahuan
kedokteran gigi. Berikut adalah keseluruhan isi satu dokumen literatur.

<dokumen judul="{title}" rujukan="{ref}">
{body}
</dokumen>

Tugas Anda: untuk setiap potongan (chunk) dari dokumen ini, tulis 1-2 kalimat singkat yang
menempatkan potongan itu dalam konteks dokumen secara keseluruhan — sebutkan topik/bagian,
populasi atau desain studi bila relevan, dan istilah kunci yang tidak muncul di potongan itu
sendiri. Jawab HANYA dengan kalimat konteks tersebut, tanpa pembuka dan tanpa kutipan."""

CONTEXT_USER = """<potongan>
{chunk}
</potongan>

Tulis kalimat konteks untuk potongan di atas."""

# The document body we cache per PDF. Long enough for context, short enough to stay cheap.
MAX_DOC_CHARS = 60_000


def _cache_path() -> Path:
    return settings.rag_index_dir / "context_cache.json"


def _load_cache() -> dict[str, str]:
    path = _cache_path()
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_cache(cache: dict[str, str]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=0), encoding="utf-8")


def load_manifest() -> list[dict]:
    data = json.loads((settings.corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    return data["documents"]


def extract_pdf(path: Path) -> str:
    from pypdf import PdfReader  # noqa: PLC0415

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _key(doc_id: str, text: str) -> str:
    return hashlib.sha1(f"{doc_id}\x00{text}".encode()).hexdigest()


def contextualize(doc: dict, body: str, chunks: list[str], cache: dict[str, str]) -> list[str]:
    """One blurb per chunk. Uses the disk cache; only misses hit the API."""
    system = CONTEXT_SYSTEM.format(
        title=doc["title"], ref=doc.get("ref", ""), body=body[:MAX_DOC_CHARS]
    )
    missing = [c for c in chunks if _key(doc["id"], c) not in cache]

    if missing and claude.is_enabled():
        # Warm the prompt cache serially, then fan out — parallel cold writes all miss.
        first = missing[0]
        cache[_key(doc["id"], first)] = claude.helper(
            system, CONTEXT_USER.format(chunk=first), max_tokens=200
        )
        rest = missing[1:]
        if rest:
            with ThreadPoolExecutor(max_workers=6) as pool:
                blurbs = list(
                    pool.map(
                        lambda c: claude.helper(
                            system, CONTEXT_USER.format(chunk=c), max_tokens=200
                        ),
                        rest,
                    )
                )
            for chunk, blurb in zip(rest, blurbs):
                cache[_key(doc["id"], chunk)] = blurb
    elif missing:
        log.warning("LLM disabled — indexing %d chunks of doc %s without context blurbs",
                    len(missing), doc["id"])

    return [cache.get(_key(doc["id"], c), "") for c in chunks]


def build_chunks(doc_ids: list[str] | None = None) -> list[dict]:
    """Extract → chunk → contextualize every manifest document. Returns index records."""
    cache = _load_cache()
    records: list[dict] = []

    for doc in load_manifest():
        if doc_ids and doc["id"] not in doc_ids:
            continue
        pdf = settings.corpus_dir / "pdfs" / doc["file"]
        if not pdf.exists():
            log.warning("missing PDF %s — skipped", pdf)
            continue

        body = extract_pdf(pdf)
        chunks = chunker.chunk_text(body)
        if not chunks:
            log.warning("no usable text in %s — skipped", pdf)
            continue

        blurbs = contextualize(doc, body, chunks, cache)
        _save_cache(cache)  # checkpoint after each doc: a crash never re-pays

        for i, (text, blurb) in enumerate(zip(chunks, blurbs)):
            records.append(
                {
                    "chunk_id": f"{doc['id']}#{i}",
                    "doc_id": doc["id"],
                    "title": doc["title"],
                    "ref": doc.get("ref", ""),
                    "category": doc["category"],
                    "context": blurb,
                    "text": text,
                }
            )
        log.info("doc %s: %d chunks", doc["id"], len(chunks))

    _save_cache(cache)
    return records


def indexable(record: dict) -> str:
    """What the dense + BM25 indexes actually see: blurb prepended to the chunk."""
    ctx = (record.get("context") or "").strip()
    return f"{ctx}\n\n{record['text']}" if ctx else record["text"]
