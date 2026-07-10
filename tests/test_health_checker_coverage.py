"""Additional coverage tests for health_checker.py."""

import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from health_checker import HealthChecker, SelfTestResult
from utils import ColorPrinter, SystemdManager


def _checker(tmp_path: Path) -> HealthChecker:
    return HealthChecker(
        printer=ColorPrinter(),
        systemd=SystemdManager(),
        install_dir=tmp_path / "plex",
        node_min_version=18,
        nginx_available=tmp_path / "sites-available",
        nginx_enabled=tmp_path / "sites-enabled",
    )


def _context(tmp_path: Path, **overrides) -> SimpleNamespace:
    base = dict(
        install_path=tmp_path / "plex" / "plextickets",
        instance_name="plextickets",
        product="plextickets",
        service_created=False,
        port=3000,
        domain=None,
        needs_web_setup=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _completed(stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ---------------------------------------------------------------------------
# wait_for_tcp_port
# ---------------------------------------------------------------------------


class TestWaitForTcpPort:
    def test_success(self):
        conn = mock.MagicMock()
        with mock.patch("health_checker.socket.create_connection", return_value=conn):
            assert HealthChecker.wait_for_tcp_port("127.0.0.1", 3000, timeout_seconds=5) is True

    def test_timeout(self):
        times = iter([0, 1, 2, 100])
        with (
            mock.patch("health_checker.socket.create_connection", side_effect=OSError),
            mock.patch("health_checker.time.time", side_effect=lambda: next(times)),
            mock.patch("health_checker.time.sleep"),
        ):
            assert HealthChecker.wait_for_tcp_port("127.0.0.1", 3000, timeout_seconds=3) is False


# ---------------------------------------------------------------------------
# run_post_install_self_tests
# ---------------------------------------------------------------------------


class TestSelfTests:
    def _base_patches(self, checker):
        return mock.patch.object(checker, "check_node_version", return_value=(True, "Node.js v20.0.0"))

    def test_no_service_no_mongo(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)
        (ctx.install_path / "package.json").write_text("{}")
        (ctx.install_path / "config.yml").write_text("k: v")

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, None)

        by_name = {r.name: r for r in results}
        assert by_name["Node.js version"].status == "pass"
        assert by_name["package.json present"].status == "pass"
        assert by_name["node_modules present"].status == "warn"
        assert by_name["Config file present"].status == "pass"
        assert "config.yml" in by_name["Config file present"].detail
        assert by_name["Config file present"].hint == ""
        assert by_name["systemd auto-start"].status == "warn"

    def test_missing_config_remains_warning(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, None)

        config_result = next(result for result in results if result.name == "Config file present")
        assert config_result.status == "warn"
        assert config_result.hint

    def test_service_active_with_port_and_http(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, service_created=True)
        ctx.install_path.mkdir(parents=True)

        with (
            self._base_patches(checker),
            mock.patch.object(checker.systemd, "get_status", return_value="active"),
            mock.patch.object(checker, "wait_for_tcp_port", return_value=True),
            mock.patch.object(checker, "probe_http", return_value=(True, "HTTP 200 OK")),
        ):
            results = checker.run_post_install_self_tests(ctx, None)

        by_name = {r.name: r for r in results}
        assert by_name["systemd service active"].status == "pass"
        assert by_name["Local TCP port reachable"].status == "pass"
        assert by_name["Local HTTP responds"].status == "pass"

    def test_service_never_becomes_active(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, service_created=True)
        ctx.install_path.mkdir(parents=True)

        with (
            self._base_patches(checker),
            mock.patch.object(checker.systemd, "get_status", return_value="failed"),
            mock.patch("health_checker.time.sleep"),
            mock.patch.object(checker, "wait_for_tcp_port", return_value=False),
        ):
            results = checker.run_post_install_self_tests(ctx, None)

        by_name = {r.name: r for r in results}
        assert by_name["systemd service active"].status == "fail"
        assert by_name["Local TCP port reachable"].status == "fail"
        assert "Local HTTP responds" not in by_name

    def test_service_detail_reuses_final_polled_status(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, service_created=True)
        ctx.install_path.mkdir(parents=True)

        with (
            self._base_patches(checker),
            mock.patch.object(checker.systemd, "get_status", side_effect=["activating", "active", "failed"]) as status,
            mock.patch("health_checker.time.sleep"),
            mock.patch.object(checker, "wait_for_tcp_port", return_value=False),
        ):
            results = checker.run_post_install_self_tests(ctx, None)

        service_result = next(result for result in results if result.name == "systemd service active")
        assert service_result.detail == "plex-plextickets is active"
        assert status.call_count == 2

    def test_bot_only_skips_port_check(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, service_created=True, needs_web_setup=False)
        ctx.install_path.mkdir(parents=True)

        with self._base_patches(checker), mock.patch.object(checker.systemd, "get_status", return_value="active"):
            results = checker.run_post_install_self_tests(ctx, None)

        by_name = {r.name: r for r in results}
        assert by_name["Local TCP port check"].status == "warn"
        assert "skipped" in by_name["Local TCP port check"].detail

    def test_mongo_uri_validates_and_reads_writes(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)
        mongo = mock.MagicMock()
        mongo.validate_uri.return_value = True
        mongo.run_shell.return_value = _completed(stdout="__PLEXINSTALLER_OK__")

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, {"uri": "mongodb://x"}, mongo_manager=mongo)

        by_name = {r.name: r for r in results}
        assert by_name["MongoDB auth via generated URI"].status == "pass"
        assert by_name["MongoDB read/write"].status == "pass"

    def test_mongo_uri_auth_fails(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)
        mongo = mock.MagicMock()
        mongo.validate_uri.return_value = False

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, {"uri": "mongodb://x"}, mongo_manager=mongo)

        by_name = {r.name: r for r in results}
        assert by_name["MongoDB auth via generated URI"].status == "fail"
        assert "MongoDB read/write" not in by_name

    def test_mongo_shell_exception_warns(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)
        mongo = mock.MagicMock()
        mongo.validate_uri.return_value = True
        mongo.run_shell.side_effect = RuntimeError("shell missing")

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, {"uri": "mongodb://x"}, mongo_manager=mongo)

        by_name = {r.name: r for r in results}
        assert by_name["MongoDB read/write"].status == "warn"

    def test_mongo_uri_without_manager_fails(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, {"uri": "mongodb://x"})

        by_name = {r.name: r for r in results}
        assert by_name["MongoDB auth via generated URI"].status == "fail"

    def test_required_mongo_missing_creds_warns(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path)
        ctx.install_path.mkdir(parents=True)
        config = mock.MagicMock()
        config.get_product.return_value = SimpleNamespace(requires_mongodb=True)

        with self._base_patches(checker):
            results = checker.run_post_install_self_tests(ctx, None, config=config)

        by_name = {r.name: r for r in results}
        assert by_name["MongoDB configured"].status == "warn"

    def test_domain_triggers_nginx_ssl_checks(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, domain="example.com")
        ctx.install_path.mkdir(parents=True)

        with self._base_patches(checker), mock.patch.object(checker, "_check_nginx_ssl") as chk:
            checker.run_post_install_self_tests(ctx, None)
        chk.assert_called_once()


