"""Gap-closing coverage tests for backup_manager, addon_manager, health_checker,
shared, mongodb_manager and plex_cli (no real system access)."""

import io
import json
import shutil as real_shutil
import subprocess as real_subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
import yaml

import addon_manager as addon_manager_module
import backup_manager as backup_manager_module
import plex_cli
import shared as shared_module
from addon_manager import AddonManager
from backup_manager import BackupManager
from health_checker import HealthChecker, SelfTestResult
from mongodb_manager import MongoDBManager
from shared import _force_symlink, _primary_key_fingerprints, _valid_signature_fingerprints


def _answers(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))


# ====================== backup_manager ======================


def _backup_manager(tmp_path: Path) -> BackupManager:
    return BackupManager(
        printer=mock.MagicMock(),
        systemd=mock.MagicMock(),
        install_dir=tmp_path,
    )


def test_backup_menu_invalid_choice_then_exit(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    monkeypatch.setattr(backup_manager_module.os, "system", lambda _cmd: 0)
    _answers(monkeypatch, ["9", "", "0"])
    bm.menu()
    bm.printer.error.assert_called_with("Invalid choice")


def _fake_extract_tar(product: str):
    def fake(_backup, extraction_root, expected_top_level=None):
        staged = Path(extraction_root) / (expected_top_level or product)
        staged.mkdir(parents=True)
        (staged / "app.js").write_text("restored")
        return Path(extraction_root)

    return fake


def _rename_recreates_source(monkeypatch):
    """Wrap Path.rename so moving the install dir aside re-creates it (race)."""
    original = Path.rename

    def fake(self, target):
        result = original(self, target)
        if ".rollback-" in Path(target).name:
            self.mkdir()
        return result

    monkeypatch.setattr(Path, "rename", fake)


def test_restore_target_reappears_and_recovery_succeeds(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    bm.systemd.get_status.return_value = "inactive"
    install = tmp_path / "plexstaff"
    install.mkdir()
    (install / "old.js").write_text("old")
    monkeypatch.setattr(backup_manager_module, "safe_extract_tar", _fake_extract_tar("plexstaff"))
    monkeypatch.setattr(bm, "_set_permissions", lambda _p: None)
    _rename_recreates_source(monkeypatch)
    bm.restore_from_backup(tmp_path / "plexstaff_backup_x.tar.gz", "plexstaff")
    # previous installation was restored from the rollback copy
    assert (install / "old.js").exists()
    bm.printer.error.assert_any_call(mock.ANY)


def test_restore_target_reappears_and_cleanup_fails(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    bm.systemd.get_status.return_value = "inactive"
    install = tmp_path / "plexstaff"
    install.mkdir()
    monkeypatch.setattr(backup_manager_module, "safe_extract_tar", _fake_extract_tar("plexstaff"))
    monkeypatch.setattr(bm, "_set_permissions", lambda _p: None)
    _rename_recreates_source(monkeypatch)
    monkeypatch.setattr(backup_manager_module.shutil, "rmtree", mock.MagicMock(side_effect=OSError("stuck")))
    bm.restore_from_backup(tmp_path / "plexstaff_backup_x.tar.gz", "plexstaff")
    errors = [str(c.args[0]) for c in bm.printer.error.call_args_list]
    assert any("Could not clear failed restore target" in e for e in errors)
    assert any("remains preserved" in e for e in errors)


def test_restore_success_rollback_removal_fails(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    bm.systemd.get_status.return_value = "inactive"
    install = tmp_path / "plexstaff"
    install.mkdir()
    (install / "old.js").write_text("old")
    monkeypatch.setattr(backup_manager_module, "safe_extract_tar", _fake_extract_tar("plexstaff"))
    monkeypatch.setattr(bm, "_set_permissions", lambda _p: None)
    real_rmtree = real_shutil.rmtree

    def selective_rmtree(path, *args, **kwargs):
        if ".rollback-" in Path(path).name:
            raise OSError("busy")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(backup_manager_module.shutil, "rmtree", selective_rmtree)
    bm.restore_from_backup(tmp_path / "plexstaff_backup_x.tar.gz", "plexstaff")
    assert (install / "app.js").exists()
    warnings = [str(c.args[0]) for c in bm.printer.warning.call_args_list]
    assert any("Could not remove rollback copy" in w for w in warnings)


def test_restore_failure_after_publish_unlinks_symlink(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    bm.systemd.get_status.return_value = "inactive"
    real_dir = tmp_path / "payload-target"
    real_dir.mkdir()

    def fake_extract(_backup, extraction_root, expected_top_level=None):
        root = Path(extraction_root)
        root.mkdir(parents=True)
        (root / "plexstaff").symlink_to(real_dir)
        return root

    monkeypatch.setattr(backup_manager_module, "safe_extract_tar", fake_extract)
    monkeypatch.setattr(bm, "_set_permissions", lambda _p: None)

    def raising_success(message):
        if "complete" in message:
            raise RuntimeError("late failure")

    bm.printer.success.side_effect = raising_success
    bm.restore_from_backup(tmp_path / "plexstaff_backup_x.tar.gz", "plexstaff")
    assert not (tmp_path / "plexstaff").exists()
    assert not (tmp_path / "plexstaff").is_symlink()


def test_backup_set_permissions_isolated_user_mismatch(tmp_path, monkeypatch):
    install = tmp_path / "plexstaff"
    install.mkdir()
    (install / ".plexinstaller-resources.json").write_text(
        json.dumps({"service_isolated": True, "service_user": "someone-else"})
    )
    run = mock.MagicMock()
    monkeypatch.setattr(backup_manager_module.subprocess, "run", run)
    BackupManager._set_permissions(install)
    assert run.call_args_list[0].args[0][:2] == ["chown", "-R"]
    assert "root:root" in run.call_args_list[0].args[0]


# ====================== addon_manager ======================


def test_validate_yaml_error_without_problem_mark(tmp_path, monkeypatch):
    manager = AddonManager()
    config = tmp_path / "config.yml"
    config.write_text("a: 1\n")
    monkeypatch.setattr(
        addon_manager_module.yaml, "safe_load", mock.MagicMock(side_effect=yaml.YAMLError("plain error"))
    )
    ok, error = manager.validate_yaml(config)
    assert ok is False
    assert error == "plain error"


def test_list_addon_backups_skips_broken_entries(tmp_path, monkeypatch):
    manager = AddonManager()
    product_path = tmp_path / "plextickets"
    product_path.mkdir()
    backup_dir = tmp_path / "backups" / "addons"
    backup_dir.mkdir(parents=True)
    (backup_dir / "plextickets_myaddon_addon_20260101_120000.tar.gz").write_bytes(b"x")
    fake_datetime = mock.MagicMock()
    fake_datetime.strptime.side_effect = RuntimeError("clock broke")
    monkeypatch.setattr(addon_manager_module, "datetime", fake_datetime)
    assert manager.list_addon_backups(product_path) == []


# ====================== health_checker ======================


def test_print_summary_failure_without_hint(tmp_path):
    checker = HealthChecker(
        printer=mock.MagicMock(),
        systemd=mock.MagicMock(),
        install_dir=tmp_path,
        node_min_version=18,
        nginx_available=tmp_path,
        nginx_enabled=tmp_path,
    )
    results = [
        SelfTestResult(name="a", status="pass", detail="ok"),
        SelfTestResult(name="b", status="warn", detail="meh"),
        SelfTestResult(name="c", status="fail", detail="bad"),
    ]
    checker.print_summary(results)
    checker.printer.error.assert_any_call("c: bad")


# ====================== shared ======================


def test_download_bytes_without_geturl(monkeypatch):
    class FakeResponse:
        def read(self, _n=None):
            return b"payload"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(shared_module.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse())
    content = shared_module._download_bytes("https://example.com/f", max_bytes=100, timeout=5)
    assert content == b"payload"


def test_primary_key_fingerprints_ignores_unexpected_fpr():
    output = "fpr:::::::::AABB:\npub:u:255:22:ID:1:0::u:::scESC:\nfpr:::::::::CCDD:\n"
    assert _primary_key_fingerprints(output) == ["CCDD"]


def test_valid_signature_fingerprints_skips_short_lines():
    output = "short line\n[GNUPG:] VALIDSIG AABBCC 2026-01-01 1 0 0 0 0 00 01 X DDEEFF\n"
    assert "AABBCC" in _valid_signature_fingerprints(output)
    assert "DDEEFF" in _valid_signature_fingerprints(output)


def test_force_symlink_missing_target_returns(tmp_path):
    _force_symlink(tmp_path / "link", tmp_path / "missing-target")
    assert not (tmp_path / "link").exists()


def test_force_symlink_typeerror_fallback(tmp_path, monkeypatch):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.write_text("plain file")
    import os as real_os

    original_unlink = Path.unlink

    calls = {"count": 0}

    def fake_unlink(self, missing_ok=False):
        calls["count"] += 1
        if calls["count"] == 1:
            real_os.unlink(self)
            raise TypeError("missing_ok not supported")
        return original_unlink(self)

    monkeypatch.setattr(Path, "unlink", fake_unlink)
    _force_symlink(link, target)
    assert link.is_symlink()


# ====================== mongodb_manager ======================


def test_save_credentials_closes_fd_when_fdopen_fails(tmp_path, monkeypatch):
    mgr = MongoDBManager(
        printer=mock.MagicMock(),
        system=mock.MagicMock(),
        mongodb_version="7.0",
        mongodb_repo_version_bookworm="7.0",
    )
    import mongodb_manager as mm

    creds_dir = tmp_path / "etc-plex"

    real_path = mm.Path

    monkeypatch.setattr(mm, "Path", lambda p: creds_dir if p == "/etc/plex" else real_path(p))
    closed = []
    monkeypatch.setattr(mm.os, "fdopen", mock.MagicMock(side_effect=RuntimeError("fdopen broke")))
    real_close = mm.os.close
    monkeypatch.setattr(mm.os, "close", lambda fd: (closed.append(fd), real_close(fd)))
    with pytest.raises(RuntimeError, match="fdopen broke"):
        mgr.save_credentials("plexstaff", {"database": "d", "username": "u", "password": "p", "uri": "m"})
    assert closed


def test_default_wait_for_tcp_port_retries_on_oserror(monkeypatch):
    import socket as real_socket

    monkeypatch.setattr(real_socket, "create_connection", mock.MagicMock(side_effect=OSError("refused")))
    import time as real_time

    ticks = iter([0.0, 0.1, 0.2, 100.0])
    monkeypatch.setattr(real_time, "time", lambda: next(ticks))
    monkeypatch.setattr(real_time, "sleep", lambda _s: None)
    assert MongoDBManager._default_wait_for_tcp_port("127.0.0.1", 27017, timeout_seconds=1) is False


# ====================== plex_cli ======================


@pytest.fixture
def install_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    return tmp_path


def make_app(install_dir: Path, name: str, config: str | None = None, config_name: str = "config.yml") -> Path:
    app = install_dir / name
    app.mkdir()
    (app / "package.json").write_text("{}")
    if config is not None:
        (app / config_name).write_text(config)
    return app


def test_redact_debug_text_without_yaml_helper(monkeypatch):
    monkeypatch.setattr(plex_cli, "redact_sensitive_yaml", None)
    result = plex_cli.redact_debug_text("mongodb://user:pass@host/db")
    assert "<REDACTED>" in result


def test_read_local_installer_version_swallows_exceptions(monkeypatch):
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", None)
    assert plex_cli._read_local_installer_version() == "0.0.0"


def test_ensure_cli_entrypoints_fallback(tmp_path, monkeypatch):
    installer_dir = tmp_path / "bundle"
    installer_dir.mkdir()
    (installer_dir / "installer.py").write_text("# installer")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "plexinstaller").write_text("old file")  # replaced by symlink
    monkeypatch.setattr(plex_cli, "ensure_cli_entrypoints", None)
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", installer_dir)
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(plex_cli, "Path", lambda _p: bin_dir)
    plex_cli._ensure_cli_entrypoints()
    assert (bin_dir / "plexinstaller").is_symlink()
    # plex_cli.py did not exist -> no link created
    assert not (bin_dir / "plex").exists()


def test_maybe_auto_update_remote_not_newer(monkeypatch):
    payload = json.dumps({"version": "0.0.1"}).encode()

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(plex_cli.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse(payload))
    monkeypatch.setattr(plex_cli, "_verify_gpg_signature", lambda _b: True)
    monkeypatch.setattr(plex_cli, "_read_local_installer_version", lambda: "99.0.0")
    ensure = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_ensure_cli_entrypoints", ensure)
    perform = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_perform_update", perform)
    plex_cli._maybe_auto_update()
    perform.assert_not_called()
    ensure.assert_called_once()


def test_show_status_subprocess_failure(install_dir: Path):
    make_app(install_dir, "plextickets")
    error = real_subprocess.CalledProcessError(1, ["systemctl"])
    with mock.patch("plex_cli.subprocess.run", side_effect=error):
        assert plex_cli.show_status("plextickets") == 1


def test_view_logs_subprocess_failure(install_dir: Path):
    make_app(install_dir, "plextickets")
    error = real_subprocess.CalledProcessError(1, ["journalctl"])
    with mock.patch("plex_cli.subprocess.run", side_effect=error):
        assert plex_cli.view_logs("plextickets") == 1


def _completed(stdout: str = "ok") -> real_subprocess.CompletedProcess:
    return real_subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_debug_app_without_config_module(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"url": "https://paste/x"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    monkeypatch.setattr(plex_cli, "Config", None)
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0


def test_debug_app_paste_endpoint_lookup_fails(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")

    class BrokenConfig:
        @property
        def PASTE_ENDPOINT(self):  # noqa: N802 - mimics real constant
            raise RuntimeError("no endpoint")

    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"url": "https://paste/x"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    monkeypatch.setattr(plex_cli, "Config", BrokenConfig())
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0


def test_debug_app_builds_url_from_key_and_documents_endpoint(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"key": "abcd"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    monkeypatch.setattr(plex_cli, "Config", SimpleNamespace(PASTE_ENDPOINT="https://paste.example/documents"))
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0


def test_get_addon_manager_returns_instance(monkeypatch):
    fake_cls = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "AddonManager", fake_cls)
    assert plex_cli._get_addon_manager() is fake_cls.return_value


# ---------- tool setupdomain ----------


def _fake_web_stack(tmp_path, monkeypatch, *, dns_ok=True, nginx_setup_error=None):
    import utils as utils_module

    nginx = mock.MagicMock()
    nginx.config.nginx_available = tmp_path / "avail"
    nginx.config.nginx_enabled = tmp_path / "enabled"
    nginx.config.nginx_available.mkdir(exist_ok=True)
    nginx.config.nginx_enabled.mkdir(exist_ok=True)
    if nginx_setup_error is not None:
        nginx.setup.side_effect = nginx_setup_error
    dns = mock.MagicMock()
    dns.check.return_value = dns_ok
    monkeypatch.setattr(utils_module, "DNSChecker", mock.MagicMock(return_value=dns))
    monkeypatch.setattr(utils_module, "FirewallManager", mock.MagicMock())
    monkeypatch.setattr(utils_module, "NginxManager", mock.MagicMock(return_value=nginx))
    monkeypatch.setattr(utils_module, "SSLManager", mock.MagicMock())
    return nginx


def test_setupdomain_config_fallbacks_and_nginx_failure(install_dir: Path, tmp_path, monkeypatch):
    app = make_app(install_dir, "plextickets", config="name: no-port-here\n")
    (app / "config.yaml").mkdir()  # read_text raises -> swallowed
    (app / "config.json").write_text('{"port": "not-a-number"}')
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    _fake_web_stack(tmp_path, monkeypatch, dns_ok=False, nginx_setup_error=RuntimeError("nginx broke"))
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        _answers(
            monkeypatch,
            [
                "abc",  # port: not a number
                "70000",  # port: out of range
                "8080",  # port: valid
                "",  # domain: empty
                "bad_domain!",  # domain: invalid
                "app.example.com",  # domain: valid
                "",  # email: empty
                "not-an-email",  # email: invalid
                "admin@example.com",  # email: valid
                "y",  # proceed despite DNS failure
            ],
        )
        assert plex_cli.tool_setupdomain("plextickets") == 1


def test_setupdomain_utils_fallback_missing_bundle(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="port: 3000\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", install_dir / "empty-bundle")
    import types

    monkeypatch.setitem(sys.modules, "utils", types.ModuleType("utils"))  # force ImportError
    _answers(monkeypatch, ["y", "app.example.com", "admin@example.com"])
    assert plex_cli.tool_setupdomain("plextickets") == 1


def test_setupdomain_utils_fallback_loads_from_installer_dir(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="port: 3000\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    repo_root = Path(__file__).resolve().parent.parent
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", repo_root)
    import types

    monkeypatch.setitem(sys.modules, "utils", types.ModuleType("utils"))  # force ImportError -> file fallback
    import socket as real_socket

    monkeypatch.setattr(real_socket, "gethostbyname", mock.MagicMock(return_value="203.0.113.9"))
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        with mock.patch("urllib.request.urlopen", side_effect=OSError("no network")):
            _answers(
                monkeypatch,
                [
                    "y",  # keep detected port
                    "app.example.com",
                    "admin@example.com",
                    "n",  # abort after DNS check failure
                ],
            )
            assert plex_cli.tool_setupdomain("plextickets") == 1


def test_rollback_setupdomain_handles_unlink_oserror(tmp_path, monkeypatch):
    enabled = tmp_path / "enabled"
    enabled.mkdir()
    conf_dir = enabled / "app.example.com.conf"
    conf_dir.mkdir()  # unlink on a directory raises OSError
    (conf_dir / "keep").write_text("x")
    nginx = SimpleNamespace(config=SimpleNamespace(nginx_enabled=enabled, nginx_available=None))
    with mock.patch("plex_cli.subprocess.run", side_effect=OSError("no certbot")):
        plex_cli._rollback_setupdomain("app.example.com", nginx=nginx, ssl_manager=mock.MagicMock(), remove_nginx=True)
    assert conf_dir.exists()


def test_record_domain_resources_ignores_non_dict_manifest(tmp_path):
    app_dir = tmp_path / "plextickets"
    app_dir.mkdir()
    manifest = app_dir / ".plexinstaller-resources.json"
    manifest.write_text("[1, 2, 3]")
    plex_cli._record_domain_resources(app_dir, "plextickets", "app.example.com", 3000)
    data = json.loads(manifest.read_text())
    assert data["domain"] == "app.example.com"
    assert data["service"] == "plex-plextickets"


# guard against unused-import lint complaints in future edits
assert real_shutil is not None


# ====================== final branch sweeps ======================


def test_write_entrypoint_closes_fd_on_write_failure(tmp_path, monkeypatch):
    script = tmp_path / "script.py"
    script.write_text("print('hi')")
    entrypoint = tmp_path / "plex"
    monkeypatch.setattr(shared_module.os, "write", mock.MagicMock(side_effect=OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        shared_module._write_entrypoint(entrypoint, script)
    assert not entrypoint.exists()
    assert not list(tmp_path.glob(".plex.*"))


def test_restore_target_reappears_as_symlink_and_is_unlinked(tmp_path, monkeypatch):
    bm = _backup_manager(tmp_path)
    bm.systemd.get_status.return_value = "inactive"
    payload = tmp_path / "somewhere-else"
    payload.mkdir()
    install = tmp_path / "plexstaff"
    install.symlink_to(payload)
    monkeypatch.setattr(backup_manager_module, "safe_extract_tar", _fake_extract_tar("plexstaff"))
    monkeypatch.setattr(bm, "_set_permissions", lambda _p: None)
    original = Path.rename

    def fake_rename(self, target):
        result = original(self, target)
        if ".rollback-" in Path(target).name:
            self.symlink_to(payload)  # target "reappears" as a symlink
        return result

    monkeypatch.setattr(Path, "rename", fake_rename)
    bm.restore_from_backup(tmp_path / "plexstaff_backup_x.tar.gz", "plexstaff")
    # symlink was unlinked and previous installation restored
    assert install.is_symlink()
    assert install.resolve() == payload.resolve()


def test_ensure_cli_entrypoints_fallback_creates_missing_link(tmp_path, monkeypatch):
    installer_dir = tmp_path / "bundle"
    installer_dir.mkdir()
    (installer_dir / "installer.py").write_text("# installer")
    (installer_dir / "plex_cli.py").write_text("# cli")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setattr(plex_cli, "ensure_cli_entrypoints", None)
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", installer_dir)
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(plex_cli, "Path", lambda _p: bin_dir)
    plex_cli._ensure_cli_entrypoints()
    assert (bin_dir / "plexinstaller").is_symlink()
    assert (bin_dir / "plex").is_symlink()


def test_ensure_cli_entrypoints_fallback_swallows_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(plex_cli, "ensure_cli_entrypoints", None)
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", tmp_path)
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    broken_dir = mock.MagicMock()
    broken_dir.mkdir.side_effect = OSError("read-only fs")
    monkeypatch.setattr(plex_cli, "Path", lambda _p: broken_dir)
    plex_cli._ensure_cli_entrypoints()  # must not raise


def test_debug_app_key_with_non_documents_endpoint(install_dir: Path, monkeypatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"key": "abcd"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    monkeypatch.setattr(plex_cli, "Config", SimpleNamespace(PASTE_ENDPOINT="https://paste.example"))
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0


def test_rollback_setupdomain_without_nginx_removal(monkeypatch):
    nginx = SimpleNamespace(config=None)
    with mock.patch("plex_cli.subprocess.run", return_value=_completed()):
        plex_cli._rollback_setupdomain("app.example.com", nginx=nginx, ssl_manager=mock.MagicMock(), remove_nginx=False)
