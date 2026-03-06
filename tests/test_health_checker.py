"""Tests for health_checker.py — SelfTestResult, probe_http, check_node_version."""

import subprocess
from pathlib import Path
from unittest import mock

from health_checker import HealthChecker, SelfTestResult
from utils import ColorPrinter, SystemdManager

# ---------------------------------------------------------------------------
# SelfTestResult dataclass
# ---------------------------------------------------------------------------


class TestSelfTestResult:
    def test_default_fields(self):
        r = SelfTestResult(name="test", status="pass")
        assert r.name == "test"
        assert r.status == "pass"
        assert r.detail == ""
        assert r.hint == ""

    def test_with_detail_and_hint(self):
        r = SelfTestResult(
            name="node version",
            status="fail",
            detail="v14.0.0 (needs >= 18)",
            hint="Run: nvm install 18",
        )
        assert r.detail == "v14.0.0 (needs >= 18)"
        assert r.hint == "Run: nvm install 18"

    def test_warn_status(self):
        r = SelfTestResult(name="dns", status="warn", detail="NXDOMAIN")
        assert r.status == "warn"


# ---------------------------------------------------------------------------
# HealthChecker.probe_http
# ---------------------------------------------------------------------------


class TestProbeHttp:
    def test_successful_probe(self):
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.reason = "OK"

        mock_conn = mock.MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        with mock.patch("health_checker.http.client.HTTPConnection", return_value=mock_conn):
            ok, detail = HealthChecker.probe_http("localhost", 3000)

        assert ok is True
        assert "200" in detail
        assert "OK" in detail

    def test_connection_refused(self):
        with mock.patch(
            "health_checker.http.client.HTTPConnection",
            side_effect=ConnectionRefusedError("Connection refused"),
        ):
            ok, detail = HealthChecker.probe_http("localhost", 9999)

        assert ok is False
        assert "refused" in detail.lower() or "Connection refused" in detail


# ---------------------------------------------------------------------------
# HealthChecker.check_node_version
# ---------------------------------------------------------------------------


class TestCheckNodeVersion:
    def _make_checker(self) -> HealthChecker:
        return HealthChecker(
            printer=ColorPrinter(),
            systemd=SystemdManager(),
            install_dir=Path("/tmp/plex"),
            node_min_version=18,
            nginx_available=Path("/etc/nginx/sites-available"),
            nginx_enabled=Path("/etc/nginx/sites-enabled"),
        )

    def test_node_meets_minimum(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="v20.10.0\n")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is True
        assert "20.10.0" in detail

    def test_node_below_minimum(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="v14.17.0\n")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is False
        assert "14.17.0" in detail

    def test_node_not_installed(self):
        hc = self._make_checker()
        with mock.patch(
            "health_checker.subprocess.run",
            side_effect=FileNotFoundError("node"),
        ):
            ok, detail = hc.check_node_version()
        assert ok is False

    def test_node_exact_minimum(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="v18.0.0\n")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is True

    def test_node_command_fails(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="command failed")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is False
        assert "failed" in detail.lower()


# ---------------------------------------------------------------------------
# HealthChecker.print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def _make_checker(self) -> HealthChecker:
        return HealthChecker(
            printer=ColorPrinter(),
            systemd=SystemdManager(),
            install_dir=Path("/tmp/plex"),
            node_min_version=18,
            nginx_available=Path("/etc/nginx/sites-available"),
            nginx_enabled=Path("/etc/nginx/sites-enabled"),
        )

    def test_all_pass(self, capsys):
        hc = self._make_checker()
        results = [
            SelfTestResult(name="test1", status="pass", detail="ok"),
            SelfTestResult(name="test2", status="pass", detail="good"),
        ]
        hc.print_summary(results)
        captured = capsys.readouterr()
        assert "passed" in captured.err.lower()

    def test_with_failures(self, capsys):
        hc = self._make_checker()
        results = [
            SelfTestResult(name="test1", status="pass", detail="ok"),
            SelfTestResult(name="test2", status="fail", detail="broken", hint="fix it"),
        ]
        hc.print_summary(results)
        captured = capsys.readouterr()
        assert "1 failure" in captured.err.lower()

    def test_with_warnings(self, capsys):
        hc = self._make_checker()
        results = [
            SelfTestResult(name="dns", status="warn", detail="NXDOMAIN"),
        ]
        hc.print_summary(results)
        captured = capsys.readouterr()
        assert "1 warning" in captured.err.lower()