# ---------------------------------------------------------------------------
# _check_nginx_ssl
# ---------------------------------------------------------------------------


class TestCheckNginxSsl:
    def _run(self, tmp_path: Path, run_side_effect, dns_side_effect=None, ssl_fail=True):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, domain="example.com")
        results: list[SelfTestResult] = []
        with (
            mock.patch("health_checker.subprocess.run", side_effect=run_side_effect),
            mock.patch(
                "health_checker.socket.gethostbyname",
                side_effect=dns_side_effect or (lambda d: "1.2.3.4"),
            ),
            mock.patch(
                "health_checker.socket.create_connection",
                side_effect=OSError("no route") if ssl_fail else None,
            ),
        ):
            checker._check_nginx_ssl(ctx, results)
        return checker, {r.name: r for r in results}

    def test_all_healthy_paths(self, tmp_path: Path):
        checker = _checker(tmp_path)
        ctx = _context(tmp_path, domain="example.com")
        checker.nginx_available.mkdir(parents=True)
        checker.nginx_enabled.mkdir(parents=True)
        (checker.nginx_available / "example.com.conf").write_text("server {}")
        (checker.nginx_enabled / "example.com.conf").symlink_to(checker.nginx_available / "example.com.conf")

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "is-active"]:
                return _completed(stdout="active\n")
            if cmd[0] == "nginx":
                return _completed(stdout="syntax is ok")
            return _completed()

        sock = mock.MagicMock()
        ssock = mock.MagicMock()
        ssl_ctx = mock.MagicMock()
        ssl_ctx.wrap_socket.return_value.__enter__ = mock.MagicMock(return_value=ssock)
        ssl_ctx.wrap_socket.return_value.__exit__ = mock.MagicMock(return_value=False)

        results: list[SelfTestResult] = []
        with (
            mock.patch("health_checker.subprocess.run", side_effect=fake_run),
            mock.patch("health_checker.socket.gethostbyname", return_value="1.2.3.4"),
            mock.patch("health_checker.socket.create_connection", return_value=sock),
            mock.patch("health_checker.ssl.create_default_context", return_value=ssl_ctx),
        ):
            sock.__enter__ = mock.MagicMock(return_value=sock)
            sock.__exit__ = mock.MagicMock(return_value=False)
            checker._check_nginx_ssl(ctx, results)

        by_name = {r.name: r for r in results}
        assert by_name["nginx service active"].status == "pass"
        assert by_name["nginx site config present"].status == "pass"
        assert by_name["nginx site enabled"].status == "pass"
        assert by_name["nginx config test"].status == "pass"
        assert by_name["SSL certificate present"].status in {"pass", "warn"}
        assert by_name["DNS resolves"].status == "pass"
        assert by_name["HTTPS handshake"].status == "pass"

    def test_everything_missing_or_failing(self, tmp_path: Path):
        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["systemctl", "is-active"]:
                return _completed(stdout="inactive\n")
            if cmd[0] == "nginx":
                return _completed(stderr="config error", returncode=1)
            return _completed()

        _, by_name = self._run(
            tmp_path,
            fake_run,
            dns_side_effect=OSError("NXDOMAIN"),
        )
        assert by_name["nginx service active"].status == "fail"
        assert by_name["nginx site config present"].status == "fail"
        assert by_name["nginx site enabled"].status == "fail"
        assert by_name["nginx config test"].status == "fail"
        assert by_name["SSL certificate present"].status == "warn"
        assert by_name["DNS resolves"].status == "warn"
        assert by_name["HTTPS handshake"].status == "warn"

    def test_subprocess_exceptions_warn(self, tmp_path: Path):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        _, by_name = self._run(tmp_path, fake_run)
        assert by_name["nginx service active"].status == "warn"
        assert by_name["nginx config test"].status == "warn"


