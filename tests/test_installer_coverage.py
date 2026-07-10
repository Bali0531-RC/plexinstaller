"""Broad coverage tests for installer.py core flows (no system interaction)."""

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

import installer as installer_module
from config import Config
from health_checker import SelfTestResult
from installer import InstallationContext, PlexInstaller, UserAbortError


def _installer(tmp_path: Path) -> PlexInstaller:
    inst = object.__new__(PlexInstaller)
    inst.version = "stable"
    inst.config = Config()
    inst.config.install_dir = tmp_path
    inst.printer = mock.MagicMock()
    inst.assume_yes = False
    inst.non_interactive = False
    inst.isolate_services = None
    inst.telemetry_enabled = True
    inst.check_updates = False
    inst.systemd = mock.MagicMock()
    inst.firewall = mock.MagicMock()
    inst.mongo_manager = mock.MagicMock()
    inst.health = mock.MagicMock()
    inst.backup_mgr = mock.MagicMock()
    inst.telemetry = mock.MagicMock()
    inst.extractor = mock.MagicMock()
    inst.nginx = mock.MagicMock()
    inst.ssl = mock.MagicMock()
    inst.dns_checker = mock.MagicMock()
    inst.addon_manager = mock.MagicMock()
    inst.system = mock.MagicMock()
    inst._lock_fd = None
    return inst


def _answers(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))


# ---------- construction / locking ----------


def _patched_init_env(monkeypatch, tmp_path):
    monkeypatch.setattr("installer.os.geteuid", lambda: 0)
    for name in (
        "SystemDetector",
        "DNSChecker",
        "FirewallManager",
        "NginxManager",
        "SSLManager",
        "SystemdManager",
        "ArchiveExtractor",
        "AddonManager",
        "MongoDBManager",
        "BackupManager",
        "HealthChecker",
        "TelemetryClient",
    ):
        monkeypatch.setattr(f"installer.{name}", mock.MagicMock())
    monkeypatch.setattr("installer.atexit.register", lambda *_a, **_k: None)
    monkeypatch.setattr(PlexInstaller, "_initialize_telemetry_preference", lambda self: False)


def test_init_builds_managers(monkeypatch, tmp_path):
    _patched_init_env(monkeypatch, tmp_path)
    monkeypatch.setattr(PlexInstaller, "_acquire_lock", lambda self: True)
    inst = PlexInstaller(assume_yes=True, non_interactive=True, check_updates=False)
    assert inst.assume_yes is True
    assert inst.telemetry_enabled is False


def test_init_requires_root(monkeypatch, tmp_path):
    _patched_init_env(monkeypatch, tmp_path)
    monkeypatch.setattr("installer.os.geteuid", lambda: 1000)
    with pytest.raises(SystemExit):
        PlexInstaller()


def test_init_exits_when_lock_held(monkeypatch, tmp_path):
    _patched_init_env(monkeypatch, tmp_path)
    monkeypatch.setattr(PlexInstaller, "_acquire_lock", lambda self: False)
    with pytest.raises(SystemExit):
        PlexInstaller()


def test_acquire_and_release_lock(monkeypatch, tmp_path):
    lock_file = tmp_path / "lock"
    monkeypatch.setattr("installer.LOCK_FILE", str(lock_file))
    inst = _installer(tmp_path)
    assert inst._acquire_lock() is True
    assert lock_file.exists()
    inst._release_lock()
    assert inst._lock_fd is None
    assert not lock_file.exists()
    # Second release is a no-op
    inst._release_lock()


def test_acquire_lock_failure(monkeypatch, tmp_path):
    monkeypatch.setattr("installer.LOCK_FILE", str(tmp_path / "nodir" / "lock"))
    inst = _installer(tmp_path)
    assert inst._acquire_lock() is False


# ---------- run / banner / confirm / deps ----------


