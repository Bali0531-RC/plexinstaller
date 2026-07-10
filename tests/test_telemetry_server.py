"""Security and retention tests for the telemetry FastAPI server."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")
from fastapi.testclient import TestClient

SERVER_PATH = Path(__file__).parents[1] / "telemetry" / "server.py"
API_KEY = "test-telemetry-key-123456"


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEMETRY_API_KEY", API_KEY)
    monkeypatch.setenv("TELEMETRY_MAX_EVENTS_BYTES", "4096")
    monkeypatch.setenv("TELEMETRY_MAX_LOG_BYTES", "100")
    monkeypatch.setenv("TELEMETRY_MAX_LOG_FILES", "2")
    spec = importlib.util.spec_from_file_location("telemetry_server_test", SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module._rate_limit_store.clear()
    return module


@pytest.fixture
def client(server):
    return TestClient(server.app)


def _payload(**overrides):
    payload = {
        "session_id": "20260710-120000-plexstore-prod-a1b2c3d4",
        "product": "plexstore",
        "instance": "prod",
        "status": "success",
        "failure_step": None,
        "error": None,
        "events": [],
        "log": "safe log",
        "timestamp": "2026-07-10T12:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _headers(key: str = API_KEY):
    return {"X-API-Key": key}


class TestAuthentication:
    def test_stats_are_public_and_hide_raw_sessions(self, server, client):
        server.STATS_FILE.write_text(
            json.dumps(
                {
                    "success": 2,
                    "failure": 1,
                    "uncompleted": 1,
                    "failures_by_step": {"extract": 1},
                    "most_recent": [{"session_id": "secret-session"}],
                }
            )
        )
        response = client.get("/stats")
        assert response.status_code == 200
        assert response.json()["total"] == 4
        assert "most_recent" not in response.json()
        assert "secret-session" not in response.text

    @pytest.mark.parametrize("path", ["/events", "/logs", "/logs/session"])
    def test_raw_get_apis_require_key(self, client, path):
        assert client.get(path).status_code == 401
        assert client.get(path, headers=_headers("wrong-key")).status_code == 401

    def test_event_ingest_requires_key(self, client):
        assert client.post("/events", json=_payload()).status_code == 401
        assert client.post("/events", json=_payload(), headers=_headers()).status_code == 200

    def test_raw_access_is_disabled_if_server_has_no_key(self, server, client, monkeypatch):
        monkeypatch.setattr(server, "TELEMETRY_API_KEY", "")
        assert client.get("/events").status_code == 503
        assert client.post("/events", json=_payload()).status_code == 200

    def test_constant_time_compare_is_used(self, server, client, monkeypatch):
        calls = []
        real_compare = server.hmac.compare_digest

        def compare(left, right):
            calls.append((left, right))
            return real_compare(left, right)

        monkeypatch.setattr(server.hmac, "compare_digest", compare)
        assert client.get("/events", headers=_headers()).status_code == 200
        assert calls


class TestValidationAndStorage:
    def test_payload_rejects_oversized_fields_and_unknown_status(self, client):
        assert client.post("/events", json=_payload(product="x" * 65), headers=_headers()).status_code == 422
        assert client.post("/events", json=_payload(status="other"), headers=_headers()).status_code == 422
        assert (
            client.post(
                "/events",
                json=_payload(events=[{"timestamp": "t", "step": "s", "status": "ok", "detail": ""}] * 201),
                headers=_headers(),
            ).status_code
            == 422
        )
        assert client.post("/events", json={**_payload(), "unexpected": True}, headers=_headers()).status_code == 422

    def test_chunked_body_is_bounded_by_actual_bytes(self, server, client):
        oversized = b"x" * (server.MAX_REQUEST_BYTES + 1)

        def chunks():
            for offset in range(0, len(oversized), 4096):
                yield oversized[offset : offset + 4096]

        response = client.post(
            "/events",
            content=chunks(),
            headers={**_headers(), "Content-Type": "application/json", "Transfer-Encoding": "chunked"},
        )
        assert response.status_code == 413

    def test_event_list_limit_is_bounded(self, client):
        assert client.get("/events?limit=0", headers=_headers()).status_code == 422
        assert client.get("/events?limit=201", headers=_headers()).status_code == 422

    def test_jsonl_listing_skips_malformed_lines(self, server, client):
        server.EVENTS_FILE.write_text('{"session_id":"one"}\nnot-json\n[]\n{"session_id":"two"}\n')
        response = client.get("/events?limit=10", headers=_headers())
        assert response.status_code == 200
        assert [event["session_id"] for event in response.json()] == ["one", "two"]

    def test_event_and_log_files_are_private(self, server, client):
        response = client.post("/events", json=_payload(), headers=_headers())
        assert response.status_code == 200
        log_path = server.LOG_DIR / f"{_payload()['session_id']}.log"
        assert server.EVENTS_FILE.stat().st_mode & 0o777 == 0o600
        assert server.STATS_FILE.stat().st_mode & 0o777 == 0o600
        assert log_path.stat().st_mode & 0o777 == 0o600
        assert server.DATA_DIR.stat().st_mode & 0o777 == 0o700
        assert server.LOG_DIR.stat().st_mode & 0o777 == 0o700

    def test_log_retention_caps_file_count_and_disk_use(self, server):
        for index, size in enumerate((40, 40, 40)):
            path = server.LOG_DIR / f"session-{index}.log"
            path.write_text("x" * size)
            os.utime(path, (index + 1, index + 1))
        server._prune_logs()
        remaining = list(server.LOG_DIR.glob("*.log"))
        assert len(remaining) <= 2
        assert sum(path.stat().st_size for path in remaining) <= 100

    def test_event_archive_rotates_at_cap(self, server):
        server.EVENTS_FILE.write_text("x" * (server.MAX_EVENTS_FILE_BYTES - 5))
        payload = server.TelemetryPayload.model_validate(_payload(log=None))
        server._append_event(payload)
        assert server.EVENTS_FILE.with_suffix(".jsonl.1").exists()
        assert server.EVENTS_FILE.stat().st_size <= server.MAX_EVENTS_FILE_BYTES
