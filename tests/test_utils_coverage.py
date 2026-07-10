"""Additional coverage tests for utils.py.

Targets: SystemDetector, DNSChecker, FirewallManager, NginxManager,
SSLManager, SystemdManager service lifecycle helpers, path validation,
staged install, archive extraction edge cases, and permission policy.
All system-facing calls are mocked.
"""

import subprocess
import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from utils import (
    ArchiveExtractor,
    ArchiveLimitError,
    DNSChecker,
    FirewallManager,
    NginxManager,
    SSLManager,
    SystemDetector,
    SystemdManager,
    UnsafeArchiveError,
    install_staged_directory,
    redact_sensitive_yaml,
    safe_extract_archive,
    safe_extract_tar,
    safe_extract_zip,
    validate_path_component,
)


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# SystemDetector
# ---------------------------------------------------------------------------


class TestSystemDetector:
    def test_detect_reads_os_release_and_pkg_manager(self):
        det = SystemDetector()
        os_release = 'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="22.04"\n'
        with (
            mock.patch("builtins.open", mock.mock_open(read_data=os_release)),
            mock.patch("utils.shutil.which", side_effect=lambda c: "/usr/bin/apt" if c == "apt" else None),
        ):
            det.detect()
        assert det.distribution == "ubuntu"
        assert det.pkg_manager == "apt"

    def test_detect_missing_os_release_exits(self):
        det = SystemDetector()
        with (
            mock.patch("builtins.open", side_effect=FileNotFoundError),
            pytest.raises(SystemExit),
        ):
            det.detect()

    def test_detect_no_pkg_manager_exits(self):
        det = SystemDetector()
        with (
            mock.patch("builtins.open", mock.mock_open(read_data="ID=weirdos\n")),
            mock.patch("utils.shutil.which", return_value=None),
            pytest.raises(SystemExit),
        ):
            det.detect()

    def test_install_dependencies_without_detect_errors(self, capsys):
        det = SystemDetector()
        det.install_dependencies()
        assert "not detected" in capsys.readouterr().err

    def test_install_dependencies_no_packages_warns(self, capsys):
        det = SystemDetector()
        det.pkg_manager = "apt"
        with mock.patch("config.Config") as cfg:
            cfg.return_value.SYSTEM_PACKAGES = {}
            det.install_dependencies()
        assert "No package list" in capsys.readouterr().err

    def test_install_dependencies_apt_flow(self):
        det = SystemDetector()
        det.pkg_manager = "apt"
        with (
            mock.patch("config.Config") as cfg,
            mock.patch("utils.subprocess.run", return_value=_ok()) as run,
            mock.patch.object(det, "_install_nodejs"),
        ):
            cfg.return_value.SYSTEM_PACKAGES = {"apt": ["curl", "nginx"]}
            det.install_dependencies()
        cmds = [c.args[0] for c in run.call_args_list]
        assert ["apt", "update", "-y"] in cmds
        assert ["apt", "install", "-y", "curl", "nginx"] in cmds

    def test_install_dependencies_install_failure_reports_error(self, capsys):
        det = SystemDetector()
        det.pkg_manager = "apt"

        def side_effect(cmd, **kw):
            if "install" in cmd and kw.get("check"):
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        with (
            mock.patch("config.Config") as cfg,
            mock.patch("utils.subprocess.run", side_effect=side_effect),
            mock.patch.object(det, "_install_nodejs"),
        ):
            cfg.return_value.SYSTEM_PACKAGES = {"apt": ["curl"]}
            det.install_dependencies()
        assert "Package installation failed" in capsys.readouterr().err

    def test_install_nodejs_apt_uses_nodesource(self):
        det = SystemDetector()
        det.pkg_manager = "apt"
        with mock.patch("utils.subprocess.run", return_value=_ok("v20.0.0\n")) as run:
            det._install_nodejs()
        first = run.call_args_list[0]
        assert "deb.nodesource.com" in first.args[0]
        assert first.kwargs.get("shell") is True

    def test_install_nodejs_pacman(self):
        det = SystemDetector()
        det.pkg_manager = "pacman"
        with mock.patch("utils.subprocess.run", return_value=_ok("v20.0.0\n")) as run:
            det._install_nodejs()
        assert run.call_args_list[0].args[0][0] == "pacman"

    def test_install_nodejs_setup_script_failure(self, capsys):
        det = SystemDetector()
        det.pkg_manager = "apt"

        def side_effect(cmd, **kw):
            if kw.get("shell"):
                raise subprocess.CalledProcessError(1, cmd)
            return _ok("v20.0.0\n")

        with mock.patch("utils.subprocess.run", side_effect=side_effect):
            det._install_nodejs()
        assert "Node.js installation failed" in capsys.readouterr().err

    def test_install_nodejs_node_missing_after_install(self, capsys):
        det = SystemDetector()
        det.pkg_manager = "pacman"

        def side_effect(cmd, **kw):
            if cmd[0] == "node":
                raise FileNotFoundError("node")
            return _ok()

        with mock.patch("utils.subprocess.run", side_effect=side_effect):
            det._install_nodejs()
        assert "Node.js not found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# DNSChecker