def test_run_with_missing_deps_repairs(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.telemetry_enabled = False
    inst.check_updates = True
    inst._check_for_updates = mock.MagicMock()
    inst._missing_dependencies = mock.MagicMock(return_value=["node"])
    inst._confirm = mock.MagicMock(return_value=True)
    inst._show_main_menu = mock.MagicMock(return_value=0)
    monkeypatch.setattr("installer.os.system", lambda *_a: 0)
    assert inst.run() == 0
    inst.system.install_dependencies.assert_called_once()
    inst._check_for_updates.assert_called_once()


def test_run_with_missing_deps_declined(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._missing_dependencies = mock.MagicMock(return_value=["npm"])
    inst._confirm = mock.MagicMock(return_value=False)
    inst._show_main_menu = mock.MagicMock(return_value=0)
    monkeypatch.setattr("installer.os.system", lambda *_a: 0)
    assert inst.run() == 0
    inst.system.install_dependencies.assert_not_called()


def test_display_banner_prints(tmp_path, capsys):
    inst = _installer(tmp_path)
    inst._display_banner()
    assert "UNOFFICIAL" in capsys.readouterr().out


def test_confirm_assume_yes(tmp_path):
    inst = _installer(tmp_path)
    inst.assume_yes = True
    assert inst._confirm("q?") is True


def test_confirm_non_interactive_default(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    assert inst._confirm("q?", default=True) is True
    assert inst._confirm("q?", default=False) is False


def test_confirm_interactive_answers(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    _answers(monkeypatch, ["y", "no", ""])
    assert inst._confirm("q?") is True
    assert inst._confirm("q?") is False
    assert inst._confirm("q?", default=True) is True


def test_missing_dependencies(monkeypatch):
    monkeypatch.setattr("installer.shutil.which", lambda cmd: None if cmd == "npm" else "/usr/bin/x")
    assert PlexInstaller._missing_dependencies() == ["npm"]


# ---------- telemetry preference ----------


def test_initialize_telemetry_pref_disabled(tmp_path):
    inst = _installer(tmp_path)
    pref = tmp_path / "pref"
    pref.write_text("disabled\n")
    inst.config.telemetry_pref_file = pref
    assert inst._initialize_telemetry_preference() is False


def test_initialize_telemetry_pref_enabled(tmp_path):
    inst = _installer(tmp_path)
    pref = tmp_path / "pref"
    pref.write_text("enabled\n")
    inst.config.telemetry_pref_file = pref
    assert inst._initialize_telemetry_preference() is True


def test_initialize_telemetry_pref_read_error_prompts(tmp_path):
    inst = _installer(tmp_path)
    pref = mock.MagicMock()
    pref.exists.side_effect = OSError("boom")
    inst.config.telemetry_pref_file = pref
    inst._prompt_telemetry_preference = mock.MagicMock(return_value=True)
    assert inst._initialize_telemetry_preference() is True
    inst.printer.warning.assert_called()


def test_prompt_telemetry_enabled(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=True)
    pref = tmp_path / "pref"
    assert inst._prompt_telemetry_preference(pref) is True
    assert pref.read_text() == "enabled\n"


def test_prompt_telemetry_write_failure_warns(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=False)
    pref = mock.MagicMock()
    pref.parent.mkdir.side_effect = OSError("ro")
    assert inst._prompt_telemetry_preference(pref) is False
    inst.printer.warning.assert_called()


# ---------- update check ----------


def _urlopen_returning(payload: bytes):
    ctx = mock.MagicMock()
    ctx.__enter__.return_value.read.return_value = payload
    return mock.MagicMock(return_value=ctx)


def test_check_updates_unauthenticated_manifest(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    payload = json.dumps({"version": "99.0.0"}).encode()
    monkeypatch.setattr("installer.urllib.request.urlopen", _urlopen_returning(payload))
    inst._verify_gpg_signature = mock.MagicMock(return_value=False)
    inst._perform_update = mock.MagicMock()
    inst._check_for_updates()
    inst._perform_update.assert_not_called()


def test_check_updates_newer_declined(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    payload = json.dumps({"version": "99.0.0", "changelog": ["fixes"]}).encode()
    monkeypatch.setattr("installer.urllib.request.urlopen", _urlopen_returning(payload))
    inst._verify_gpg_signature = mock.MagicMock(return_value=True)
    inst._confirm = mock.MagicMock(return_value=False)
    inst._perform_update = mock.MagicMock()
    inst._download_missing_files = mock.MagicMock()
    inst._ensure_cli_entrypoints = mock.MagicMock()
    inst._check_for_updates()
    inst._perform_update.assert_not_called()


def test_check_updates_newer_accepted(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    payload = json.dumps({"version": "99.0.0"}).encode()
    monkeypatch.setattr("installer.urllib.request.urlopen", _urlopen_returning(payload))
    inst._verify_gpg_signature = mock.MagicMock(return_value=True)
    inst._confirm = mock.MagicMock(return_value=True)
    inst._perform_update = mock.MagicMock()
    inst._download_missing_files = mock.MagicMock()
    inst._ensure_cli_entrypoints = mock.MagicMock()
    inst._check_for_updates()
    inst._perform_update.assert_called_once()


def test_check_updates_up_to_date(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    payload = json.dumps({"version": "0.0.1"}).encode()
    monkeypatch.setattr("installer.urllib.request.urlopen", _urlopen_returning(payload))
    inst._verify_gpg_signature = mock.MagicMock(return_value=True)
    inst._download_missing_files = mock.MagicMock()
    inst._ensure_cli_entrypoints = mock.MagicMock()
    inst._check_for_updates()
    inst.printer.success.assert_called()


def test_check_updates_network_failure(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer.urllib.request.urlopen", mock.MagicMock(side_effect=OSError("offline")))
    inst._check_for_updates()
    inst.printer.warning.assert_called()


def test_download_missing_files_uses_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    shared = mock.MagicMock()
    monkeypatch.setattr("installer._shared_download_missing", shared)
    inst._download_missing_files({})
    shared.assert_called_once()


def test_download_missing_files_without_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer._shared_download_missing", None)
    inst._download_missing_files({})
    inst.printer.warning.assert_called()


def test_ensure_cli_entrypoints(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    shared = mock.MagicMock()
    monkeypatch.setattr("installer._shared_ensure_cli", shared)
    inst._ensure_cli_entrypoints()
    shared.assert_called_once()
    monkeypatch.setattr("installer._shared_ensure_cli", None)
    inst._ensure_cli_entrypoints()


def test_is_newer_version_fallback(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer._shared_is_newer", None)
    assert inst._is_newer_version("2.0", "1.9.9") is True
    assert inst._is_newer_version("1.0.0", "1.0") is False
    assert inst._is_newer_version("bogus", "1.0") is False


def test_verify_gpg_without_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer._shared_verify_gpg", None)
    assert inst._verify_gpg_signature(b"data") is False


def test_verify_gpg_with_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer._shared_verify_gpg", mock.MagicMock(return_value=True))
    assert inst._verify_gpg_signature(b"data") is True


def test_perform_update_without_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setattr("installer._shared_perform_update", None)
    inst._perform_update({})
    inst.printer.warning.assert_called()


def test_perform_update_with_shared(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    shared = mock.MagicMock()
    monkeypatch.setattr("installer._shared_perform_update", shared)
    inst._perform_update({"version": "1"}, b"raw")
    shared.assert_called_once()


# ---------- archive finding / extraction ----------


def test_find_archive_manual_path_found(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    archive = tmp_path / "outside" / "custom-archive.zip"
    archive.parent.mkdir()
    archive.write_bytes(b"x")
    monkeypatch.setattr("installer.Path.home", lambda: empty)
    monkeypatch.setattr("installer.Path.cwd", lambda: empty)
    _answers(monkeypatch, [str(archive)])
    assert inst._find_archive("zzq1prod") == archive


def test_find_archive_manual_path_missing(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setattr("installer.Path.home", lambda: empty)
    monkeypatch.setattr("installer.Path.cwd", lambda: empty)
    _answers(monkeypatch, ["/nonexistent/file.zip"])
    assert inst._find_archive("zzq2prod") is None


def test_find_archive_custom_path_choice(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "zzq3prod-a.zip").write_bytes(b"x")
    custom = tmp_path / "custom.zip"
    custom.write_bytes(b"x")
    monkeypatch.setattr("installer.Path.home", lambda: tmp_path)
    monkeypatch.setattr("installer.Path.cwd", lambda: tmp_path)
    _answers(monkeypatch, ["0", str(custom)])
    assert inst._find_archive("zzq3prod") == custom


def test_find_archive_invalid_choice(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "zzq4prod-a.zip").write_bytes(b"x")
    monkeypatch.setattr("installer.Path.home", lambda: tmp_path)
    monkeypatch.setattr("installer.Path.cwd", lambda: tmp_path)
    _answers(monkeypatch, ["nope"])
    assert inst._find_archive("zzq4prod") is None


def test_find_archive_out_of_range_choice(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "zzq5prod-a.zip").write_bytes(b"x")
    monkeypatch.setattr("installer.Path.home", lambda: tmp_path)
    monkeypatch.setattr("installer.Path.cwd", lambda: tmp_path)
    _answers(monkeypatch, ["99"])
    assert inst._find_archive("zzq5prod") is None


def test_extract_product_refuses_existing(tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "inst").mkdir()
    assert inst._extract_product(tmp_path / "a.zip", "inst") is None


def test_extract_product_extraction_error(tmp_path):
    inst = _installer(tmp_path)
    inst.extractor.extract.side_effect = RuntimeError("bad archive")
    assert inst._extract_product(tmp_path / "a.zip", "inst") is None


def test_extract_product_success(tmp_path):
    inst = _installer(tmp_path)
    inst.extractor.extract.return_value = str(tmp_path / "inst")
    assert inst._extract_product(tmp_path / "a.zip", "inst") == tmp_path / "inst"


# ---------- npm / 502 page ----------


def test_npm_install_no_package_json(tmp_path):
    inst = _installer(tmp_path)
    assert inst._install_npm_dependencies(tmp_path) is False


def test_npm_install_failure(tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "package.json").write_text("{}")
    err = subprocess.CalledProcessError(1, "npm", stderr=b"broken")
    with mock.patch("installer.subprocess.run", side_effect=err):
        assert inst._install_npm_dependencies(tmp_path) is False


def test_create_502_page(tmp_path):
    inst = _installer(tmp_path)
    inst._create_502_page(tmp_path, "plexstaff")
    assert "502" in (tmp_path / "502.html").read_text()


# ---------- port selection / web setup ----------


def test_select_port_interactive_retry(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.is_port_available = mock.MagicMock(side_effect=[False, True])
    _answers(monkeypatch, ["70000", "abc", "3005", "3006"])
    assert inst._select_available_port(3000) == 3006


def test_select_port_non_interactive_invalid_default(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    with pytest.raises(UserAbortError, match="Invalid port"):
        inst._select_available_port(0)


def _web_context(tmp_path):
    return InstallationContext("plexstaff", "plexstaff", tmp_path, 3001)


def test_setup_web_happy_path(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.nginx_available.mkdir()
    inst.config.nginx_enabled.mkdir()
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst.config.persist_app_port = mock.MagicMock()
    inst.dns_checker.check.return_value = True
    ctx = _web_context(tmp_path)
    _answers(monkeypatch, ["3001", "", "bad_domain!", "app.example.com", "", "not-an-email", "a@b.com"])
    domain, port, email = inst._setup_web("plexstaff", 3001, tmp_path, ctx)
    assert (domain, port, email) == ("app.example.com", 3001, "a@b.com")
    assert ctx.nginx_configured and ctx.ssl_configured
    inst.firewall.close_port.assert_called_once_with(3001)


def test_setup_web_dns_failure_abort(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst.config.persist_app_port = mock.MagicMock()
    inst.dns_checker.check.return_value = False
    ctx = _web_context(tmp_path)
    _answers(monkeypatch, ["3001", "app.example.com", "a@b.com", "n"])
    with pytest.raises(UserAbortError, match="DNS"):
        inst._setup_web("plexstaff", 3001, tmp_path, ctx)


def test_setup_web_existing_nginx_config(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.nginx_available.mkdir()
    inst.config.nginx_enabled.mkdir()
    (inst.config.nginx_available / "app.example.com.conf").write_text("x")
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst.config.persist_app_port = mock.MagicMock()
    inst.dns_checker.check.return_value = True
    ctx = _web_context(tmp_path)
    _answers(monkeypatch, ["3001", "app.example.com", "a@b.com"])
    with pytest.raises(UserAbortError, match="already exists"):
        inst._setup_web("plexstaff", 3001, tmp_path, ctx)


def test_setup_web_nginx_failure_rolls_back(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.nginx_available.mkdir()
    inst.config.nginx_enabled.mkdir()
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst.config.persist_app_port = mock.MagicMock()
    inst.dns_checker.check.return_value = True
    inst.nginx.setup.side_effect = RuntimeError("nginx -t failed")
    inst._remove_nginx_config = mock.MagicMock()
    ctx = _web_context(tmp_path)
    _answers(monkeypatch, ["3001", "app.example.com", "a@b.com", "y"])
    inst.dns_checker.check.return_value = False  # also exercise DNS proceed-anyway
    with pytest.raises(RuntimeError):
        inst._setup_web("plexstaff", 3001, tmp_path, ctx)
    inst._remove_nginx_config.assert_called_once_with("app.example.com")
    assert ctx.nginx_configured is False


def test_setup_web_firewall_close_warning(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.nginx_available.mkdir()
    inst.config.nginx_enabled.mkdir()
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst.config.persist_app_port = mock.MagicMock()
    inst.dns_checker.check.return_value = True
    inst.firewall.close_port.side_effect = RuntimeError("ufw broken")
    ctx = _web_context(tmp_path)
    _answers(monkeypatch, ["3001", "app.example.com", "a@b.com"])
    domain, _port, _email = inst._setup_web("plexstaff", 3001, tmp_path, ctx)
    assert domain == "app.example.com"
    inst.printer.warning.assert_called()


# ---------- dashboard / systemd ----------


def test_install_dashboard_no_archive(tmp_path):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=None)
    inst._install_dashboard(tmp_path)
    inst.printer.warning.assert_called()


def test_install_dashboard_with_user(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "dash.zip")
    inst.extractor.extract.return_value = tmp_path / "addons" / "Dashboard"
    inst._install_npm_dependencies = mock.MagicMock(return_value=True)
    with mock.patch("installer.subprocess.run") as run:
        inst._install_dashboard(tmp_path, run_as_user="plex-x")
    assert run.call_args.args[0][0] == "chown"
    inst._install_npm_dependencies.assert_called_once()


def test_setup_systemd_declined(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=False)
    assert inst._setup_systemd("x", tmp_path) is False


def test_setup_systemd_isolation_failure_falls_back(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=True)
    calls = []

    def create_service(name, path, **kwargs):
        if kwargs.get("isolated"):
            raise RuntimeError("no isolation")
        calls.append(kwargs)

    inst.systemd.create_service.side_effect = create_service
    inst.systemd.release_service_identity.side_effect = RuntimeError("cleanup fail")
    assert inst._setup_systemd("x", tmp_path, isolated=True) is True
    assert inst._last_service_isolated is False


def test_isolation_requested_env_and_prompt(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.isolate_services = True
    assert inst._isolation_requested() is True
    inst.isolate_services = None
    monkeypatch.setenv("PLEX_ISOLATE_SERVICES", "no")
    assert inst._isolation_requested() is False
    monkeypatch.delenv("PLEX_ISOLATE_SERVICES")
    inst._confirm = mock.MagicMock(return_value=True)
    assert inst._isolation_requested() is True


def test_create_systemd_service_all_signatures_unsupported(tmp_path):
    inst = _installer(tmp_path)
    inst.systemd.create_service.side_effect = TypeError("unexpected kwarg")
    with pytest.raises(RuntimeError, match="does not support"):
        inst._create_systemd_service("x", tmp_path, isolated=True)


# ---------- post install / editor ----------


def test_post_install_with_config_edit(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "config.yml").write_text("Port: 1\n")
    inst._confirm = mock.MagicMock(return_value=True)
    inst._run_editor = mock.MagicMock(return_value=False)
    inst._post_install("x", tmp_path, "app.example.com", True)
    inst.printer.warning.assert_called()
    inst.printer.success.assert_called()


def test_post_install_no_domain(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=False)
    inst._post_install("x", tmp_path, None, True)
    inst.printer.warning.assert_called()


def test_run_editor_success_and_failure(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setenv("EDITOR", "true")
    with mock.patch("installer.subprocess.run", return_value=mock.MagicMock(returncode=0)):
        assert inst._run_editor(tmp_path / "f") is True
    with mock.patch("installer.subprocess.run", return_value=mock.MagicMock(returncode=1)):
        assert inst._run_editor(tmp_path / "f") is False


def test_run_editor_bad_editor_values(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    monkeypatch.setenv("EDITOR", "'unterminated")
    assert inst._run_editor(tmp_path / "f") is False
    monkeypatch.setenv("EDITOR", "")
    assert inst._run_editor(tmp_path / "f") is False
    monkeypatch.setenv("EDITOR", "definitely-not-a-real-editor")
    with mock.patch("installer.subprocess.run", side_effect=OSError("no such file")):
        assert inst._run_editor(tmp_path / "f") is False


# ---------- cleanup / nginx / ssl removal ----------


def test_cleanup_failed_install_full_rollback(tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "inst"
    app.mkdir()
    ctx = InstallationContext(
        "plexstaff",
        "inst",
        app,
        3001,
        domain="app.example.com",
        install_path_created=True,
        service_created=True,
        nginx_paths_created=True,
        ssl_configured=True,
        opened_port=3001,
        service_user="plex-inst",
        service_user_created=True,
    )
    inst.systemd.remove_service.side_effect = RuntimeError("gone")
    inst.systemd.release_service_identity.side_effect = RuntimeError("no user")
    inst._remove_nginx_config = mock.MagicMock()
    inst._remove_ssl_certificate = mock.MagicMock()
    inst._cleanup_failed_install(ctx)
    assert not app.exists()
    inst._remove_nginx_config.assert_called_once()
    inst._remove_ssl_certificate.assert_called_once()
    inst.firewall.close_port.assert_called_once_with(3001)


def test_cleanup_failed_install_mongo_error(tmp_path):
    inst = _installer(tmp_path)
    ctx = InstallationContext("p", "p", tmp_path / "missing", 3001, mongo_identity={"database": "d", "username": "u"})
    inst.mongo_manager.cleanup_identity.side_effect = RuntimeError("mongo down")
    inst._cleanup_failed_install(ctx)
    inst.printer.warning.assert_called()


def test_remove_nginx_config(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.config.nginx_available = tmp_path / "avail"
    inst.config.nginx_enabled = tmp_path / "enabled"
    inst.config.nginx_available.mkdir()
    inst.config.nginx_enabled.mkdir()
    conf = inst.config.nginx_available / "d.conf"
    conf.write_text("x")
    link = inst.config.nginx_enabled / "d.conf"
    link.symlink_to(conf)
    with mock.patch("installer.subprocess.run") as run:
        inst._remove_nginx_config("d")
    assert not conf.exists() and not link.exists()
    assert run.call_count == 2


def test_remove_ssl_certificate_paths(tmp_path):
    inst = _installer(tmp_path)
    with mock.patch("installer.subprocess.run") as run:
        inst._remove_ssl_certificate("d")
    run.assert_called_once()
    err = subprocess.CalledProcessError(1, "certbot")
    with mock.patch("installer.subprocess.run", side_effect=err):
        inst._remove_ssl_certificate("d")
    inst.printer.warning.assert_called()


# ---------- multi-instance / manifest ----------


def test_multi_instance_non_interactive_default_name(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    (tmp_path / "plexstaff").mkdir()
    inst._confirm = mock.MagicMock(return_value=True)
    name = inst._handle_multi_instance("plexstaff")
    assert name.startswith("plexstaff-")


def test_multi_instance_invalid_name_rejected(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "plexstaff").mkdir()
    inst._confirm = mock.MagicMock(return_value=True)
    _answers(monkeypatch, ["bad name!"])
    with pytest.raises(ValueError, match="Invalid instance name"):
        inst._handle_multi_instance("plexstaff")


def test_load_manifest_rejects_bad_fields(tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "inst"
    app.mkdir()
    path = app / installer_module.RESOURCE_MANIFEST

    def write(data):
        path.write_text(json.dumps(data))

    base = {"instance": "inst", "install_path": str(app)}
    for bad in (
        {**base, "service": "plex-other"},
        {**base, "firewall_port": 999999},
        {**base, "domain": "bad domain!"},
        {**base, "mongodb": ["not", "a", "dict"]},
    ):
        write(bad)
        loaded = inst._load_resource_manifest(app, "inst")
        assert loaded["schema_version"] == 0

    path.write_text("{not json")
    assert inst._load_resource_manifest(app, "inst")["schema_version"] == 0

    write({**base, "service": "plex-inst", "firewall_port": 4000, "domain": "ok.example.com", "mongodb": {}})
    assert inst._load_resource_manifest(app, "inst")["firewall_port"] == 4000


def test_uninstall_invalid_name_and_outside_path(tmp_path):
    inst = _installer(tmp_path)
    assert inst._uninstall_product("bad/../name") is False
    outside = tmp_path / "app"
    outside.mkdir()
    inst.config.install_dir = tmp_path / "installs"
    inst.config.install_dir.mkdir()
    (inst.config.install_dir / "link").symlink_to(outside)
    assert inst._uninstall_product("link") is False


def test_uninstall_declined(tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "app").mkdir()
    inst._confirm = mock.MagicMock(return_value=False)
    assert inst._uninstall_product("app") is False


def test_uninstall_with_errors_and_retained_credentials(tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    ctx = InstallationContext(
        "plexstaff",
        "app",
        app,
        3001,
        domain="app.example.com",
        service_created=True,
        nginx_configured=True,
        ssl_configured=True,
        opened_port=3001,
        mongo_identity={"database": "db", "username": "user"},
        service_isolated=True,
        service_user="plex-app",
        service_user_created=True,
    )
    inst._write_resource_manifest(ctx)
    inst._confirm = mock.MagicMock(side_effect=[True, False])
    inst.systemd.stop.side_effect = RuntimeError("stop failed")
    inst.firewall.close_port.side_effect = RuntimeError("fw failed")
    inst.systemd.release_service_identity.side_effect = RuntimeError("user busy")
    inst.mongo_manager.cleanup_identity.return_value = False
    inst._remove_nginx_config = mock.MagicMock()
    inst._remove_ssl_certificate = mock.MagicMock()
    assert inst._uninstall_product("app") is True
    inst.mongo_manager.remove_saved_credentials.assert_not_called()
    assert not app.exists()


def test_uninstall_without_mongo_manager_preserves_data(tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "app"
    app.mkdir()
    ctx = InstallationContext("plexstaff", "app", app, 3001, mongo_identity={"database": "db", "username": "user"})
    inst._write_resource_manifest(ctx)
    inst.mongo_manager = None
    inst._confirm = mock.MagicMock(side_effect=[True, False])
    assert inst._uninstall_product("app") is True
    inst.printer.warning.assert_any_call("MongoDB manager unavailable; stored database resources were preserved")


# ---------- _install_product branches ----------


def _wired_for_install(inst, tmp_path):
    app = tmp_path / "plexstaff"
    inst.extractor.extract.return_value = app
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "plexstaff.zip")
    inst._install_npm_dependencies = mock.MagicMock(return_value=True)
    inst._create_502_page = mock.MagicMock()
    inst.mongo_manager.setup.return_value = {"database": "db", "username": "user"}
    inst.config.persist_app_port = mock.MagicMock()
    inst.config.is_port_available = mock.MagicMock(return_value=True)
    inst._setup_systemd = mock.MagicMock(return_value=True)
    inst._write_resource_manifest = mock.MagicMock()
    inst._post_install = mock.MagicMock()
    inst.health.run_post_install_self_tests.return_value = []
    return app


def test_install_product_success_domain_skipped(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    assert inst._install_product("plexstaff", 3001) == 0
    inst.telemetry.finish_session.assert_called_with("success")
    inst._post_install.assert_called_once()


def test_install_product_success_with_domain_and_dashboard(tmp_path):
    inst = _installer(tmp_path)
    inst.assume_yes = True
    _wired_for_install(inst, tmp_path)
    inst._setup_web = mock.MagicMock(return_value=("app.example.com", 3100, "a@b.com"))
    inst._install_dashboard = mock.MagicMock()
    assert inst._install_product("plextickets", 3000, has_dashboard=True) == 0
    inst._install_dashboard.assert_called_once()
    inst._setup_web.assert_called_once()


def test_install_product_no_archive_returns_1(tmp_path):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=None)
    assert inst._install_product("plexstaff", 3001) == 1
    assert inst.telemetry.finish_session.call_args.args[0] == "uncompleted"


def test_install_product_extraction_failure_aborts(tmp_path):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "a.zip")
    inst.extractor.extract.side_effect = RuntimeError("boom")
    assert inst._install_product("plexstaff", 3001) == 1
    inst.printer.warning.assert_called()


def test_install_product_npm_failure_prompts_log_upload(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    inst._install_npm_dependencies = mock.MagicMock(return_value=False)
    inst._confirm = mock.MagicMock(return_value=True)
    inst.telemetry.share_log.return_value = "https://paste/xyz"
    assert inst._install_product("plexstaff", 3001) == 1
    inst.telemetry.share_log.assert_called_once()


def test_install_product_keyboard_interrupt(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    inst._install_npm_dependencies = mock.MagicMock(side_effect=KeyboardInterrupt)
    assert inst._install_product("plexstaff", 3001) == 1
    assert inst.telemetry.finish_session.call_args.args[0] == "uncompleted"


def test_install_product_mongo_required_but_unavailable(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    inst.mongo_manager = None
    inst.config.get_product = mock.MagicMock(return_value=mock.MagicMock(requires_mongodb=True))
    inst._confirm = mock.MagicMock(return_value=False)
    assert inst._install_product("plexstaff", 3001) == 1
    inst.printer.error.assert_called()


def test_install_product_isolation_prepare_failure_warns(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    inst.isolate_services = True
    _wired_for_install(inst, tmp_path)
    inst.systemd.prepare_service_identity.side_effect = RuntimeError("useradd failed")
    assert inst._install_product("plexstaff", 3001) == 0
    inst.printer.warning.assert_any_call(
        "Could not prepare isolated service identity (useradd failed); using root mode"
    )


def test_install_product_isolation_service_fallback_releases_identity(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    inst.isolate_services = True
    _wired_for_install(inst, tmp_path)
    inst.systemd.prepare_service_identity.return_value = ("plex-x", True)
    inst._setup_systemd = mock.MagicMock(return_value=False)
    assert inst._install_product("plexstaff", 3001) == 0
    inst.systemd.release_service_identity.assert_called_once()


def test_install_product_health_unavailable_returns_2(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    inst.health = None
    assert inst._install_product("plexstaff", 3001) == 2
    assert inst.telemetry.finish_session.call_args.args[0] == "uncompleted"


def test_install_product_self_test_warnings_still_succeed(tmp_path):
    inst = _installer(tmp_path)
    inst.non_interactive = True
    _wired_for_install(inst, tmp_path)
    inst.health.run_post_install_self_tests.return_value = [SelfTestResult("optional check", "warn", "meh")]
    assert inst._install_product("plexstaff", 3001) == 0


# ---------- main() ----------


def test_main_repair_dependencies(monkeypatch):
    fake = mock.MagicMock()
    monkeypatch.setattr("installer.PlexInstaller", mock.MagicMock(return_value=fake))
    monkeypatch.setattr("installer.setup_logging", lambda: None)
    assert installer_module.main(["--repair-dependencies", "--no-update-check"]) == 0
    fake.system.install_dependencies.assert_called_once()
    fake.run.assert_not_called()


def test_main_runs_installer(monkeypatch):
    fake = mock.MagicMock()
    fake.run.return_value = 3
    ctor = mock.MagicMock(return_value=fake)
    monkeypatch.setattr("installer.PlexInstaller", ctor)
    monkeypatch.setattr("installer.setup_logging", lambda: None)
    assert installer_module.main(["--yes", "--isolate-services"]) == 3
    assert ctor.call_args.kwargs["assume_yes"] is True
    assert ctor.call_args.kwargs["isolate_services"] is True
