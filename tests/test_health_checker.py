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


# ---------------------------------------------------------------------------
# HealthChecker.wait_for_tcp_port
# ---------------------------------------------------------------------------


class TestWaitForTcpPort:
    def test_returns_true_when_port_open(self):
        mock_sock = mock.MagicMock()
        mock_sock.__enter__ = mock.MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = mock.MagicMock(return_value=False)

        with mock.patch("health_checker.socket.create_connection", return_value=mock_sock):
            assert HealthChecker.wait_for_tcp_port("localhost", 3000, timeout_seconds=2) is True

    def test_returns_false_when_port_never_opens(self):
        with mock.patch(
            "health_checker.socket.create_connection",
            side_effect=OSError("refused"),
        ):
            with mock.patch("health_checker.time.sleep"):
                with mock.patch("health_checker.time.time", side_effect=[0, 0.5, 999]):
                    assert HealthChecker.wait_for_tcp_port("localhost", 3000, timeout_seconds=1) is False

    def test_returns_true_after_retries(self):
        """Port opens on second attempt."""
        mock_sock = mock.MagicMock()
        mock_sock.__enter__ = mock.MagicMock(return_value=mock_sock)
        mock_sock.__exit__ = mock.MagicMock(return_value=False)

        call_count = 0

        def mock_connect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise OSError("not yet")
            return mock_sock

        with mock.patch("health_checker.socket.create_connection", side_effect=mock_connect):
            with mock.patch("health_checker.time.sleep"):
                with mock.patch("health_checker.time.time", side_effect=[0, 0.5, 0.8, 1.0]):
                    assert HealthChecker.wait_for_tcp_port("localhost", 3000, timeout_seconds=5) is True


# ---------------------------------------------------------------------------
# HealthChecker.probe_http — extra
# ---------------------------------------------------------------------------


class TestProbeHttpExtra:
    def test_timeout(self):
        with mock.patch(
            "health_checker.http.client.HTTPConnection",
            side_effect=TimeoutError("timed out"),
        ):
            ok, detail = HealthChecker.probe_http("localhost", 9999, timeout=1)
        assert ok is False
        assert "timed out" in detail

    def test_with_custom_path(self):
        mock_resp = mock.MagicMock()
        mock_resp.status = 200
        mock_resp.reason = "OK"

        mock_conn = mock.MagicMock()
        mock_conn.getresponse.return_value = mock_resp

        with mock.patch("health_checker.http.client.HTTPConnection", return_value=mock_conn):
            ok, detail = HealthChecker.probe_http("localhost", 3000, path="/health")

        mock_conn.request.assert_called_once_with("GET", "/health")
        assert ok is True


# ---------------------------------------------------------------------------
# HealthChecker.check_node_version — extra
# ---------------------------------------------------------------------------


class TestCheckNodeVersionExtra:
    def _make_checker(self) -> HealthChecker:
        return HealthChecker(
            printer=ColorPrinter(),
            systemd=SystemdManager(),
            install_dir=Path("/tmp/plex"),
            node_min_version=18,
            nginx_available=Path("/etc/nginx/sites-available"),
            nginx_enabled=Path("/etc/nginx/sites-enabled"),
        )

    def test_node_just_below_minimum(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="v17.9.9\n")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is False
        assert "17.9.9" in detail

    def test_node_timeout(self):
        hc = self._make_checker()
        with mock.patch(
            "health_checker.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="node", timeout=10),
        ):
            ok, detail = hc.check_node_version()
        assert ok is False
        assert "timed out" in detail.lower() or "TimeoutExpired" in detail

    def test_high_major_version(self):
        hc = self._make_checker()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="v22.5.1\n")
        with mock.patch("health_checker.subprocess.run", return_value=result):
            ok, detail = hc.check_node_version()
        assert ok is True
        assert "22.5.1" in detail


# ---------------------------------------------------------------------------
# HealthChecker.system_health_check
# ---------------------------------------------------------------------------