# ---------------------------------------------------------------------------


class TestDNSChecker:
    def test_check_match(self):
        checker = DNSChecker()
        with (
            mock.patch.object(checker, "_get_public_ip", return_value="1.2.3.4"),
            mock.patch("utils.socket.gethostbyname", return_value="1.2.3.4"),
        ):
            assert checker.check("example.com") is True

    def test_check_mismatch(self):
        checker = DNSChecker()
        with (
            mock.patch.object(checker, "_get_public_ip", return_value="1.2.3.4"),
            mock.patch("utils.socket.gethostbyname", return_value="5.6.7.8"),
        ):
            assert checker.check("example.com") is False

    def test_check_unresolvable_domain(self):
        import socket as socket_mod

        checker = DNSChecker()
        with (
            mock.patch.object(checker, "_get_public_ip", return_value="1.2.3.4"),
            mock.patch("utils.socket.gethostbyname", side_effect=socket_mod.gaierror),
        ):
            assert checker.check("nope.invalid") is False

    def test_check_no_public_ip(self):
        checker = DNSChecker()
        with mock.patch.object(checker, "_get_public_ip", return_value=None):
            assert checker.check("example.com") is False

    def test_get_public_ip_success(self):
        checker = DNSChecker()
        with mock.patch("utils.subprocess.run", return_value=_ok("9.9.9.9\n")):
            assert checker._get_public_ip() == "9.9.9.9"

    def test_get_public_ip_all_services_fail(self):
        checker = DNSChecker()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.TimeoutExpired("curl", 10)):
            assert checker._get_public_ip() is None

    def test_get_public_ip_skips_empty_output(self):
        checker = DNSChecker()
        results = [_ok(""), _ok("8.8.8.8\n")]
        with mock.patch("utils.subprocess.run", side_effect=results):
            assert checker._get_public_ip() == "8.8.8.8"


# ---------------------------------------------------------------------------
# FirewallManager
# ---------------------------------------------------------------------------


