"""Boot the backend for Playwright E2E: fresh seeded SQLite DB + MOCK inference + uvicorn.

Playwright's webServer runs this. Env (DATABASE_URL, MOCK_INFERENCE=1, MOCK_STEP_DELAY=0,
JWT_SECRET, CORS_ORIGINS, RESULTS_DIR) is set by playwright.config. We drop any prior test
DB so every run starts from the seeded 2 accounts + 4 demo cases, then serve on :8000.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# sensible E2E defaults if not provided by the caller
os.environ.setdefault("MOCK_INFERENCE", "1")
os.environ.setdefault("MOCK_STEP_DELAY", "0")
os.environ.setdefault("DATABASE_URL", "sqlite:///./data/e2e.db")
os.environ.setdefault("JWT_SECRET", "e2e-secret-at-least-32-bytes-long-00000")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
# E2E asserts on the deterministic LLM stub — never call the real API from Playwright.
os.environ["LLM_ENABLED"] = "0"
os.environ["RAG_ENABLED"] = "0"

from app.config import settings  # noqa: E402


def _reset_db() -> None:
    p = settings.sqlite_path
    if p is not None and p.exists():
        p.unlink()


def main() -> None:
    _reset_db()
    import seed  # noqa: E402
    seed.run()

    import uvicorn  # noqa: E402
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    main()
