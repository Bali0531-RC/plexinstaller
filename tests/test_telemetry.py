"""Tests for telemetry_client.py — redaction, session lifecycle, payload assembly."""

from pathlib import Path
from unittest import mock

from telemetry_client import TelemetryClient, TelemetrySummary, _redact

# ---------------------------------------------------------------------------
# _redact
# ---------------------------------------------------------------------------

class TestRedact:
    def test_redacts_mongo_uri(self):
        text = "mongodb://admin:s3cret@db.host:27017/mydb"
        result = _redact(text)
        assert "admin" not in result
        assert "s3cret" not in result
        assert "[REDACTED]" in result

    def test_redacts_mongo_srv_uri(self):
        text = "mongodb+srv://user:pass@cluster.example.com/db"
        result = _redact(text)
        assert "user" not in result
        assert "pass" not in result

    def test_redacts_password_field(self):
        text = "password=hunter2"
        assert "hunter2" not in _redact(text)

    def test_redacts_token_field(self):
        text = "token: abc123def456"
        assert "abc123def456" not in _redact(text)

    def test_redacts_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9"
        assert "eyJhbGciOiJIUzI1NiJ9" not in _redact(text)

    def test_preserves_safe_text(self):
        text = "Installing plextickets on port 3000"
        assert _redact(text) == text

    def test_redacts_api_key(self):
        text = "api_key=ABCDEF123456"
        assert "ABCDEF123456" not in _redact(text)


# ---------------------------------------------------------------------------
# TelemetrySummary dataclass
# ---------------------------------------------------------------------------

class TestTelemetrySummary:
    def test_construction(self):
        summary = TelemetrySummary(
            session_id="20260101-120000-plextickets-default",
            status="success",
            failure_step=None,
            error=None,
            log_path=Path("/tmp/test.log"),
            events=[],
        )
        assert summary.session_id == "20260101-120000-plextickets-default"
        assert summary.status == "success"
        assert summary.failure_step is None
        assert summary.events == []

    def test_construction_with_failure(self):
        summary = TelemetrySummary(
            session_id="sess1",
            status="failure",
            failure_step="install_node",
            error="node not found",
            log_path=None,
            events=[{"step": "install_node", "status": "fail"}],
        )
        assert summary.failure_step == "install_node"
        assert summary.error == "node not found"
        assert len(summary.events) == 1


# ---------------------------------------------------------------------------
# TelemetryClient session lifecycle
# ---------------------------------------------------------------------------

class TestTelemetryClientSession:
    def _make_client(self, tmp_path: Path, enabled: bool = True) -> TelemetryClient:
        return TelemetryClient(
            endpoint="https://telemetry.example.com",
            log_dir=tmp_path / "logs",
            paste_endpoint="https://paste.example.com",
            enabled=enabled,
        )

    def test_start_session_creates_log_file_parent(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        session_id = client.start_session("plextickets", "default")
        assert session_id != ""
        assert "plextickets" in session_id
        assert client.log_path is not None
        assert client.log_path.parent.exists()

    def test_start_session_disabled_returns_empty(self, tmp_path: Path):
        client = self._make_client(tmp_path, enabled=False)
        assert client.start_session("plextickets", "default") == ""

    def test_log_step_records_event(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install_deps", "ok", "all packages installed")
        assert len(client._events) == 1
        assert client._events[0]["step"] == "install_deps"
        assert client._events[0]["status"] == "ok"

    def test_log_step_redacts_sensitive_detail(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("configure_db", "ok", "mongodb://admin:secret@host/db")
        assert "secret" not in client._events[0]["detail"]

    def test_log_step_noop_when_disabled(self, tmp_path: Path):
        client = self._make_client(tmp_path, enabled=False)
        client.log_step("step", "ok")
        assert len(client._events) == 0

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_returns_summary(self, mock_post, tmp_path: Path):
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install", "ok")

        summary = client.finish_session("success")

        assert summary is not None
        assert summary.status == "success"
        assert len(summary.events) == 1
        assert summary.failure_step is None

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_posts_payload(self, mock_post, tmp_path: Path):
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.finish_session("success")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["product"] == "plextickets"
        assert payload["status"] == "success"

    def test_finish_session_disabled_returns_none(self, tmp_path: Path):
        client = self._make_client(tmp_path, enabled=False)
        assert client.finish_session("success") is None

    def test_write_line_writes_to_log_file(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("test_step", "ok", "detail info")

        assert client.log_path is not None
        log_content = client.log_path.read_text()
        assert "test_step" in log_content