class TestFirewallManager:
    def _which(self, available: str):
        return lambda cmd: f"/usr/bin/{cmd}" if cmd == available else None

    @pytest.mark.parametrize(
        ("tool", "expected_first_arg"),
        [("ufw", "ufw"), ("firewall-cmd", "firewall-cmd"), ("iptables", "iptables")],
    )
    def test_open_port_dispatch(self, tool: str, expected_first_arg: str):
        fw = FirewallManager()
        with (
            mock.patch("utils.shutil.which", side_effect=self._which(tool)),
            mock.patch("utils.subprocess.run", return_value=_ok()) as run,
        ):
            fw.open_port(3000, "test")
        assert run.call_args_list[0].args[0][0] == expected_first_arg

    def test_open_port_no_firewall_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.shutil.which", return_value=None):
            fw.open_port(3000, "test")
        assert "No supported firewall" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("tool", "expected_first_arg"),
        [("ufw", "ufw"), ("firewall-cmd", "firewall-cmd"), ("iptables", "iptables")],
    )
    def test_close_port_dispatch(self, tool: str, expected_first_arg: str):
        fw = FirewallManager()
        with (
            mock.patch("utils.shutil.which", side_effect=self._which(tool)),
            mock.patch("utils.subprocess.run", return_value=_ok()) as run,
        ):
            fw.close_port(3000)
        assert run.call_args_list[0].args[0][0] == expected_first_arg

    def test_open_ufw_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ufw"])):
            fw._open_ufw(3000, "test")
        assert "Failed to open port in UFW" in capsys.readouterr().err

    def test_open_firewalld_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["fw"])):
            fw._open_firewalld(3000)
        assert "Failed to open port in firewalld" in capsys.readouterr().err

    def test_open_iptables_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ipt"])):
            fw._open_iptables(3000)
        assert "Failed to open port in iptables" in capsys.readouterr().err

    def test_close_ufw_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ufw"])):
            fw._close_ufw(3000)
        assert "Failed to remove UFW rule" in capsys.readouterr().err

    def test_close_firewalld_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["fw"])):
            fw._close_firewalld(3000)
        assert "Failed to remove firewalld rule" in capsys.readouterr().err

    def test_close_iptables_failure_warns(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["ipt"])):
            fw._close_iptables(3000)
        assert "Failed to remove iptables rule" in capsys.readouterr().err

    def test_iptables_persistence_warning(self, capsys):
        fw = FirewallManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            fw._open_iptables(3000)
        assert "may not persist" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# NginxManager
# ---------------------------------------------------------------------------


class TestNginxManager:
    def _manager(self, tmp_path: Path) -> NginxManager:
        mgr = NginxManager()
        mgr.config = mock.MagicMock()
        available = tmp_path / "sites-available"
        enabled = tmp_path / "sites-enabled"
        available.mkdir()
        enabled.mkdir()
        mgr.config.nginx_available = available
        mgr.config.nginx_enabled = enabled
        return mgr

    def test_setup_writes_config_and_symlink(self, tmp_path: Path):
        mgr = self._manager(tmp_path)
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            mgr.setup("example.com", 3000, "svc", tmp_path / "app")
        conf = tmp_path / "sites-available" / "example.com.conf"
        link = tmp_path / "sites-enabled" / "example.com.conf"
        content = conf.read_text()
        assert "proxy_pass http://localhost:3000" in content
        assert "server_name example.com" in content
        assert link.is_symlink()
        assert (conf.stat().st_mode & 0o777) == 0o644

    def test_setup_replaces_existing_symlink(self, tmp_path: Path):
        mgr = self._manager(tmp_path)
        link = tmp_path / "sites-enabled" / "example.com.conf"
        stale = tmp_path / "stale"
        stale.write_text("x")
        link.symlink_to(stale)
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            mgr.setup("example.com", 3000, "svc", tmp_path / "app")
        assert link.resolve() == (tmp_path / "sites-available" / "example.com.conf").resolve()

    def test_setup_nginx_test_failure_raises(self, tmp_path: Path):
        mgr = self._manager(tmp_path)
        err = subprocess.CalledProcessError(1, ["nginx"], stderr=b"bad config")
        with (
            mock.patch("utils.subprocess.run", side_effect=err),
            pytest.raises(subprocess.CalledProcessError),
        ):
            mgr.setup("example.com", 3000, "svc", tmp_path / "app")


# ---------------------------------------------------------------------------
# SSLManager
# ---------------------------------------------------------------------------


