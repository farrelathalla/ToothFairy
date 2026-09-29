"""ToothFairy ML service — FastAPI entrypoint.

    uvicorn app.main:app --port 8000        # from ml/

This service is **stateless**: no accounts, no sessions, no database. It exposes the two
expensive operations — the vision pipeline and the LLM/RAG advisory graph — behind an
internal API that only the Go gateway calls. Identity, case records, uploads and job
scheduling live in the gateway, which is what lets this process be scaled (or GPU-scheduled)
independently of ordinary request traffic.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .llm import openai_client
from .routers import internal

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.results_dir.mkdir(parents=True, exist_ok=True)
    if not (settings.internal_api_key or "").strip():
        log.warning(
            "INTERNAL_API_KEY is unset — the internal API is unauthenticated. "
            "Acceptable on localhost only; set it in every deployment."
        )
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ToothFairy ML Service", version="1.0.0", lifespan=lifespan)

    # The gateway is the intended client and is server-side, so CORS matters only for
    # direct browser debugging in development.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Liveness + the capability flags the gateway reports on its own /health."""
        return {
            "ok": True,
            "service": "ml",
            "mock_inference": settings.mock_inference,
            "llm_enabled": openai_client.is_enabled(),
            "rag_enabled": settings.rag_enabled,
            "model": settings.llm_model if openai_client.is_enabled() else None,
        }

    app.include_router(internal.router)
    return app


app = create_app()
