"""Shared pytest fixtures.

Env is configured BEFORE importing the app so `settings` picks up throwaway directories and
MOCK_INFERENCE. This service is stateless, so there is no schema to reset between tests.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Make the `app` package importable (ml/ is the parent of this tests/ dir).
ML_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ML_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="toothfairy-test-"))
os.environ.setdefault("UPLOAD_DIR", str(_TMP / "uploads"))
os.environ.setdefault("RESULTS_DIR", str(_TMP / "results"))
os.environ.setdefault("MOCK_INFERENCE", "1")
os.environ.setdefault("MOCK_STEP_DELAY", "0")  # no artificial delay in tests

# HARD off, not setdefault: a developer's ml/.env may carry LLM_ENABLED=1 + a real key, and
# pydantic-settings would read it. The suite must never touch the OpenAI API — tests that
# exercise the live path (test_diagnosis_agent) flip these per-test with a fake client.
os.environ["LLM_ENABLED"] = "0"
os.environ["RAG_ENABLED"] = "0"
os.environ["MODERATION_ENABLED"] = "0"
os.environ["OPENAI_API_KEY"] = ""
os.environ["INTERNAL_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def sample_detections() -> dict:
    """A detections.json-shaped fixture covering the interesting per-tooth cases.

    Two D6 teeth that differ in extent/darkness/lesion count (the "Idem" trap), one hidden
    panoramic-only lesion, one low-evidence tooth on an interpolated FDI box, one healthy
    tooth, and one tooth both detectors call absent.
    """
    return {
        "meta": {
            "views": ["up"],
            "has_panoramic": True,
            "hidden_fdi": ["36"],
            "missing_fdi": [28],
            "predicted_fdi": ["22"],
        },
        "teeth": {
            "11": {
                "fdi": 11, "present": True, "severity": 6, "grade_source": "rfdetr+seg",
                "caries_ratio": 0.34, "rel_dark": 0.78, "pano_grade": 0, "pano_ratio": 0.0,
                "sources": ["seg", "rfdetr"], "fdi_predicted": False, "hidden": False,
                "lesions": [
                    {"u": 0.5, "v": 0.5, "r": 0.6, "type": "Cavity", "grade": 6,
                     "conf": 0.55},
                    {"u": 0.2, "v": 0.8, "r": 0.3, "type": "Caries", "grade": 4,
                     "conf": 0.41},
                ],
            },
            "21": {
                "fdi": 21, "present": True, "severity": 6, "grade_source": "rfdetr",
                "caries_ratio": 0.08, "rel_dark": 0.25, "pano_grade": 0, "pano_ratio": 0.0,
                "sources": ["rfdetr"], "fdi_predicted": False, "hidden": False,
                "lesions": [
                    {"u": 0.52, "v": 0.48, "r": 0.25, "type": "Caries", "grade": 6,
                     "conf": 0.47},
                ],
            },
            "22": {
                "fdi": 22, "present": True, "severity": 2, "grade_source": "seg",
                "caries_ratio": 0.03, "rel_dark": 0.12, "pano_grade": 0, "pano_ratio": 0.0,
                "sources": ["seg"], "fdi_predicted": True, "hidden": False,
                "lesions": [
                    {"u": 0.9, "v": 0.1, "r": 0.1, "type": "Caries", "grade": 2,
                     "conf": 0.15},
                ],
            },
            "36": {
                "fdi": 36, "present": True, "severity": 4, "grade_source": "panoramic",
                "caries_ratio": 0.0, "rel_dark": 0.0, "pano_grade": 4, "pano_ratio": 0.031,
                "sources": ["panoramic"], "fdi_predicted": False, "hidden": True,
                "lesions": [
                    {"u": 0.5, "v": 0.5, "r": 0.2, "type": "Caries", "grade": 4,
                     "conf": 0.5},
                ],
            },
            "47": {
                "fdi": 47, "present": True, "severity": 0, "grade_source": "",
                "caries_ratio": 0.0, "rel_dark": 0.0, "sources": [], "lesions": [],
            },
        },
    }