class TestSSLManager:
    def test_setup_success(self):
        ssl = SSLManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()) as run:
            ssl.setup("example.com", "a@b.c")
        cmd = run.call_args.args[0]
        assert cmd[0] == "certbot"
        assert "example.com" in cmd
        assert "a@b.c" in cmd

    def test_setup_failure_raises(self, capsys):
        ssl = SSLManager()
        with (
            mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["certbot"])),
            pytest.raises(subprocess.CalledProcessError),
        ):
            ssl.setup("example.com", "a@b.c")
        assert "SSL setup failed" in capsys.readouterr().err

    def test_auto_renewal_adds_cron_entry(self):
        ssl = SSLManager()
        calls = []

        def side_effect(cmd, **kw):
            calls.append((cmd, kw))
            if cmd == ["crontab", "-l"]:
                return _ok("0 1 * * * something\n")
            return _ok()

        with mock.patch("utils.subprocess.run", side_effect=side_effect):
            ssl.setup_auto_renewal()
        write_call = [c for c in calls if c[0] == ["crontab", "-"]]
        assert len(write_call) == 1
        assert "certbot renew" in write_call[0][1]["input"]

    def test_auto_renewal_already_configured(self):
        ssl = SSLManager()

        def side_effect(cmd, **kw):
            if cmd == ["crontab", "-l"]:
                return _ok("0 2 * * * /usr/bin/certbot renew --quiet\n")
            raise AssertionError("should not write crontab")

        with mock.patch("utils.subprocess.run", side_effect=side_effect):
            ssl.setup_auto_renewal()

    def test_auto_renewal_write_failure_reports_error(self, capsys):
        ssl = SSLManager()

        def side_effect(cmd, **kw):
            if cmd == ["crontab", "-l"]:
                return _ok("", returncode=1)
            raise subprocess.CalledProcessError(1, cmd)

        with mock.patch("utils.subprocess.run", side_effect=side_effect):
            ssl.setup_auto_renewal()
        assert "Failed to setup auto-renewal" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# SystemdManager
# ---------------------------------------------------------------------------


