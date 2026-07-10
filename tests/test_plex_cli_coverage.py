"""Broad coverage tests for plex_cli: dispatch, subprocess flows, addons, tools."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import plex_cli


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


def completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


# ---------- helpers / redaction ----------


def test_confirm_assume_yes():
    assert plex_cli._confirm("go?", assume_yes=True) is True


def test_confirm_non_interactive_is_false():
    assert plex_cli._confirm("go?", non_interactive=True) is False


def test_confirm_no_tty_is_false(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: False)
    assert plex_cli._confirm("go?") is False


def test_confirm_prompts_when_tty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _p="": "y")
    assert plex_cli._confirm("go?") is True
    monkeypatch.setattr("builtins.input", lambda _p="": "no")
    assert plex_cli._confirm("go?") is False


def test_editor_command_invalid_shlex_falls_back(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDITOR", 'bad "quote')
    with mock.patch("plex_cli.shutil_which", side_effect=lambda c: "/usr/bin/vi" if c == "vi" else None):
        assert plex_cli._editor_command() == ["vi"]


def test_editor_command_no_fallbacks_returns_vi(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDITOR", "")
    with mock.patch("plex_cli.shutil_which", return_value=None):
        assert plex_cli._editor_command() == ["vi"]


def test_editor_command_uses_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EDITOR", "nano")
    with mock.patch("plex_cli.shutil_which", return_value="/usr/bin/nano"):
        assert plex_cli._editor_command() == ["nano"]


def test_shutil_which_returns_string_or_none():
    result = plex_cli.shutil_which("definitely-not-a-real-binary-xyz")
    assert result is None


def test_run_editor_oserror(tmp_path: Path):
    with mock.patch("plex_cli.subprocess.run", side_effect=OSError("boom")):
        assert plex_cli._run_editor(tmp_path / "c.yml") == plex_cli.EXIT_ERROR


def test_run_editor_success(tmp_path: Path):
    with mock.patch("plex_cli.subprocess.run", return_value=completed(0)):
        assert plex_cli._run_editor(tmp_path / "c.yml") == plex_cli.EXIT_OK


def test_redact_debug_text_masks_bearer_and_kv():
    text = "Authorization: Bearer abc.def\npassword = supersecret\n"
    redacted = plex_cli.redact_debug_text(text)
    assert "abc.def" not in redacted
    assert "supersecret" not in redacted


def test_redact_config_contents_invalid_json_falls_back():
    out = plex_cli.redact_config_contents("token: abc123\n{ broken json", ".json")
    assert "abc123" not in out


def test_redact_config_contents_invalid_json_masks_midline_assignments():
    source = "not json { token: abc123\nrequest accessToken=hunter2, status=failed\ntoken is xyz789"
    out = plex_cli.redact_config_contents(source, ".json")
    assert "abc123" not in out
    assert "hunter2" not in out
    assert "xyz789" not in out
    assert plex_cli.debug_bundle_is_safe(out) is True


def test_redact_debug_text_masks_generic_uri_credentials_and_key_variants():
    source = "connect https://alice:p%40ss@example.com/path\nclientSecret = swordfish\n"
    out = plex_cli.redact_debug_text(source)
    assert "alice:p%40ss" not in out
    assert "swordfish" not in out
    assert "https://<REDACTED>:<REDACTED>@example.com/path" in out
    assert plex_cli.debug_bundle_is_safe(out) is True


def test_redact_json_value_handles_lists():
    result = plex_cli._redact_json_value({"items": [{"token": "x", "refreshToken": "y"}, "mongodb://a:b@h/db"]})
    assert result["items"][0]["token"] == "<REDACTED>"
    assert result["items"][0]["refreshToken"] == "<REDACTED>"
    assert "a:b" not in result["items"][1]


def test_debug_bundle_is_safe_rejects_uri_and_leaks():
    assert plex_cli.debug_bundle_is_safe("mongodb://u:p@host/db") is False
    assert plex_cli.debug_bundle_is_safe("https://u:p@host/path") is False
    assert plex_cli.debug_bundle_is_safe("https://<REDACTED>:<REDACTED>@host/path") is True
    assert plex_cli.debug_bundle_is_safe("password: leaked") is False
    assert plex_cli.debug_bundle_is_safe("prefix { token: leaked") is False
    assert plex_cli.debug_bundle_is_safe("token is leaked") is False
    assert plex_cli.debug_bundle_is_safe('password: "<REDACTED>"') is True
    assert plex_cli.debug_bundle_is_safe('prefix { token: "<REDACTED>"') is True
    assert plex_cli.debug_bundle_is_safe("tokenizer: parser-name") is True
    assert plex_cli.debug_bundle_is_safe("all clear\n") is True


def test_print_helpers(capsys):
    plex_cli.print_error("e")
    plex_cli.print_success("s")
    plex_cli.print_info("i")
    plex_cli.print_warning("w")
    err = capsys.readouterr().err
    for token in ("e", "s", "i", "w"):
        assert token in err


def test_show_help(capsys):
    plex_cli.show_help()
    out = capsys.readouterr().out
    assert "plex list" in out
    assert "addon install" in out


# ---------- version / update ----------


def test_is_newer_version_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "is_newer_version", None)
    assert plex_cli._is_newer_version("1.2.1", "1.2") is True
    assert plex_cli._is_newer_version("1.0", "1.0.0") is False
    assert plex_cli._is_newer_version("bad", "1.0") is False


def test_is_newer_version_shared(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "is_newer_version", lambda remote, local: True)
    assert plex_cli._is_newer_version("x", "y") is True


def test_read_local_installer_version_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", tmp_path)
    assert plex_cli._read_local_installer_version() == "0.0.0"


def test_read_local_installer_version_parses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", tmp_path)
    (tmp_path / "installer.py").write_text('INSTALLER_VERSION = "9.9.9"\n')
    assert plex_cli._read_local_installer_version() == "9.9.9"


def test_read_local_installer_version_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "INSTALLER_DIR", tmp_path)
    (tmp_path / "installer.py").write_text("nothing here\n")
    assert plex_cli._read_local_installer_version() == "0.0.0"


def test_ensure_cli_entrypoints_uses_shared(monkeypatch: pytest.MonkeyPatch):
    shared = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "ensure_cli_entrypoints", shared)
    plex_cli._ensure_cli_entrypoints()
    shared.assert_called_once()


def test_ensure_cli_entrypoints_fallback_not_root(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "ensure_cli_entrypoints", None)
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 1000)
    assert plex_cli._ensure_cli_entrypoints() is None


def test_verify_gpg_signature_uses_shared(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "verify_gpg_signature", lambda *a, **k: True)
    assert plex_cli._verify_gpg_signature(b"x") is True


def test_verify_gpg_signature_fallback_fails(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(plex_cli, "verify_gpg_signature", None)
    assert plex_cli._verify_gpg_signature(b"x") is False


def test_perform_update_uses_shared(monkeypatch: pytest.MonkeyPatch):
    shared = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "perform_update", shared)
    plex_cli._perform_update({"version": "1.0"}, b"raw")
    shared.assert_called_once()


def test_perform_update_fallback_warns(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(plex_cli, "perform_update", None)
    plex_cli._perform_update({})
    assert "cannot perform update" in capsys.readouterr().err


def test_maybe_auto_update_skips_without_tty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: False)
    with mock.patch("plex_cli.urllib.request.urlopen") as urlopen:
        plex_cli._maybe_auto_update()
    urlopen.assert_not_called()


def test_maybe_auto_update_prompts_and_updates(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    payload = json.dumps({"version": "9.9.9", "changelog": ["new stuff"]}).encode()
    response = mock.MagicMock()
    response.read.return_value = payload
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    monkeypatch.setattr("builtins.input", lambda _p="": "y")
    with (
        mock.patch("plex_cli.urllib.request.urlopen", return_value=response),
        mock.patch("plex_cli._verify_gpg_signature", return_value=True),
        mock.patch("plex_cli._read_local_installer_version", return_value="0.0.1"),
        mock.patch("plex_cli._perform_update") as update,
        mock.patch("plex_cli._ensure_cli_entrypoints"),
    ):
        plex_cli._maybe_auto_update()
    update.assert_called_once()


def test_maybe_auto_update_declined(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    payload = json.dumps({"version": "9.9.9"}).encode()
    response = mock.MagicMock()
    response.read.return_value = payload
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    monkeypatch.setattr("builtins.input", lambda _p="": "n")
    with (
        mock.patch("plex_cli.urllib.request.urlopen", return_value=response),
        mock.patch("plex_cli._verify_gpg_signature", return_value=True),
        mock.patch("plex_cli._read_local_installer_version", return_value="0.0.1"),
        mock.patch("plex_cli._perform_update") as update,
        mock.patch("plex_cli._ensure_cli_entrypoints"),
    ):
        plex_cli._maybe_auto_update()
    update.assert_not_called()


def test_maybe_auto_update_bad_signature(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    response = mock.MagicMock()
    response.read.return_value = b'{"version": "9.9.9"}'
    response.__enter__ = lambda s: s
    response.__exit__ = lambda s, *a: False
    with (
        mock.patch("plex_cli.urllib.request.urlopen", return_value=response),
        mock.patch("plex_cli._verify_gpg_signature", return_value=False),
        mock.patch("plex_cli._perform_update") as update,
        mock.patch("plex_cli._ensure_cli_entrypoints"),
    ):
        plex_cli._maybe_auto_update()
    update.assert_not_called()


def test_maybe_auto_update_network_error_is_silent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    with (
        mock.patch("plex_cli.urllib.request.urlopen", side_effect=OSError("net down")),
        mock.patch("plex_cli._ensure_cli_entrypoints") as entry,
    ):
        plex_cli._maybe_auto_update()
    entry.assert_called_once()


def test_maybe_auto_update_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli.sys.stdin, "isatty", lambda: True)
    with (
        mock.patch("plex_cli.urllib.request.urlopen", side_effect=KeyboardInterrupt),
        mock.patch("plex_cli._ensure_cli_entrypoints") as entry,
    ):
        plex_cli._maybe_auto_update()
    entry.assert_called_once()


# ---------- discovery / resolution ----------


def test_get_installed_apps_missing_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path / "nope")
    assert plex_cli.get_installed_apps() == []


def test_get_installed_apps_skips_backups(install_dir: Path):
    make_app(install_dir, "plextickets")
    make_app(install_dir, "backups")
    (install_dir / "not-an-app").mkdir()
    assert plex_cli.get_installed_apps() == ["plextickets"]


def test_resolve_app_instance_empty_name(install_dir: Path):
    assert plex_cli.resolve_app_instance("") is None
    make_app(install_dir, "plextickets")
    assert plex_cli.resolve_app_instance("nonexistent") is None


def test_resolve_app_instance_no_installs(install_dir: Path):
    assert plex_cli.resolve_app_instance("plextickets") is None


def test_resolve_app_instance_multiple_prefix(install_dir: Path, capsys):
    make_app(install_dir, "plextickets-a")
    make_app(install_dir, "plextickets-b")
    assert plex_cli.resolve_app_instance("plextickets") is None
    assert "Multiple instances" in capsys.readouterr().err


def test_resolve_app_instance_single_prefix(install_dir: Path):
    make_app(install_dir, "plextickets-prod")
    assert plex_cli.resolve_app_instance("plextickets") == "plextickets-prod"


def test_resolve_app_instance_ambiguous_brands(install_dir: Path, capsys):
    make_app(install_dir, "plexstore")
    make_app(install_dir, "drakostore")
    assert plex_cli.resolve_app_instance("plexstore") == "plexstore"
    assert plex_cli.resolve_app_instance("drakostore") == "drakostore"


def test_is_valid_app_and_service_name(install_dir: Path):
    make_app(install_dir, "plextickets")
    assert plex_cli.is_valid_app("plextickets") is True
    assert plex_cli.is_valid_app("missing") is False
    assert plex_cli.get_service_name("plextickets") == "plex-plextickets"
    assert plex_cli.get_service_name("unknown") == "plex-unknown"


def test_get_service_status_variants():
    def fake_run(cmd, **kwargs):
        if cmd[1] == "is-active":
            return completed(stdout="active\n")
        return completed(stdout="enabled\n")

    with mock.patch("plex_cli.subprocess.run", side_effect=fake_run):
        status = plex_cli.get_service_status("plex-x")
    assert status["status"] == "Running" and status["active"] and status["enabled"]

    def fake_stopped(cmd, **kwargs):
        if cmd[1] == "is-active":
            return completed(stdout="inactive\n")
        return completed(stdout="enabled\n")

    with mock.patch("plex_cli.subprocess.run", side_effect=fake_stopped):
        assert plex_cli.get_service_status("plex-x")["status"] == "Stopped"

    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="disabled\n")):
        assert plex_cli.get_service_status("plex-x")["status"] == "Disabled"

    with mock.patch("plex_cli.subprocess.run", side_effect=OSError):
        assert plex_cli.get_service_status("plex-x")["status"] == "Unknown"


# ---------- list ----------


def test_list_apps_none_found(install_dir: Path):
    assert plex_cli.list_apps() == 1


def test_list_apps_text_output(install_dir: Path, capsys):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    status = {"status": "Running", "color": "", "active": True, "enabled": True}
    with mock.patch("plex_cli.get_service_status", return_value=status):
        assert plex_cli.list_apps() == 0
    out = capsys.readouterr().out
    assert "plextickets" in out
    assert "Enabled on boot" in out
    assert "config.yml" in out


def test_list_apps_text_output_disabled(install_dir: Path, capsys):
    make_app(install_dir, "plexstaff")
    status = {"status": "Disabled", "color": "", "active": False, "enabled": False}
    with mock.patch("plex_cli.get_service_status", return_value=status):
        assert plex_cli.list_apps() == 0
    assert "Not enabled on boot" in capsys.readouterr().out


def test_list_apps_json_output(install_dir: Path, capsys):
    make_app(install_dir, "plextickets")
    status = {"status": "Stopped", "color": "", "active": False, "enabled": True}
    with mock.patch("plex_cli.get_service_status", return_value=status):
        assert plex_cli.list_apps(json_output=True) == plex_cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["name"] == "plextickets"
    assert payload[0]["status"] == "Stopped"


# ---------- start/stop/restart/status/logs/enable/disable ----------


def test_start_app_unknown(install_dir: Path):
    assert plex_cli.start_app("missing") == 1


def test_start_app_success(install_dir: Path):
    make_app(install_dir, "plextickets")
    status = {"status": "Running", "color": "", "active": True, "enabled": True}
    with (
        mock.patch("plex_cli.subprocess.run", return_value=completed(0)),
        mock.patch("plex_cli.get_service_status", return_value=status),
        mock.patch("time.sleep"),
    ):
        assert plex_cli.start_app("plextickets") == 0


def test_start_app_fails_after_start(install_dir: Path):
    make_app(install_dir, "plextickets")
    status = {"status": "Stopped", "color": "", "active": False, "enabled": True}
    with (
        mock.patch("plex_cli.subprocess.run", return_value=completed(0)),
        mock.patch("plex_cli.get_service_status", return_value=status),
        mock.patch("time.sleep"),
    ):
        assert plex_cli.start_app("plextickets") == 1


def test_start_app_systemctl_error(install_dir: Path):
    make_app(install_dir, "plextickets")
    with mock.patch("plex_cli.subprocess.run", side_effect=subprocess.CalledProcessError(1, "systemctl")):
        assert plex_cli.start_app("plextickets") == 1


def test_stop_app(install_dir: Path):
    make_app(install_dir, "plextickets")
    with mock.patch("plex_cli.subprocess.run", return_value=completed(0)):
        assert plex_cli.stop_app("plextickets") == 0
    with mock.patch("plex_cli.subprocess.run", side_effect=subprocess.CalledProcessError(1, "x")):
        assert plex_cli.stop_app("plextickets") == 1
    assert plex_cli.stop_app("missing") == 1


def test_restart_app(install_dir: Path):
    make_app(install_dir, "plextickets")
    ok = {"status": "Running", "color": "", "active": True, "enabled": True}
    bad = {"status": "Stopped", "color": "", "active": False, "enabled": True}
    with (
        mock.patch("plex_cli.subprocess.run", return_value=completed(0)),
        mock.patch("plex_cli.get_service_status", return_value=ok),
        mock.patch("time.sleep"),
    ):
        assert plex_cli.restart_app("plextickets") == 0
    with (
        mock.patch("plex_cli.subprocess.run", return_value=completed(0)),
        mock.patch("plex_cli.get_service_status", return_value=bad),
        mock.patch("time.sleep"),
    ):
        assert plex_cli.restart_app("plextickets") == 1
    with mock.patch("plex_cli.subprocess.run", side_effect=subprocess.CalledProcessError(1, "x")):
        assert plex_cli.restart_app("plextickets") == 1
    assert plex_cli.restart_app("missing") == 1


def test_show_status(install_dir: Path):
    make_app(install_dir, "plextickets")
    with mock.patch("plex_cli.subprocess.run", return_value=completed(0)):
        assert plex_cli.show_status("plextickets") == 0
    assert plex_cli.show_status("missing") == 1


def test_view_logs(install_dir: Path):
    make_app(install_dir, "plextickets")
    with mock.patch("plex_cli.subprocess.run", return_value=completed(0)):
        assert plex_cli.view_logs("plextickets") == 0
    with mock.patch("plex_cli.subprocess.run", side_effect=KeyboardInterrupt):
        assert plex_cli.view_logs("plextickets") == 0
    assert plex_cli.view_logs("missing") == 1


def test_enable_disable_app(install_dir: Path):
    make_app(install_dir, "plextickets")
    with mock.patch("plex_cli.subprocess.run", return_value=completed(0)):
        assert plex_cli.enable_app("plextickets") == 0
        assert plex_cli.disable_app("plextickets") == 0
    with mock.patch("plex_cli.subprocess.run", side_effect=subprocess.CalledProcessError(1, "x")):
        assert plex_cli.enable_app("plextickets") == 1
        assert plex_cli.disable_app("plextickets") == 1
    assert plex_cli.enable_app("missing") == 1
    assert plex_cli.disable_app("missing") == 1


# ---------- config editing ----------


def test_edit_config_unknown_app(install_dir: Path):
    assert plex_cli.edit_config("missing") == 1


def test_edit_config_no_config(install_dir: Path):
    make_app(install_dir, "plextickets")
    assert plex_cli.edit_config("plextickets") == 1


def test_edit_config_success(install_dir: Path):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    with mock.patch("plex_cli._run_editor", return_value=plex_cli.EXIT_OK):
        assert plex_cli.edit_config("plextickets") == plex_cli.EXIT_OK
    with mock.patch("plex_cli._run_editor", return_value=plex_cli.EXIT_ERROR):
        assert plex_cli.edit_config("plextickets") == plex_cli.EXIT_ERROR


# ---------- debug ----------


def test_debug_app_unknown(install_dir: Path):
    assert plex_cli.debug_app("missing") == 1


def test_debug_app_upload_success(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config='{"token": "abc", "port": 3000}', config_name="config.json")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"key": "abcd"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="log line\n")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0
    fake_requests.post.assert_called_once()


def test_debug_app_upload_url_from_response(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"url": "https://paste/x"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0


def test_debug_app_upload_no_url(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 1


def test_debug_app_upload_network_error(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.side_effect = OSError("boom")
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 1


def test_debug_app_requests_missing(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    monkeypatch.setattr(plex_cli, "requests", None)
    with mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 1


def test_debug_app_no_config_and_journal_failure(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"url": "https://paste/x"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with mock.patch("plex_cli.subprocess.run", side_effect=OSError("no journalctl")):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0
    body = fake_requests.post.call_args.kwargs["data"].decode()
    assert "No config.yml" in body
    assert "Could not run journalctl" in body


def test_debug_app_blocked_when_unsafe(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with (
        mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")),
        mock.patch("plex_cli.debug_bundle_is_safe", return_value=False),
    ):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == plex_cli.EXIT_ERROR
    fake_requests.post.assert_not_called()


def test_debug_app_unreadable_config(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="Port: 3000\n")
    fake_requests = mock.MagicMock()
    fake_requests.post.return_value.json.return_value = {"url": "https://paste/x"}
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    with (
        mock.patch.object(Path, "read_text", side_effect=OSError("denied")),
        mock.patch("plex_cli.subprocess.run", return_value=completed(stdout="ok")),
    ):
        assert plex_cli.debug_app("plextickets", assume_yes=True) == 0
    assert "Could not read config file" in fake_requests.post.call_args.kwargs["data"].decode()


# ---------- addons ----------


def test_get_addon_manager_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "AddonManager", None)
    assert plex_cli._get_addon_manager() is None


def test_supports_addons():
    assert plex_cli._supports_addons("plextickets-prod") is True
    assert plex_cli._supports_addons("PlexStaff") is True
    assert plex_cli._supports_addons("plexstore") is False


def test_addon_list_paths(install_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    assert plex_cli.addon_list("missing") == 1
    make_app(install_dir, "plexstore")
    assert plex_cli.addon_list("plexstore") == 1

    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: None)
    assert plex_cli.addon_list("plextickets") == 1

    manager = mock.MagicMock()
    manager.list_addons.return_value = []
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: manager)
    assert plex_cli.addon_list("plextickets") == 0

    manager.list_addons.return_value = [
        {"name": "MyAddon", "has_config": True, "config_path": Path("/x/config.yml")},
        {"name": "Other", "has_config": False, "config_path": Path("/x/none")},
    ]
    assert plex_cli.addon_list("plextickets") == 0
    out = capsys.readouterr().out
    assert "MyAddon" in out and "No config" in out and "Total: 2" in out


def test_addon_install_error_paths(
    install_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
):
    assert plex_cli.addon_install("missing", "x.zip") == 1
    make_app(install_dir, "plexstore")
    assert plex_cli.addon_install("plexstore", "x.zip") == 1

    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: None)
    assert plex_cli.addon_install("plextickets", "x.zip") == 1

    manager = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: manager)
    assert plex_cli.addon_install("plextickets", str(tmp_path / "nope.zip")) == 1

    bad = tmp_path / "addon.rar"
    bad.touch()
    assert plex_cli.addon_install("plextickets", str(bad)) == 1

    archive = tmp_path / "MyAddon-main.zip"
    archive.touch()
    manager.addon_exists.return_value = True
    capsys.readouterr()
    assert plex_cli.addon_install("plextickets", str(archive)) == 1
    assert "plex addon remove plextickets MyAddon" in capsys.readouterr().err
    manager.addon_exists.assert_called_with("MyAddon", install_dir / "plextickets")

    manager.addon_exists.return_value = False
    manager.install_addon.return_value = (False, "extraction failed", None)
    assert plex_cli.addon_install("plextickets", str(archive)) == 1

    manager.install_addon.return_value = (True, "installed", "MyAddon")
    assert plex_cli.addon_install("plextickets", str(archive)) == 0


def test_addon_remove_paths(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    assert plex_cli.addon_remove("missing", "A") == 1
    make_app(install_dir, "plexstore")
    assert plex_cli.addon_remove("plexstore", "A") == 1

    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: None)
    assert plex_cli.addon_remove("plextickets", "A") == 1

    manager = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: manager)
    manager.addon_exists.return_value = False
    assert plex_cli.addon_remove("plextickets", "A") == 1

    manager.addon_exists.return_value = True
    manager.remove_addon.return_value = (True, "removed")
    assert plex_cli.addon_remove("plextickets", "A") == 0
    manager.remove_addon.return_value = (False, "failed")
    assert plex_cli.addon_remove("plextickets", "A") == 1


def test_addon_config_paths(install_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    assert plex_cli.addon_config("missing", "A") == 1
    make_app(install_dir, "plexstore")
    assert plex_cli.addon_config("plexstore", "A") == 1

    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: None)
    assert plex_cli.addon_config("plextickets", "A") == 1

    manager = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: manager)

    manager.get_addon_config_path.return_value = None
    manager.addon_exists.return_value = False
    assert plex_cli.addon_config("plextickets", "A") == 1
    manager.addon_exists.return_value = True
    assert plex_cli.addon_config("plextickets", "A") == 1

    config_path = tmp_path / "config.yml"
    config_path.write_text("ok: true\n")
    manager.get_addon_config_path.return_value = config_path
    manager.validate_yaml.return_value = (True, None)
    with mock.patch("plex_cli._run_editor", return_value=plex_cli.EXIT_OK):
        assert plex_cli.addon_config("plextickets", "A") == plex_cli.EXIT_OK
    manager.validate_yaml.return_value = (False, "bad yaml")
    with mock.patch("plex_cli._run_editor", return_value=plex_cli.EXIT_OK):
        assert plex_cli.addon_config("plextickets", "A") == plex_cli.EXIT_OK
    with mock.patch("plex_cli._run_editor", return_value=plex_cli.EXIT_ERROR):
        assert plex_cli.addon_config("plextickets", "A") == plex_cli.EXIT_ERROR


def test_handle_addon_command_dispatch(monkeypatch: pytest.MonkeyPatch):
    assert plex_cli.handle_addon_command([]) == 1
    assert plex_cli.handle_addon_command(["list"]) == 1
    monkeypatch.setattr(plex_cli, "addon_list", lambda app: 0)
    assert plex_cli.handle_addon_command(["list", "app"]) == 0
    assert plex_cli.handle_addon_command(["install", "app"]) == 1
    monkeypatch.setattr(plex_cli, "addon_install", lambda app, path: 0)
    assert plex_cli.handle_addon_command(["install", "app", "x.zip"]) == 0
    assert plex_cli.handle_addon_command(["remove", "app"]) == 1
    monkeypatch.setattr(plex_cli, "addon_remove", lambda app, name: 0)
    assert plex_cli.handle_addon_command(["remove", "app", "A"]) == 0
    assert plex_cli.handle_addon_command(["config", "app"]) == 1
    monkeypatch.setattr(plex_cli, "addon_config", lambda app, name: 0)
    assert plex_cli.handle_addon_command(["configure", "app", "A"]) == 0
    assert plex_cli.handle_addon_command(["bogus", "app"]) == 1


# ---------- tool setupdomain ----------


def _tool_mocks():
    return (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup"),
        mock.patch("utils.SSLManager.setup"),
        mock.patch("utils.FirewallManager.close_port"),
        mock.patch("plex_cli._record_domain_resources"),
    )


def test_tool_setupdomain_unknown_app(install_dir: Path):
    assert plex_cli.tool_setupdomain("missing") == 1


def test_tool_setupdomain_requires_root(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 1000)
    assert plex_cli.tool_setupdomain("plextickets") == 1


def test_tool_setupdomain_prompts_for_port_and_validates(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["notaport", "99999", "3005", "bad domain!", "app.example.com", "notanemail", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    m1, m2, m3, m4, m5 = _tool_mocks()
    with m1, m2, m3, m4, m5, mock.patch.object(plex_cli.Config, "persist_app_port", create=True):
        with mock.patch("plex_cli.Config") as config_cls:
            config_cls.PASTE_ENDPOINT = "x"
            assert plex_cli.tool_setupdomain("plextickets") == 0


@pytest.mark.parametrize("confirmation", ["", "y", "yes"])
def test_tool_setupdomain_detects_yaml_port_and_keeps_it(
    install_dir: Path, monkeypatch: pytest.MonkeyPatch, confirmation: str
):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter([confirmation, "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    m1, m2, m3, m4, m5 = _tool_mocks()
    with m1, m2 as nginx_setup, m3, m4, m5, mock.patch("plex_cli.Config") as config_cls:
        config_cls.return_value.persist_app_port = mock.MagicMock()
        assert plex_cli.tool_setupdomain("plextickets") == 0
    assert nginx_setup.call_args.args[1] == 3010


def test_tool_setupdomain_invalid_override_reprompts(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["999999", "notaport", "3020", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    m1, m2, m3, m4, m5 = _tool_mocks()
    with m1, m2 as nginx_setup, m3, m4, m5, mock.patch("plex_cli.Config"):
        assert plex_cli.tool_setupdomain("plextickets") == 0
    assert nginx_setup.call_args.args[1] == 3020


@pytest.mark.parametrize("decline", ["n", "no"])
def test_tool_setupdomain_declining_detected_port_prompts_for_new_port(
    install_dir: Path, monkeypatch: pytest.MonkeyPatch, decline: str
):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter([decline, "bad", "70000", "3021", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    m1, m2, m3, m4, m5 = _tool_mocks()
    with m1, m2 as nginx_setup, m3, m4, m5, mock.patch("plex_cli.Config"):
        assert plex_cli.tool_setupdomain("plextickets") == 0
    assert nginx_setup.call_args.args[1] == 3021


def test_tool_setupdomain_config_module_missing(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(plex_cli, "Config", None)
    monkeypatch.setattr("builtins.input", lambda _p="": "y")
    assert plex_cli.tool_setupdomain("plextickets") == plex_cli.EXIT_ERROR


def test_tool_setupdomain_existing_nginx_conf(install_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    available = tmp_path / "avail"
    enabled = tmp_path / "enab"
    available.mkdir()
    enabled.mkdir()
    (available / "app.example.com.conf").write_text("x")
    nginx = SimpleNamespace(config=SimpleNamespace(nginx_available=available, nginx_enabled=enabled))
    with mock.patch("utils.NginxManager", return_value=nginx):
        assert plex_cli.tool_setupdomain("plextickets") == plex_cli.EXIT_ERROR


def test_tool_setupdomain_dns_failure_abort(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io", "n"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    with mock.patch("utils.DNSChecker.check", return_value=False):
        assert plex_cli.tool_setupdomain("plextickets") == 1


def test_tool_setupdomain_nginx_failure_rolls_back(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    with (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup", side_effect=RuntimeError("nginx broke")),
        mock.patch("plex_cli._rollback_setupdomain") as rollback,
    ):
        assert plex_cli.tool_setupdomain("plextickets") == 1
    rollback.assert_called_once()


def test_tool_setupdomain_ssl_failure_rolls_back(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    with (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup"),
        mock.patch("utils.SSLManager.setup", side_effect=RuntimeError("certbot broke")),
        mock.patch("plex_cli._rollback_setupdomain") as rollback,
    ):
        assert plex_cli.tool_setupdomain("plextickets") == 1
    rollback.assert_called_once()


def test_tool_setupdomain_persist_failure_rolls_back(install_dir: Path, monkeypatch: pytest.MonkeyPatch):
    make_app(install_dir, "plextickets", config="port: 3010\n")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    fake_config = mock.MagicMock()
    fake_config.return_value.persist_app_port.side_effect = RuntimeError("disk full")
    monkeypatch.setattr(plex_cli, "Config", fake_config)
    with (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup"),
        mock.patch("utils.SSLManager.setup"),
        mock.patch("plex_cli._rollback_setupdomain") as rollback,
    ):
        assert plex_cli.tool_setupdomain("plextickets") == plex_cli.EXIT_ERROR
    rollback.assert_called_once()


def test_tool_setupdomain_firewall_warning_is_nonfatal(install_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    make_app(install_dir, "plextickets", config='{"Port": 3010}', config_name="config.json")
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["y", "app.example.com", "a@b.io"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    with (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup"),
        mock.patch("utils.SSLManager.setup"),
        mock.patch("utils.FirewallManager.close_port", side_effect=RuntimeError("ufw missing")),
        mock.patch("plex_cli.Config"),
        mock.patch("plex_cli._record_domain_resources"),
    ):
        assert plex_cli.tool_setupdomain("plextickets") == 0
    assert "firewall" in capsys.readouterr().err.lower()


def test_rollback_setupdomain_without_ssl_manager(tmp_path: Path):
    nginx = SimpleNamespace(config=SimpleNamespace(nginx_available=tmp_path, nginx_enabled=tmp_path))
    with mock.patch("plex_cli.subprocess.run") as run:
        plex_cli._rollback_setupdomain("d.example.com", nginx=nginx)
    assert not any(call.args[0][0] == "certbot" for call in run.call_args_list)


def test_rollback_setupdomain_handles_missing_config():
    with mock.patch("plex_cli.subprocess.run", side_effect=OSError):
        plex_cli._rollback_setupdomain("d.example.com", nginx=SimpleNamespace(), ssl_manager=mock.MagicMock())


def test_record_domain_resources_merges_existing(tmp_path: Path):
    app = tmp_path / "app"
    app.mkdir()
    manifest = app / ".plexinstaller-resources.json"
    manifest.write_text(json.dumps({"service": "custom-svc", "mongodb": {"db": "x"}}))
    plex_cli._record_domain_resources(app, "app", "d.example.com", 3000)
    data = json.loads(manifest.read_text())
    assert data["service"] == "custom-svc"
    assert data["mongodb"] == {"db": "x"}
    assert data["port"] == 3000


def test_record_domain_resources_ignores_corrupt_manifest(tmp_path: Path):
    app = tmp_path / "app"
    app.mkdir()
    (app / ".plexinstaller-resources.json").write_text("not-json")
    plex_cli._record_domain_resources(app, "app", "d.example.com", 3000)
    assert json.loads((app / ".plexinstaller-resources.json").read_text())["domain"] == "d.example.com"


def test_handle_tool_command_dispatch(monkeypatch: pytest.MonkeyPatch):
    assert plex_cli.handle_tool_command([]) == 1
    assert plex_cli.handle_tool_command(["setupdomain"]) == 1
    monkeypatch.setattr(plex_cli, "tool_setupdomain", lambda app: 0)
    assert plex_cli.handle_tool_command(["setupdomain", "app"]) == 0
    assert plex_cli.handle_tool_command(["bogus"]) == 1


# ---------- main dispatch ----------


def test_main_no_command_shows_help(capsys):
    assert plex_cli.main([]) == plex_cli.EXIT_USAGE
    assert "Plex CLI" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("argv", "target"),
    [
        (["start", "app"], "start_app"),
        (["stop", "app"], "stop_app"),
        (["restart", "app"], "restart_app"),
        (["status", "app"], "show_status"),
        (["logs", "app"], "view_logs"),
        (["enable", "app"], "enable_app"),
        (["disable", "app"], "disable_app"),
        (["config", "app"], "edit_config"),
        (["configure", "app"], "edit_config"),
    ],
)
def test_main_dispatches_app_commands(argv, target, monkeypatch: pytest.MonkeyPatch):
    handler = mock.MagicMock(return_value=0)
    monkeypatch.setattr(plex_cli, target, handler)
    assert plex_cli.main(["--no-update-check", *argv]) == 0
    handler.assert_called_once_with("app")


def test_main_ls_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(plex_cli, "list_apps", mock.MagicMock(return_value=0))
    assert plex_cli.main(["--no-update-check", "ls"]) == 0


def test_main_config_non_interactive_rejected():
    assert plex_cli.main(["--no-update-check", "--non-interactive", "config", "app"]) == plex_cli.EXIT_USAGE


def test_main_debug_dispatch(monkeypatch: pytest.MonkeyPatch):
    handler = mock.MagicMock(return_value=0)
    monkeypatch.setattr(plex_cli, "debug_app", handler)
    assert plex_cli.main(["--no-update-check", "--yes", "debug", "app"]) == 0
    handler.assert_called_once_with("app", assume_yes=True, non_interactive=False)


def test_main_addon_dispatch(monkeypatch: pytest.MonkeyPatch):
    handler = mock.MagicMock(return_value=0)
    monkeypatch.setattr(plex_cli, "handle_addon_command", handler)
    assert plex_cli.main(["--no-update-check", "addon", "list", "app"]) == 0
    handler.assert_called_once_with(["list", "app"])


def test_main_tool_dispatch(monkeypatch: pytest.MonkeyPatch):
    handler = mock.MagicMock(return_value=0)
    monkeypatch.setattr(plex_cli, "handle_tool_command", handler)
    assert plex_cli.main(["--no-update-check", "tool", "setupdomain", "app"]) == 0
    handler.assert_called_once_with(["setupdomain", "app"])


def test_main_tool_non_interactive_rejected():
    assert plex_cli.main(["--no-update-check", "--non-interactive", "tool", "setupdomain", "a"]) == plex_cli.EXIT_USAGE


def test_main_help_command(capsys):
    assert plex_cli.main(["--no-update-check", "help"]) == plex_cli.EXIT_OK
    assert "Plex CLI" in capsys.readouterr().out


def test_main_runs_update_check(monkeypatch: pytest.MonkeyPatch):
    update = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "_maybe_auto_update", update)
    monkeypatch.setattr(plex_cli, "list_apps", mock.MagicMock(return_value=0))
    assert plex_cli.main(["list"]) == 0
    update.assert_called_once()


def test_main_unknown_command_exits_usage():
    with pytest.raises(SystemExit) as exc:
        plex_cli.main(["--no-update-check", "bogus"])
    assert exc.value.code == plex_cli.EXIT_USAGE
