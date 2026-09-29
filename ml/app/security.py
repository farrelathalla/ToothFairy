"""Access control for the internal ML API.

This service holds **no user accounts and no sessions** — the Go gateway owns identity and
is the only client that may reach it. So the check here is a single shared secret presented
on every `/internal/*` call, and the service is expected to be bound to a private network.

`INTERNAL_API_KEY` empty disables the check, which is convenient for `uvicorn` on localhost
and is exactly what must never happen in a deployment; `main.py` logs a warning at startup
so an unset key cannot pass unnoticed.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import settings

HEADER = "X-Internal-Key"


def require_internal_key(x_internal_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: constant-time comparison against the configured secret."""
    expected = (settings.internal_api_key or "").strip()
    if not expected:
        return
    if not x_internal_key or not hmac.compare_digest(x_internal_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Kunci internal tidak valid",
        )