# ---------------------------------------------------------------------------
# system_health_check
# ---------------------------------------------------------------------------


class TestSystemHealthCheck:
    def _run(self, tmp_path: Path, *, statuses=None, run_map=None, meminfo=None, load=(0.1, 0.1, 0.1)):
        checker = _checker(tmp_path)
        statuses = statuses or {}
        run_map = run_map or {}

        def fake_systemd_status(name):
            return statuses.get(name, "not-found")

        def fake_run(cmd, **kwargs):
            key = " ".join(cmd)
            if key in run_map:
                return run_map[key]
            return _completed(returncode=1)

        meminfo = meminfo or "MemTotal: 8000000 kB\nMemAvailable: 4000000 kB\n"

        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch.object(checker.systemd, "get_status", side_effect=fake_systemd_status),
            mock.patch("health_checker.subprocess.run", side_effect=fake_run),
            mock.patch("builtins.open", mock.mock_open(read_data=meminfo)),
            mock.patch("health_checker.os.getloadavg", return_value=load),
            mock.patch("health_checker.os.cpu_count", return_value=4),
        ):
            checker.system_health_check()
        return checker

    def test_healthy_system(self, tmp_path: Path):
        install = tmp_path / "plex"
        (install / "plextickets").mkdir(parents=True)
        (install / "backups").mkdir()
        run_map = {
            "systemctl is-active nginx": _completed(stdout="active\n"),
            "systemctl is-active mongod": _completed(stdout="active\n"),
            "which certbot": _completed(returncode=0),
            "certbot certificates": _completed(stdout="Certificate Name: example.com\n"),
        }
        self._run(tmp_path, statuses={"plex-plextickets": "active"}, run_map=run_map)

    def test_stopped_and_missing_services(self, tmp_path: Path, caplog):
        install = tmp_path / "plex"
        (install / "stopped").mkdir(parents=True)
        (install / "gone").mkdir()
        with caplog.at_level(logging.DEBUG, logger="plexinstaller.health"):
            self._run(
                tmp_path,
                statuses={"plex-stopped": "inactive", "plex-gone": "unknown"},
            )
        assert any("Stopped" in r.message for r in caplog.records)
        assert any("Not Found" in r.message for r in caplog.records)

    def test_no_install_dir(self, tmp_path: Path):
        checker = self._run(tmp_path)
        assert not checker.install_dir.exists()

    def test_certbot_no_certificates(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        run_map = {
            "which certbot": _completed(returncode=0),
            "certbot certificates": _completed(stdout="No certificates found.\n"),
        }
        self._run(tmp_path, run_map=run_map)

    def test_high_memory_and_load(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        checker = _checker(tmp_path)
        meminfo = "MemTotal: 8000000 kB\nMemAvailable: 100000 kB\n"
        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.subprocess.run", return_value=_completed(returncode=1)),
            mock.patch("builtins.open", mock.mock_open(read_data=meminfo)),
            mock.patch("health_checker.os.getloadavg", return_value=(9.0, 9.0, 9.0)),
            mock.patch("health_checker.os.cpu_count", return_value=4),
            mock.patch.object(checker.printer, "error") as err,
        ):
            checker.system_health_check()
        messages = " ".join(str(c.args[0]) for c in err.call_args_list)
        assert "Memory" in messages
        assert "load" in messages.lower()

    def test_elevated_memory_and_load(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        checker = _checker(tmp_path)
        meminfo = "MemTotal: 8000000 kB\nMemAvailable: 1200000 kB\n"
        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.subprocess.run", return_value=_completed(returncode=1)),
            mock.patch("builtins.open", mock.mock_open(read_data=meminfo)),
            mock.patch("health_checker.os.getloadavg", return_value=(5.0, 5.0, 5.0)),
            mock.patch("health_checker.os.cpu_count", return_value=4),
            mock.patch.object(checker.printer, "warning") as warn,
        ):
            checker.system_health_check()
        messages = " ".join(str(c.args[0]) for c in warn.call_args_list)
        assert "Memory" in messages
        assert "load" in messages.lower()

    def test_meminfo_and_loadavg_failures(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        checker = _checker(tmp_path)

        def fake_run(cmd, **kwargs):
            if cmd[0] == "which":
                return _completed(returncode=1)
            raise FileNotFoundError(cmd[0])

        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.subprocess.run", side_effect=fake_run),
            mock.patch("builtins.open", side_effect=OSError("no /proc")),
            mock.patch("health_checker.os.getloadavg", side_effect=OSError("unsupported")),
            mock.patch.object(checker.printer, "warning") as warn,
        ):
            checker.system_health_check()
        messages = " ".join(str(c.args[0]) for c in warn.call_args_list)
        assert "memory" in messages.lower()
        assert "load" in messages.lower()

    def test_disk_thresholds(self, tmp_path: Path):
        checker = _checker(tmp_path)
        stat = mock.MagicMock()
        stat.f_bavail = 5
        stat.f_frsize = 1024**3
        stat.f_blocks = 100
        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.os.statvfs", return_value=stat),
            mock.patch("health_checker.subprocess.run", return_value=_completed(returncode=1)),
            mock.patch("builtins.open", side_effect=OSError),
            mock.patch("health_checker.os.getloadavg", side_effect=OSError),
            mock.patch.object(checker.printer, "error") as err,
        ):
            checker.system_health_check()
        assert any("90" in str(c.args[0]) for c in err.call_args_list)

    def test_disk_above_80(self, tmp_path: Path):
        checker = _checker(tmp_path)
        stat = mock.MagicMock()
        stat.f_bavail = 15
        stat.f_frsize = 1024**3
        stat.f_blocks = 100
        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.os.statvfs", return_value=stat),
            mock.patch("health_checker.subprocess.run", return_value=_completed(returncode=1)),
            mock.patch("builtins.open", side_effect=OSError),
            mock.patch("health_checker.os.getloadavg", side_effect=OSError),
            mock.patch.object(checker.printer, "warning") as warn,
        ):
            checker.system_health_check()
        assert any("80" in str(c.args[0]) for c in warn.call_args_list)

    def test_systemctl_exceptions_handled(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        checker = _checker(tmp_path)

        def fake_run(cmd, **kwargs):
            if cmd[0] == "which":
                return _completed(returncode=1)
            raise FileNotFoundError(cmd[0])

        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.subprocess.run", side_effect=fake_run),
            mock.patch("builtins.open", side_effect=OSError),
            mock.patch("health_checker.os.getloadavg", side_effect=OSError),
            mock.patch.object(checker.printer, "warning") as warn,
            mock.patch.object(checker.printer, "step") as step,
        ):
            checker.system_health_check()
        messages = " ".join(str(c.args[0]) for c in warn.call_args_list)
        assert "Nginx" in messages
        step_messages = " ".join(str(c.args[0]) for c in step.call_args_list)
        assert "MongoDB" in step_messages

    def test_certbot_check_failure_warns(self, tmp_path: Path):
        (tmp_path / "plex").mkdir()
        checker = _checker(tmp_path)

        def fake_run(cmd, **kwargs):
            if cmd[0] == "which":
                return _completed(returncode=0)
            if cmd[0] == "certbot":
                raise OSError("certbot broke")
            return _completed(stdout="inactive\n")

        with (
            mock.patch("health_checker.clear_terminal"),
            mock.patch("health_checker.subprocess.run", side_effect=fake_run),
            mock.patch("builtins.open", side_effect=OSError),
            mock.patch("health_checker.os.getloadavg", side_effect=OSError),
            mock.patch.object(checker.printer, "warning") as warn,
        ):
            checker.system_health_check()
        assert any("SSL" in str(c.args[0]) for c in warn.call_args_list)


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------


