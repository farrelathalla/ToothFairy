"""Thin OpenAI SDK wrapper for the advisory layer.

Everything that talks to the model goes through here, so the rest of the package never
imports `openai` directly and the whole layer can be disabled with one flag.

Four jobs:

* **`is_enabled()`** — the single gate. False (no key, or `LLM_ENABLED=0`) means *nothing*
  here touches the network, so pytest/E2E always run the deterministic stub.
* **`answer_with_documents()`** — the clinical call (diagnosis, recommendation): a stable
  `instructions` prefix, the retrieved passages rendered as numbered, delimited document
  blocks, and the patient's data as the user turn.
* **`helper()`** — the cheap model for sub-tasks (contextualizing chunks at ingest,
  LLM-judge scoring in the evals). Never used for clinical text.
* **`moderate()`** — omni-moderation over free-text patient input, so obviously
  out-of-scope or abusive text never reaches the clinical prompt.

Cost/latency notes:
  - OpenAI caches long prompt **prefixes automatically**; `instructions` holds the whole
    byte-stable system prefix (role + ICD-10 table + output template) and every call passes
    a `prompt_cache_key`, so repeat cases read the prefix at a large discount.
  - retrieval hands us a small top-N (6) rather than a big top-K;
  - `reasoning.effort` is a config knob — drop it to `medium`/`low` to trade quality for cost.

Model notes: `gpt-5.6-sol` is the flagship reasoning model used for clinical text;
`gpt-5.6-luna` is the cheap helper. Reasoning tokens bill against `max_output_tokens`, so
`llm_max_tokens` is deliberately generous — a truncated clinical answer is worse than an
expensive one, and `LLMTruncated` is raised (and caught upstream) rather than returning
half a table.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import settings

log = logging.getLogger(__name__)

_client = None


class LLMTruncated(RuntimeError):
    """The model hit `max_output_tokens` before finishing — never return a partial answer."""


def api_key() -> str:
    return (settings.openai_api_key or "").strip()


def is_enabled() -> bool:
    """True only when a real model call is both configured and permitted."""
    return bool(settings.llm_enabled and api_key())


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI  # noqa: PLC0415 (keep the import off the unit-test path)

        kwargs: dict[str, Any] = {
            "api_key": api_key(),
            "timeout": settings.llm_timeout_s,
            "max_retries": settings.llm_max_retries,
        }
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        _client = OpenAI(**kwargs)
    return _client


def reset_client() -> None:
    """Drop the memoized client (tests, key rotation)."""
    global _client
    _client = None


def text_of(response) -> str:
    """`output_text` when the SDK exposes it, else concatenate the output text parts."""
    text = getattr(response, "output_text", None)
    if text:
        return text.strip()
    parts: list[str] = []
    for item in getattr(response, "output", None) or []:
        for block in getattr(item, "content", None) or []:
            if getattr(block, "type", "") in ("output_text", "text"):
                parts.append(getattr(block, "text", "") or "")
    return "".join(parts).strip()


def _guard(response) -> None:
    if getattr(response, "status", None) == "incomplete":
        detail = getattr(response, "incomplete_details", None)
        reason = getattr(detail, "reason", None) or "unknown"
        raise LLMTruncated(f"response incomplete (reason={reason})")


def helper(
    system: str,
    user: str,
    *,
    max_tokens: int = 1200,
    model: str | None = None,
    effort: str = "low",
    cache_key: str = "toothfairy-helper",
) -> str:
    """One cheap turn returning plain text."""
    response = get_client().responses.create(
        model=model or settings.llm_helper_model,
        instructions=system,
        input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
        reasoning={"effort": effort},
        max_output_tokens=max_tokens,
        prompt_cache_key=cache_key,
    )
    _guard(response)
    return text_of(response)


def answer_with_documents(
    system: str,
    documents: list[dict[str, Any]],
    user: str,
    *,
    max_tokens: int | None = None,
    effort: str | None = None,
    cache_key: str = "toothfairy-clinical",
):
    """Clinical call. `documents` = [{title, ref, context, text}] → numbered source blocks.

    `system` is the byte-stable cached prefix; `documents` + `user` vary per patient and
    sit after it. Returns the raw SDK response (the caller renders markdown + reads usage).
    """
    from . import citations  # noqa: PLC0415 (local import keeps the module graph acyclic)

    body = citations.render_documents(documents)
    text = f"{body}\n\n{user}" if body else user

    response = get_client().responses.create(
        model=settings.llm_model,
        instructions=system,
        input=[{"role": "user", "content": [{"type": "input_text", "text": text}]}],
        reasoning={"effort": effort or settings.llm_effort},
        max_output_tokens=max_tokens or settings.llm_max_tokens,
        prompt_cache_key=cache_key,
    )
    _guard(response)
    return response


def moderate(text: str) -> dict[str, Any]:
    """Classify free-text patient input. Returns `{"flagged": bool, "categories": [...]}`.

    Fails **open** (never flagged) when moderation is disabled or the call errors: a
    moderation outage must not block a clinician from running a case.
    """
    if not (settings.moderation_enabled and api_key()) or not (text or "").strip():
        return {"flagged": False, "categories": [], "checked": False}
    try:
        result = get_client().moderations.create(
            model="omni-moderation-latest", input=text[:8000]
        ).results[0]
        flagged_categories = [
            name for name, hit in (result.categories.model_dump() or {}).items() if hit
        ]
        return {"flagged": bool(result.flagged), "categories": flagged_categories,
                "checked": True}
    except Exception as exc:  # noqa: BLE001 — moderation must never take a case down
        log.warning("moderation check failed, allowing input: %s", exc)
        return {"flagged": False, "categories": [], "checked": False}


def usage_of(response) -> dict[str, int]:
    """Flatten `response.usage` for the eval report's cost table."""
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    details = getattr(usage, "input_tokens_details", None)
    out_details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0,
        "reasoning_tokens": getattr(out_details, "reasoning_tokens", 0) or 0,
    }
