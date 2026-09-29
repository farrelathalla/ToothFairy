"""Thin Anthropic SDK wrapper for the advisory layer.

Three jobs:

* **`is_enabled()`** — the single gate. False (no key, or `LLM_ENABLED=0`) means *nothing*
  here touches the network, so pytest/E2E always run the deterministic stub.
* **`answer_with_citations()`** — the diagnosis call: a prompt-cached system prompt, the
  retrieved passages as `document` blocks with **Claude Citations** enabled, and the
  patient's data as the user turn. Citations return exact `cited_text` + source, which is
  what makes the output auditable and keeps the model from inventing document facts.
* **`helper()`** — Haiku for cheap sub-tasks (contextualizing chunks at ingest, LLM-judge
  scoring in the evals). Never used for clinical text.

Token/cost efficiency (PLAN §8.3), all without touching output quality:
  - the system prompt + ICD-10 table are one **cached** block (`cache_control: ephemeral`),
    so every diagnosis after the first reads them at ~0.1× input price;
  - `helper()` caches the document body so 40 chunk-blurbs for one PDF pay for it once;
  - retrieval hands us a small top-N (6) instead of a big top-K;
  - `output_config.effort` is a config knob — drop it to `medium` to trade tokens for cost.

Model notes: `claude-sonnet-5` takes adaptive thinking + `effort` and rejects
`budget_tokens`/`temperature`. `claude-haiku-4-5` does **not** accept `effort` — don't send
it. Citations and `output_config.format` are mutually exclusive, so the agent asks for a
fixed markdown template instead of a JSON schema.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

_client = None


def api_key() -> str:
    return (settings.anthropic_api_key or "").strip()


def is_enabled() -> bool:
    """True only when a real Claude call is both configured and permitted."""
    return bool(settings.llm_enabled and api_key())


def get_client():
    global _client
    if _client is None:
        import anthropic  # noqa: PLC0415 (keep the import off the unit-test path)

        _client = anthropic.Anthropic(api_key=api_key())
    return _client


def _cached_system(text: str) -> list[dict]:
    return [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}]


def helper(
    system: str,
    user: str,
    *,
    max_tokens: int = 300,
    cache_system: bool = True,
    model: str | None = None,
) -> str:
    """One cheap Haiku turn returning plain text. No effort param — Haiku 4.5 rejects it."""
    resp = get_client().messages.create(
        model=model or settings.llm_helper_model,
        max_tokens=max_tokens,
        system=_cached_system(system) if cache_system else system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def answer_with_citations(
    system: str,
    documents: list[dict[str, Any]],
    user: str,
    *,
    max_tokens: int | None = None,
    effort: str | None = None,
):
    """Diagnosis call. `documents` = [{title, context, text}] → cited `document` blocks.

    Returns the raw SDK `Message` (the caller renders markdown + reads `usage`).
    """
    content: list[dict[str, Any]] = [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": doc["text"]},
            "title": doc.get("title") or f"Dokumen {i + 1}",
            "context": doc.get("context") or "",
            "citations": {"enabled": True},
        }
        for i, doc in enumerate(documents)
    ]
    content.append({"type": "text", "text": user})

    return get_client().messages.create(
        model=settings.llm_model,
        max_tokens=max_tokens or settings.llm_max_tokens,
        system=_cached_system(system),
        thinking={"type": "adaptive"},
        output_config={"effort": effort or settings.llm_effort},
        messages=[{"role": "user", "content": content}],
    )


def render_cited_markdown(message, documents: list[dict[str, Any]]) -> tuple[str, list[dict]]:
    """Splice Claude's citations into the markdown as footnotes.

    Claude returns one `text` block per cited span. We attach a `[^N]` marker per source
    **document** (not per span) so a paragraph citing one paper three times reads cleanly,
    and collect the exact `cited_text` under a `Rujukan` section — that verbatim quote is
    what a dentist audits the claim against.
    """
    order: list[int] = []            # document_index, in first-citation order
    snippets: dict[int, list[str]] = {}
    parts: list[str] = []

    for block in message.content:
        if getattr(block, "type", None) != "text":
            continue
        text = block.text
        cites = getattr(block, "citations", None) or []
        marks: list[str] = []
        for cite in cites:
            di = getattr(cite, "document_index", None)
            if di is None or not (0 <= di < len(documents)):
                continue
            if di not in order:
                order.append(di)
                snippets[di] = []
            quote = (getattr(cite, "cited_text", "") or "").strip()
            if quote and len(snippets[di]) < 2 and quote not in snippets[di]:
                snippets[di].append(quote)
            mark = f"[^{order.index(di) + 1}]"
            if mark not in marks:
                marks.append(mark)
        parts.append(text + ("".join(marks) if marks else ""))

    body = "".join(parts).rstrip()
    sources: list[dict] = []
    if order:
        lines = ["", "", "## Rujukan", ""]
        for n, di in enumerate(order, start=1):
            doc = documents[di]
            ref = doc.get("ref") or ""
            lines.append(f"[^{n}]: **{doc.get('title', '')}**" + (f" — {ref}" if ref else ""))
            for quote in snippets[di]:
                short = quote if len(quote) <= 260 else quote[:257] + "…"
                lines.append(f"    > {short}")
            sources.append({"n": n, "doc_id": doc.get("doc_id"), "title": doc.get("title"),
                            "ref": ref, "quotes": snippets[di]})
        body += "\n".join(lines)

    return body + "\n", sources


def usage_of(message) -> dict[str, int]:
    """Flatten `message.usage` for the eval report's cost table."""
    u = getattr(message, "usage", None)
    if u is None:
        return {}
    return {
        "input_tokens": getattr(u, "input_tokens", 0) or 0,
        "output_tokens": getattr(u, "output_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }
