"""Additional branch-coverage tests for telemetry/server.py and telemetry_client.py."""

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("pydantic")
from fastapi import HTTPException
from fastapi.testclient import TestClient

from telemetry_client import TelemetryClient

SERVER_PATH = Path(__file__).parents[1] / "telemetry" / "server.py"
API_KEY = "test-telemetry-key-123456"


def _load_server(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SERVER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TELEMETRY_API_KEY", API_KEY)
    monkeypatch.setenv("TELEMETRY_MAX_EVENTS_BYTES", "4096")
    monkeypatch.setenv("TELEMETRY_MAX_LOG_BYTES", "100")
    monkeypatch.setenv("TELEMETRY_MAX_LOG_FILES", "2")
    module = _load_server("telemetry_server_coverage_test")
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


class TestSessionValidation:
    def test_invalid_session_id_rejected(self, server):
        with pytest.raises(HTTPException) as exc:
            server._validate_session_id("../etc/passwd")
        assert exc.value.status_code == 400

    def test_get_log_invalid_session_id(self, client):
        response = client.get("/logs/bad!session", headers=_headers())
        assert response.status_code == 400


class TestRateLimit:
    def test_check_rate_limit_raises_when_exceeded(self, server):
        now = time.monotonic()
        server._rate_limit_store["1.2.3.4"] = [now] * server.RATE_LIMIT_MAX
        with pytest.raises(HTTPException) as exc:
            server._check_rate_limit("1.2.3.4")
        assert exc.value.status_code == 429

    def test_middleware_returns_429(self, server, client):
        now = time.monotonic()
        server._rate_limit_store["testclient"] = [now] * server.RATE_LIMIT_MAX
        response = client.get("/stats")
        assert response.status_code == 429
        assert response.json() == {"detail": "Rate limit exceeded"}


class TestMiddlewareContentLength:
    def test_content_length_too_large(self, server, client):
        response = client.get("/stats", headers={"Content-Length": str(server.MAX_REQUEST_BYTES + 1)})
        assert response.status_code == 413

    def test_content_length_invalid(self, client):
        response = client.get("/stats", headers={"Content-Length": "not-a-number"})
        assert response.status_code == 400


class TestLoadStats:
    def test_non_dict_json_returns_defaults(self, server):
        server.STATS_FILE.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        assert server._load_stats() == server._default_stats()

    def test_legacy_other_key_migrated(self, server):
        server.STATS_FILE.write_text(json.dumps({"success": 1, "other": 3, "uncompleted": 2}), encoding="utf-8")
        stats = server._load_stats()
        assert stats["uncompleted"] == 5
        assert "other" not in stats

    def test_corrupt_json_returns_defaults(self, server):
        server.STATS_FILE.write_text("{not json", encoding="utf-8")
        assert server._load_stats() == server._default_stats()


class TestDeriveStats:
    def test_non_dict_failures_by_step_replaced(self, server):
        derived = server._derive_stats({"success": 1, "failures_by_step": ["bad"]})
        assert derived["failures_by_step"] == {}


class TestEventArchive:
    def test_rotate_without_existing_file(self, server):
        assert not server.EVENTS_FILE.exists()
        server._rotate_events_if_needed(server.MAX_EVENTS_FILE_BYTES + 1)
        assert not server.EVENTS_FILE.with_suffix(".jsonl.1").exists()

    def test_oversized_event_rejected(self, server, monkeypatch):
        monkeypatch.setattr(server, "MAX_EVENTS_FILE_BYTES", 8)
        payload = server.TelemetryPayload(**_payload())
        with pytest.raises(HTTPException) as exc:
            server._append_event(payload)
        assert exc.value.status_code == 413


class TestPruneLogs:
    def test_stat_oserror_is_skipped(self, server, monkeypatch):
        (server.LOG_DIR / "a.log").write_text("x", encoding="utf-8")
        original_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self.name == "a.log":
                raise OSError("boom")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        server._prune_logs()
        assert (server.LOG_DIR / "a.log").exists()

    def test_excess_files_removed(self, server):
        for index in range(4):
            path = server.LOG_DIR / f"s{index}.log"
            path.write_text("y" * 10, encoding="utf-8")
        server._prune_logs()
        remaining = list(server.LOG_DIR.glob("*.log"))
        assert len(remaining) == server.MAX_LOG_FILES


class TestJsonlTail:
    def test_open_oserror_returns_empty(self, server, monkeypatch):
        server.EVENTS_FILE.write_text('{"a": 1}\n', encoding="utf-8")
        original_open = Path.open

        def broken_open(self, *args, **kwargs):
            if self.name == server.EVENTS_FILE.name:
                raise OSError("denied")
            return original_open(self, *args, **kwargs)

        monkeypatch.setattr(Path, "open", broken_open)
        assert server._iter_jsonl_tail(server.EVENTS_FILE, 5) == []


class TestIngestBranches:
    def test_failure_with_step_counted(self, client, server):
        payload = _payload(status="failure", failure_step="nginx-setup", log=None)
        response = client.post("/events", json=payload, headers=_headers())
        assert response.status_code == 200
        stats = json.loads(server.STATS_FILE.read_text(encoding="utf-8"))
        assert stats["failures_by_step"]["nginx-setup"] == 1
        assert not (server.LOG_DIR / f"{payload['session_id']}.log").exists()


class TestLogEndpoints:
    def test_list_logs_sorted_and_limited(self, client, server):
        for index in range(3):
            (server.LOG_DIR / f"log{index}.log").write_text("z", encoding="utf-8")
        response = client.get("/logs", params={"limit": 2}, headers=_headers())
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_logs_stat_oserror_skipped(self, client, server, monkeypatch):
        (server.LOG_DIR / "bad.log").write_text("z", encoding="utf-8")
        original_stat = Path.stat

        def flaky_stat(self, *args, **kwargs):
            if self.name == "bad.log":
                raise OSError("boom")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", flaky_stat)
        response = client.get("/logs", headers=_headers())
        assert response.status_code == 200
        assert "bad.log" not in response.json()

    def test_get_log_success(self, client, server):
        (server.LOG_DIR / "session-1.log").write_text("hello", encoding="utf-8")
        response = client.get("/logs/session-1", headers=_headers())
        assert response.status_code == 200
        assert response.json() == {"session_id": "session-1", "log": "hello"}

    def test_get_log_not_found(self, client):
        response = client.get("/logs/missing-session", headers=_headers())
        assert response.status_code == 404

    def test_get_log_read_error(self, client, server, monkeypatch):
        (server.LOG_DIR / "session-2.log").write_text("hello", encoding="utf-8")

        def broken_read_text(self, *args, **kwargs):
            raise OSError("denied")

        monkeypatch.setattr(Path, "read_text", broken_read_text)
        response = client.get("/logs/session-2", headers=_headers())
        assert response.status_code == 500


class TestStartupValidation:
    def test_short_api_key_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("TELEMETRY_API_KEY", "short")
        with pytest.raises(RuntimeError, match="at least 16 characters"):
            _load_server("telemetry_server_short_key_test")

    def test_non_positive_limits_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TELEMETRY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("TELEMETRY_API_KEY", API_KEY)
        monkeypatch.setenv("TELEMETRY_MAX_LOG_FILES", "0")
        with pytest.raises(RuntimeError, match="must be positive"):
            _load_server("telemetry_server_bad_limits_test")


class TestTelemetryClientBranches:
    def _make_client(self, tmp_path: Path, endpoint: str = "https://t.example.com") -> TelemetryClient:
        return TelemetryClient(
            endpoint=endpoint,
            log_dir=tmp_path / "logs",
            paste_endpoint="https://paste.example.com",
            enabled=True,
        )

    def test_read_log_contents_without_session(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        assert client._read_log_contents() == ""

    def test_post_payload_without_endpoint(self, tmp_path: Path, monkeypatch):
        client = self._make_client(tmp_path, endpoint="")

        def fail_post(*args, **kwargs):  # pragma: no cover - must not be called
            raise AssertionError("requests.post should not be invoked")

        monkeypatch.setattr("telemetry_client.requests.post", fail_post)
        client._post_payload({"anything": True})

    def test_write_line_without_log_path(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        client._write_line("ignored")
        assert list((tmp_path / "logs").glob("*.log")) == []
