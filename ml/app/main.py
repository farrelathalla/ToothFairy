"""FastAPI application entrypoint.

    uvicorn backend.app.main:app --reload --port 8000   # from the repo root

Phase 0: app boots, CORS, /health, /media static mount. Routers (auth, accounts,
cases) are registered in later phases.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="ToothFairy API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve uploaded raw photos (created lazily; mount is safe even if empty).
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(settings.upload_dir)), name="media")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "mock_inference": settings.mock_inference}

    from .routers import accounts, auth, cases

    app.include_router(auth.router)
    app.include_router(accounts.router)
    app.include_router(cases.router)

    return app


app = create_app()
