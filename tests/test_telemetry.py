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

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_with_failure(self, mock_post, tmp_path: Path):
        """failure_step and error are propagated to the summary."""
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install_deps", "ok")
        client.log_step("install_node", "fail", "node not found")

        summary = client.finish_session("failure", failure_step="install_node", error="node not found")

        assert summary is not None
        assert summary.status == "failure"
        assert summary.failure_step == "install_node"
        assert summary.error == "node not found"
        assert len(summary.events) == 2

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_writes_error_to_log(self, mock_post, tmp_path: Path):
        """Session error is written to the log file."""
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.finish_session("failure", error="crash")

        assert client.log_path is not None
        content = client.log_path.read_text()
        assert "crash" in content

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_redacts_error(self, mock_post, tmp_path: Path):
        """Sensitive data in error is redacted in the log file."""
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.finish_session("failure", error="password=hunter2")

        content = client.log_path.read_text()
        assert "hunter2" not in content

    @mock.patch("telemetry_client.requests.post")
    def test_finish_session_cannot_be_called_twice(self, mock_post, tmp_path: Path):
        """Second finish_session returns None because session is no longer active."""
        mock_post.return_value = mock.MagicMock(status_code=200)
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        first = client.finish_session("success")
        second = client.finish_session("success")

        assert first is not None
        assert second is None

    @mock.patch("telemetry_client.requests.post")
    def test_post_failure_is_silent(self, mock_post, tmp_path: Path):
        """Network error during post_payload does not raise."""
        import requests as req

        mock_post.side_effect = req.RequestException("network down")
        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        summary = client.finish_session("success")
        assert summary is not None
        assert summary.status == "success"

    def test_log_step_without_session_is_noop(self, tmp_path: Path):
        """Calling log_step before start_session does nothing."""
        client = self._make_client(tmp_path)
        client.log_step("step", "ok", "detail")
        assert len(client._events) == 0

    def test_session_id_format(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        sid = client.start_session("plexstore", "prod")
        # format: YYYYMMDD-HHMMSS-product-instance
        parts = sid.split("-")
        assert len(parts) == 4
        assert parts[2] == "plexstore"
        assert parts[3] == "prod"


# ---------------------------------------------------------------------------
# TelemetryClient.share_log
# ---------------------------------------------------------------------------


class TestShareLog:
    def _make_client(self, tmp_path: Path, enabled: bool = True) -> TelemetryClient:
        return TelemetryClient(
            endpoint="https://telemetry.example.com",
            log_dir=tmp_path / "logs",
            paste_endpoint="https://paste.example.com",
            enabled=enabled,
        )

    def test_returns_none_when_disabled(self, tmp_path: Path):
        client = self._make_client(tmp_path, enabled=False)
        assert client.share_log() is None

    def test_returns_none_when_no_log_file(self, tmp_path: Path):
        client = self._make_client(tmp_path)
        # log_path is None before start_session
        assert client.share_log() is None

    def test_returns_none_when_no_paste_endpoint(self, tmp_path: Path):
        client = TelemetryClient(
            endpoint="https://telemetry.example.com",
            log_dir=tmp_path / "logs",
            paste_endpoint="",
            enabled=True,
        )
        assert client.share_log() is None

    @mock.patch("telemetry_client.requests.post")
    def test_returns_url_from_response(self, mock_post, tmp_path: Path):
        """share_log returns the url from the paste service response."""
        mock_post.return_value = mock.MagicMock(
            status_code=200,
            json=mock.MagicMock(return_value={"url": "https://paste.example.com/abc"}),
        )
        mock_post.return_value.raise_for_status = mock.MagicMock()

        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install", "ok")

        result = client.share_log()
        assert result == "https://paste.example.com/abc"

    @mock.patch("telemetry_client.requests.post")
    def test_returns_key_fallback(self, mock_post, tmp_path: Path):
        """share_log falls back to 'key' when 'url' is not present."""
        mock_post.return_value = mock.MagicMock(
            status_code=200,
            json=mock.MagicMock(return_value={"key": "abc123"}),
        )
        mock_post.return_value.raise_for_status = mock.MagicMock()

        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install", "ok")

        result = client.share_log()
        assert result == "abc123"

    @mock.patch("telemetry_client.requests.post")
    def test_returns_none_on_missing_keys(self, mock_post, tmp_path: Path):
        """Neither url nor key → returns None, not 'None' string."""
        mock_post.return_value = mock.MagicMock(
            status_code=200,
            json=mock.MagicMock(return_value={}),
        )
        mock_post.return_value.raise_for_status = mock.MagicMock()

        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install", "ok")

        result = client.share_log()
        assert result is None  # not "None" string

    @mock.patch("telemetry_client.requests.post")
    def test_returns_none_on_network_error(self, mock_post, tmp_path: Path):
        """Network error during share_log returns None gracefully."""
        import requests as req

        mock_post.side_effect = req.RequestException("timeout")

        client = self._make_client(tmp_path)
        client.start_session("plextickets", "default")
        client.log_step("install", "ok")

        assert client.share_log() is None


# ---------------------------------------------------------------------------
# _redact edge cases
# ---------------------------------------------------------------------------


class TestRedactExtra:
    def test_multiple_sensitive_fields_in_one_string(self):
        text = "password=abc token=xyz api_key=123"
        result = _redact(text)
        assert "abc" not in result
        assert "xyz" not in result
        assert "123" not in result

    def test_case_insensitive_password(self):
        text = "PASSWORD=secret123"
        assert "secret123" not in _redact(text)

    def test_passwd_variant(self):
        text = "passwd=mypass"
        assert "mypass" not in _redact(text)

    def test_secret_field(self):
        text = "secret: top_secret_value"
        assert "top_secret_value" not in _redact(text)

    def test_apikey_no_underscore(self):
        text = "apikey=KEYVALUE"
        assert "KEYVALUE" not in _redact(text)

    def test_empty_string(self):
        assert _redact("") == ""

    def test_multiline_redaction(self):
        text = "line1\npassword=secret\nline3"
        result = _redact(text)
        assert "secret" not in result
        assert "line1" in result
        assert "line3" in result
