"""Shared pytest fixtures.

Env is configured BEFORE importing the app so `settings` picks up a throwaway SQLite
file and MOCK_INFERENCE. Each test gets a fresh schema.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the `app` package importable (backend/ is the parent of this tests/ dir).
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# Point config at a temp DB + mock inference, before app import.
_TMP = Path(tempfile.mkdtemp(prefix="toothfairy-test-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(_TMP / 'test.db').as_posix()}")
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("RESULTS_DIR", str(_TMP / "results"))
os.environ.setdefault("MOCK_INFERENCE", "1")
os.environ.setdefault("MOCK_STEP_DELAY", "0")  # no artificial delay in tests
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-bytes-long-000")

# HARD off, not setdefault: a developer's backend/.env may carry LLM_ENABLED=1 + a real key,
# and pydantic-settings would read it. The suite must never touch the Anthropic API — tests
# that exercise the live path (test_diagnosis_agent) flip these per-test with a fake client.
os.environ["LLM_ENABLED"] = "0"
os.environ["RAG_ENABLED"] = "0"
os.environ["ANTHROPIC_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_schema():
    """Drop + recreate all tables around every test for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    """A DB session for service-layer tests."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