class TestSystemdManager:
    def test_service_user_name_normalizes(self):
        assert SystemdManager.service_user_name("My App") == "plex-my-app"

    def test_service_user_name_truncates(self):
        name = SystemdManager.service_user_name("a" * 60)
        assert len(name) == 31

    @pytest.mark.parametrize("bad", ["..", ".", "", "a/b", "a\\b", "a\x00b"])
    def test_service_user_name_rejects_invalid(self, bad: str):
        with pytest.raises(ValueError):
            SystemdManager.service_user_name(bad)

    def test_prepare_identity_requires_tools(self, tmp_path: Path):
        mgr = SystemdManager()
        with (
            mock.patch("utils.shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="useradd and runuser"),
        ):
            mgr.prepare_service_identity("svc", tmp_path)

    def test_prepare_identity_existing_user_skips_useradd(self, tmp_path: Path):
        mgr = SystemdManager()
        with (
            mock.patch("utils.shutil.which", return_value="/usr/bin/tool"),
            mock.patch("utils.pwd.getpwnam", return_value=object()),
            mock.patch("utils.subprocess.run", return_value=_ok()) as run,
        ):
            user, created = mgr.prepare_service_identity("svc", tmp_path)
        assert user == "plex-svc"
        assert created is False
        assert all(c.args[0][0] != "useradd" for c in run.call_args_list)

    def test_prepare_identity_chown_failure_removes_created_user(self, tmp_path: Path):
        mgr = SystemdManager()

        def side_effect(cmd, **kw):
            if cmd[0] == "chown":
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        with (
            mock.patch("utils.shutil.which", return_value="/usr/bin/tool"),
            mock.patch("utils.pwd.getpwnam", side_effect=KeyError),
            mock.patch("utils.subprocess.run", side_effect=side_effect) as run,
            pytest.raises(subprocess.CalledProcessError),
        ):
            mgr.prepare_service_identity("svc", tmp_path)
        assert any(c.args[0][0] == "userdel" for c in run.call_args_list)

    def test_release_identity_removes_user_and_group(self, tmp_path: Path):
        mgr = SystemdManager()
        with (
            mock.patch("utils.shutil.which", return_value="/usr/bin/groupdel"),
            mock.patch("utils.subprocess.run", return_value=_ok()) as run,
        ):
            mgr.release_service_identity("svc", tmp_path, remove_user=True)
        cmds = [c.args[0][0] for c in run.call_args_list]
        assert "chown" in cmds
        assert "userdel" in cmds
        assert "groupdel" in cmds

    def test_release_identity_keeps_user(self, tmp_path: Path):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()) as run:
            mgr.release_service_identity("svc", tmp_path / "missing", remove_user=False)
        assert run.call_args_list == []

    def test_start_success_and_failure(self, capsys):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            mgr.start("svc")
        assert "started" in capsys.readouterr().err
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["x"])):
            mgr.start("svc")
        assert "Failed to start" in capsys.readouterr().err

    def test_stop_success_and_failure(self, capsys):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            mgr.stop("svc")
        assert "stopped" in capsys.readouterr().err
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["x"])):
            mgr.stop("svc")
        assert "Failed to stop" in capsys.readouterr().err

    def test_restart_success_and_failure(self, capsys):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            mgr.restart("svc")
        assert "restarted" in capsys.readouterr().err
        with mock.patch("utils.subprocess.run", side_effect=subprocess.CalledProcessError(1, ["x"])):
            mgr.restart("svc")
        assert "Failed to restart" in capsys.readouterr().err

    def test_get_status(self):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", return_value=_ok("active\n")):
            assert mgr.get_status("svc") == "active"
        with mock.patch("utils.subprocess.run", return_value=_ok("")):
            assert mgr.get_status("svc") == "unknown"
        with mock.patch("utils.subprocess.run", side_effect=OSError):
            assert mgr.get_status("svc") == "unknown"

    def test_view_logs_handles_keyboard_interrupt(self):
        mgr = SystemdManager()
        with mock.patch("utils.subprocess.run", side_effect=KeyboardInterrupt):
            mgr.view_logs("svc")  # should not raise

    def test_remove_service(self, tmp_path: Path, capsys):
        mgr = SystemdManager()
        service_file = tmp_path / "plex-svc.service"
        service_file.write_text("[Unit]")
        original_path = Path

        def fake_path(value):
            if str(value).startswith("/etc/systemd/system/"):
                return service_file
            return original_path(value)

        with (
            mock.patch("utils.Path", side_effect=fake_path),
            mock.patch("utils.subprocess.run", return_value=_ok()),
        ):
            mgr.remove_service("plex-svc")
        assert not service_file.exists()
        assert "removed" in capsys.readouterr().err

    def test_remove_service_missing_file_ok(self, tmp_path: Path):
        mgr = SystemdManager()
        original_path = Path

        def fake_path(value):
            if str(value).startswith("/etc/systemd/system/"):
                return tmp_path / "nonexistent.service"
            return original_path(value)

        with (
            mock.patch("utils.Path", side_effect=fake_path),
            mock.patch("utils.subprocess.run", return_value=_ok()),
        ):
            mgr.remove_service("plex-svc")

    def test_remove_service_daemon_reload_failure(self, tmp_path: Path, capsys):
        mgr = SystemdManager()
        original_path = Path

        def fake_path(value):
            if str(value).startswith("/etc/systemd/system/"):
                return tmp_path / "nonexistent.service"
            return original_path(value)

        def side_effect(cmd, **kw):
            if kw.get("check") and cmd[:2] == ["systemctl", "daemon-reload"]:
                raise subprocess.CalledProcessError(1, cmd)
            return _ok()

        with (
            mock.patch("utils.Path", side_effect=fake_path),
            mock.patch("utils.subprocess.run", side_effect=side_effect),
        ):
            mgr.remove_service("plex-svc")
        assert "Failed to remove service" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# validate_path_component / install_staged_directory
# ---------------------------------------------------------------------------