class TestPrintSummary:
    def test_all_pass(self, tmp_path: Path):
        checker = _checker(tmp_path)
        with mock.patch.object(checker.printer, "success") as ok:
            checker.print_summary([SelfTestResult(name="a", status="pass", detail="d")])
        assert any("All self-tests passed" in str(c.args[0]) for c in ok.call_args_list)

    def test_warnings_only(self, tmp_path: Path):
        checker = _checker(tmp_path)
        with mock.patch.object(checker.printer, "warning") as warn, mock.patch.object(checker.printer, "step") as step:
            checker.print_summary([SelfTestResult(name="a", status="warn", detail="d", hint="fix it")])
        assert any("1 warning" in str(c.args[0]) for c in warn.call_args_list)
        step.assert_called_once_with("fix it")

    def test_failures_and_warnings(self, tmp_path: Path):
        checker = _checker(tmp_path)
        results = [
            SelfTestResult(name="a", status="fail", detail="bad", hint="do X"),
            SelfTestResult(name="b", status="warn", detail="meh"),
            SelfTestResult(name="c", status="pass", detail="ok"),
        ]
        with mock.patch.object(checker.printer, "error") as err:
            checker.print_summary(results)
        assert any("1 failure" in str(c.args[0]) for c in err.call_args_list)