class TestSystemHealthCheck:
    def _make_checker(self, install_dir: Path) -> HealthChecker:
        return HealthChecker(
            printer=ColorPrinter(),
            systemd=SystemdManager(),
            install_dir=install_dir,
            node_min_version=18,
            nginx_available=Path("/etc/nginx/sites-available"),
            nginx_enabled=Path("/etc/nginx/sites-enabled"),
        )

    def test_disk_fallback_to_root(self, tmp_path: Path):
        """If install_dir doesn't exist, statvfs is called on /."""
        install_dir = tmp_path / "nonexistent"
        hc = self._make_checker(install_dir)

        fake_stat = mock.MagicMock()
        fake_stat.f_bavail = 50 * 1024 * 256  # plenty free
        fake_stat.f_frsize = 4096
        fake_stat.f_blocks = 100 * 1024 * 256

        with mock.patch("health_checker.os.system"):
            with mock.patch("health_checker.os.statvfs", return_value=fake_stat) as mock_statvfs:
                with mock.patch("health_checker.subprocess.run"):
                    hc.system_health_check()

        # Should fall back to "/" since install_dir doesn't exist
        mock_statvfs.assert_called_once_with(Path("/"))

    def test_healthy_disk_no_warning(self, tmp_path: Path, capsys):
        """Disk under 80% usage → success message."""
        install_dir = tmp_path / "plex"
        install_dir.mkdir()
        hc = self._make_checker(install_dir)

        fake_stat = mock.MagicMock()
        fake_stat.f_bavail = 80 * 1024 * 256  # 80% free
        fake_stat.f_frsize = 4096
        fake_stat.f_blocks = 100 * 1024 * 256

        with mock.patch("health_checker.os.system"):
            with mock.patch("health_checker.os.statvfs", return_value=fake_stat):
                with mock.patch("health_checker.subprocess.run"):
                    hc.system_health_check()

        captured = capsys.readouterr()
        assert "healthy" in captured.err.lower()

    def test_services_checked_when_dir_exists(self, tmp_path: Path, capsys):
        """Product dirs are iterated and service status is checked."""
        install_dir = tmp_path / "plex"
        install_dir.mkdir()
        (install_dir / "plextickets").mkdir()
        (install_dir / "backups").mkdir()  # should be skipped

        hc = self._make_checker(install_dir)

        fake_stat = mock.MagicMock()
        fake_stat.f_bavail = 80 * 1024 * 256
        fake_stat.f_frsize = 4096
        fake_stat.f_blocks = 100 * 1024 * 256

        with mock.patch("health_checker.os.system"):
            with mock.patch("health_checker.os.statvfs", return_value=fake_stat):
                with mock.patch.object(hc.systemd, "get_status", return_value="active") as mock_status:
                    with mock.patch("health_checker.subprocess.run"):
                        hc.system_health_check()

        mock_status.assert_called_once_with("plex-plextickets")


# ---------------------------------------------------------------------------
# SelfTestResult extra
# ---------------------------------------------------------------------------


class TestSelfTestResultExtra:
    def test_all_statuses(self):
        for status in ("pass", "fail", "warn"):
            r = SelfTestResult(name="test", status=status)
            assert r.status == status

    def test_empty_strings_default(self):
        r = SelfTestResult(name="t", status="pass")
        assert r.detail == ""
        assert r.hint == ""
        assert r.name == "t"


# ---------------------------------------------------------------------------
# HealthChecker.print_summary — extra
# ---------------------------------------------------------------------------


class TestPrintSummaryExtra:
    def _make_checker(self) -> HealthChecker:
        return HealthChecker(
            printer=ColorPrinter(),
            systemd=SystemdManager(),
            install_dir=Path("/tmp/plex"),
            node_min_version=18,
            nginx_available=Path("/etc/nginx/sites-available"),
            nginx_enabled=Path("/etc/nginx/sites-enabled"),
        )

    def test_empty_results(self, capsys):
        hc = self._make_checker()
        hc.print_summary([])
        captured = capsys.readouterr()
        assert "passed" in captured.err.lower()

    def test_mixed_results(self, capsys):
        hc = self._make_checker()
        results = [
            SelfTestResult(name="a", status="pass"),
            SelfTestResult(name="b", status="warn", detail="hmm"),
            SelfTestResult(name="c", status="fail", detail="bad", hint="fix"),
        ]
        hc.print_summary(results)
        captured = capsys.readouterr()
        out = captured.err.lower()
        assert "1 failure" in out or "failed" in out

    def test_hint_printed_for_failure(self, capsys):
        hc = self._make_checker()
        results = [
            SelfTestResult(name="node", status="fail", detail="missing", hint="install node"),
        ]
        hc.print_summary(results)
        captured = capsys.readouterr()
        assert "install node" in captured.err