class TestValidatePathComponent:
    def test_valid(self):
        assert validate_path_component("myapp") == "myapp"

    @pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b", "a\x00b", "C:evil", None, 5])
    def test_invalid(self, bad):
        with pytest.raises(ValueError):
            validate_path_component(bad)


class TestInstallStagedDirectory:
    def test_success(self, tmp_path: Path):
        src = tmp_path / "staged"
        src.mkdir()
        (src / "f.txt").write_text("data")
        target = tmp_path / "final"
        install_staged_directory(src, target)
        assert (target / "f.txt").read_text() == "data"
        assert not src.exists()

    def test_existing_target_raises(self, tmp_path: Path):
        src = tmp_path / "staged"
        src.mkdir()
        target = tmp_path / "final"
        target.mkdir()
        (target / "keep.txt").write_text("keep")
        with pytest.raises(FileExistsError):
            install_staged_directory(src, target)
        assert (target / "keep.txt").exists()


# ---------------------------------------------------------------------------
# Archive extraction edge cases
# ---------------------------------------------------------------------------


class TestArchiveEdgeCases:
    def test_safe_extract_archive_dispatches_tar(self, tmp_path: Path):
        archive = tmp_path / "app.tar.gz"
        member = tarfile.TarInfo("app/file.txt")
        data = b"hello"
        member.size = len(data)
        with tarfile.open(archive, "w:gz") as tf:
            tf.addfile(member, BytesIO(data))
        out = safe_extract_archive(archive, tmp_path / "out")
        assert (out / "app" / "file.txt").read_text() == "hello"

    def test_safe_extract_archive_unsupported(self, tmp_path: Path):
        bad = tmp_path / "app.rar"
        bad.write_text("x")
        with pytest.raises(ValueError, match="Unsupported archive format"):
            safe_extract_archive(bad, tmp_path / "out")

    def test_missing_archive_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            safe_extract_zip(tmp_path / "missing.zip", tmp_path / "out")

    def test_corrupted_zip_raises_value_error(self, tmp_path: Path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip at all")
        target = tmp_path / "out"
        with pytest.raises(ValueError, match="Corrupted or invalid ZIP"):
            safe_extract_zip(bad, target)
        assert not target.exists()

    def test_corrupted_tar_raises_value_error(self, tmp_path: Path):
        bad = tmp_path / "bad.tar"
        bad.write_bytes(b"\x00" * 100)
        with pytest.raises(ValueError, match="Corrupted or invalid TAR"):
            safe_extract_tar(bad, tmp_path / "out")

    def test_empty_zip_rejected(self, tmp_path: Path):
        archive = tmp_path / "empty.zip"
        with zipfile.ZipFile(archive, "w"):
            pass
        with pytest.raises(UnsafeArchiveError, match="empty"):
            safe_extract_zip(archive, tmp_path / "out")

    def test_duplicate_member_paths_rejected(self, tmp_path: Path):
        archive = tmp_path / "dup.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("file.txt", "one")
            zf.writestr("file.txt", "two")
        with pytest.raises(UnsafeArchiveError, match="Duplicate"):
            safe_extract_zip(archive, tmp_path / "out")

    def test_path_conflicting_with_file_rejected(self, tmp_path: Path):
        archive = tmp_path / "conflict.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("a", "file")
            zf.writestr("a/b", "nested")
        with pytest.raises(UnsafeArchiveError, match="conflicts with a file"):
            safe_extract_zip(archive, tmp_path / "out")

    def test_tar_file_count_limit(self, tmp_path: Path):
        archive = tmp_path / "many.tar"
        with tarfile.open(archive, "w") as tf:
            for i in range(3):
                member = tarfile.TarInfo(f"f{i}")
                data = b"x"
                member.size = 1
                tf.addfile(member, BytesIO(data))
        with pytest.raises(ArchiveLimitError, match="too many files"):
            safe_extract_tar(archive, tmp_path / "out", max_files=2)

    def test_tar_byte_limit(self, tmp_path: Path):
        archive = tmp_path / "big.tar"
        member = tarfile.TarInfo("big")
        data = b"A" * 50
        member.size = 50
        with tarfile.open(archive, "w") as tf:
            tf.addfile(member, BytesIO(data))
        with pytest.raises(ArchiveLimitError, match="too many bytes"):
            safe_extract_tar(archive, tmp_path / "out", max_bytes=49)

    def test_tar_expected_top_level_accepted(self, tmp_path: Path):
        archive = tmp_path / "good.tar"
        member = tarfile.TarInfo("expected/file.txt")
        data = b"ok"
        member.size = 2
        with tarfile.open(archive, "w") as tf:
            tf.addfile(member, BytesIO(data))
        out = safe_extract_tar(archive, tmp_path / "out", expected_top_level="expected")
        assert (out / "expected" / "file.txt").exists()

    def test_zip_directory_entries_and_modes(self, tmp_path: Path):
        archive = tmp_path / "dirs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("app/", "")
            zf.writestr("app/run.sh", "#!/bin/sh\n")
        out = safe_extract_zip(archive, tmp_path / "out")
        assert (out / "app").is_dir()
        assert (out / "app" / "run.sh").exists()

    def test_failed_extraction_cleans_up_target(self, tmp_path: Path):
        archive = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape", "bad")
        target = tmp_path / "out"
        with pytest.raises(UnsafeArchiveError):
            safe_extract_zip(archive, target)
        assert not target.exists()


# ---------------------------------------------------------------------------
# ArchiveExtractor internals
# ---------------------------------------------------------------------------


class TestArchiveExtractorInternals:
    def test_set_permissions_policy(self, tmp_path: Path):
        extractor = ArchiveExtractor()
        root = tmp_path / "product"
        root.mkdir()
        (root / "config.yml").write_text("Token: x")
        (root / "run.sh").write_text("#!/bin/sh")
        (root / "readme.txt").write_text("hi")
        (root / "secret.key").write_text("k")
        with mock.patch("utils.subprocess.run", return_value=_ok()):
            extractor._set_permissions(root)
        assert (root / "config.yml").stat().st_mode & 0o777 == 0o600
        assert (root / "secret.key").stat().st_mode & 0o777 == 0o600
        assert (root / "run.sh").stat().st_mode & 0o777 == 0o750
        assert (root / "readme.txt").stat().st_mode & 0o777 == 0o640

    def test_compat_extract_zip_wrapper(self, tmp_path: Path):
        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("app/f.txt", "x")
        extractor = ArchiveExtractor()
        out = extractor._extract_zip(archive, tmp_path / "out")
        assert (out / "app" / "f.txt").exists()

    def test_compat_extract_tar_wrapper(self, tmp_path: Path):
        archive = tmp_path / "a.tar"
        member = tarfile.TarInfo("app/f.txt")
        member.size = 1
        with tarfile.open(archive, "w") as tf:
            tf.addfile(member, BytesIO(b"x"))
        extractor = ArchiveExtractor()
        out = extractor._extract_tar(archive, tmp_path / "out")
        assert (out / "app" / "f.txt").exists()

    def test_find_product_dir_name_match(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "MyApp").mkdir()
        extractor = ArchiveExtractor()
        assert extractor._find_product_dir(tmp_path, "myapp") == tmp_path / "MyApp"

    def test_find_product_dir_defaults_to_root(self, tmp_path: Path):
        (tmp_path / "index.js").write_text("//")
        (tmp_path / "lib").mkdir()
        (tmp_path / "other").mkdir()
        extractor = ArchiveExtractor()
        assert extractor._find_product_dir(tmp_path, "nomatch") == tmp_path


# ---------------------------------------------------------------------------
# Redaction: inline comment branch
# ---------------------------------------------------------------------------


class TestRedactionInlineComment:
    def test_sensitive_key_keeps_inline_comment(self):
        text = "Token: secret-value # keep me\n"
        result = redact_sensitive_yaml(text)
        assert "secret-value" not in result
        assert "# keep me" in result
        assert "<REDACTED>" in result
