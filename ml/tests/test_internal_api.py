"""The internal ML API — the contract the Go gateway codes against.

Three things must hold or the gateway breaks in ways that are hard to see from the UI:
the analyze stream is well-formed NDJSON ending in exactly one terminal event, the advisory
response carries all three markdown fields, and the shared-secret check is enforced when
configured.
"""
import json

import pytest

from app.config import settings


def _events(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_health_reports_capability_flags(client):
    body = client.get("/health").json()
    assert body["ok"] is True
    assert body["service"] == "ml"
    assert body["mock_inference"] is True     # set by the test env
    assert body["llm_enabled"] is False       # the suite never calls out
    assert body["model"] is None


def test_analyze_streams_progress_then_one_result(client, tmp_path):
    img = tmp_path / "up.jpg"
    img.write_bytes(b"\xff\xd8fake")

    response = client.post("/internal/analyze", json={
        "case_id": "case-test-1", "images": {"up": str(img)},
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")

    events = _events(response)
    assert events[-1]["type"] == "result"
    assert events[-1]["dataset_id"] == "case-test-1"
    assert all(e["type"] == "progress" for e in events[:-1])

    pcts = [e["pct"] for e in events[:-1]]
    assert pcts == sorted(pcts) and pcts[-1] == 100
    assert all(e["stage"] for e in events[:-1])

    # MOCK mode copies a precomputed dataset into results/<case_id>/
    assert (settings.results_dir / "case-test-1" / "detections.json").exists()


def test_analyze_rejects_an_empty_capture(client):
    assert client.post("/internal/analyze",
                       json={"case_id": "c", "images": {}}).status_code == 422


def test_analyze_rejects_an_unknown_view_key(client, tmp_path):
    img = tmp_path / "x.jpg"
    img.write_bytes(b"x")
    response = client.post("/internal/analyze", json={
        "case_id": "c", "images": {"selfie": str(img)},
    })
    assert response.status_code == 422


def test_analyze_reports_failures_as_a_terminal_error_event(client, monkeypatch, tmp_path):
    from app.services import inference_adapter

    def _boom(req, on_progress=None):
        raise RuntimeError("model weights missing")

    monkeypatch.setattr(inference_adapter, "run_inference", _boom)
    img = tmp_path / "up.jpg"
    img.write_bytes(b"x")
    events = _events(client.post("/internal/analyze", json={
        "case_id": "case-bad", "images": {"up": str(img)},
    }))
    assert events[-1] == {"type": "error", "message": "model weights missing"}


def test_advisory_returns_all_three_fields_and_telemetry(client, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    (tmp_path / "case-adv").mkdir()
    (tmp_path / "case-adv" / "detections.json").write_text(
        json.dumps({"teeth": {"11": {"fdi": 11, "severity": 6}}}), encoding="utf-8"
    )

    body = client.post("/internal/advisory", json={
        "case_id": "case-adv", "dataset_id": "case-adv", "patient_name": "Anak A",
        "anamnesa": {"lokasi": "Gigi depan atas"},
    }).json()

    for key in ("diagnosis_md", "recommendation_md", "sanity_md"):
        assert body[key].lstrip().startswith("#")
    assert body["meta"]["llm_enabled"] is False
    assert body["meta"]["sanity_ok"] is True
    assert body["meta"]["moderation"]["checked"] is False   # disabled in tests


def test_advisory_degrades_when_detections_are_missing(client, tmp_path, monkeypatch):
    """The clinically valuable part already succeeded — never fail the case here."""
    monkeypatch.setattr(settings, "results_dir", tmp_path)
    body = client.post("/internal/advisory", json={
        "case_id": "nope", "dataset_id": "nope", "anamnesa": {},
    }).json()
    assert body["diagnosis_md"].strip()


def test_moderation_is_off_by_default(client):
    body = client.post("/internal/moderate", json={"text": "sakit gigi"}).json()
    assert body == {"flagged": False, "categories": [], "checked": False}


# ── access control ───────────────────────────────────────────────────────────────

@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(settings, "internal_api_key", "s3cret")


def test_internal_routes_require_the_shared_secret_when_configured(client, keyed):
    assert client.post("/internal/moderate", json={"text": "x"}).status_code == 401
    assert client.post("/internal/moderate", json={"text": "x"},
                       headers={"X-Internal-Key": "wrong"}).status_code == 401
    assert client.post("/internal/moderate", json={"text": "x"},
                       headers={"X-Internal-Key": "s3cret"}).status_code == 200


def test_health_stays_open_for_load_balancer_probes(client, keyed):
    assert client.get("/health").status_code == 200
