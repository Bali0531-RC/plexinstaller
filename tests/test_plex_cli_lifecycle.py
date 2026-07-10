"""Focused CLI parsing, redaction, editor, and rollback tests."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import plex_cli


def test_cli_global_flags_parse_and_skip_update():
    with mock.patch("plex_cli._maybe_auto_update") as update:
        with mock.patch("plex_cli.list_apps", return_value=0) as list_apps:
            assert plex_cli.main(["--no-update-check", "--json", "list"]) == 0
    update.assert_not_called()
    list_apps.assert_called_once_with(json_output=True)


def test_cli_missing_argument_has_stable_usage_code():
    with pytest.raises(SystemExit) as exc:
        plex_cli.main(["--no-update-check", "start"])
    assert exc.value.code == plex_cli.EXIT_USAGE


def test_cli_resolves_drako_name_to_legacy_plex_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    legacy = tmp_path / "plexstore"
    legacy.mkdir()
    (legacy / "package.json").write_text("{}")
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)

    assert plex_cli.resolve_app_instance("drakostore") == "plexstore"


def test_cli_resolves_legacy_plex_name_to_drako_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    current = tmp_path / "drakostore-prod"
    current.mkdir()
    (current / "package.json").write_text("{}")
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)

    assert plex_cli.resolve_app_instance("plexstore-prod") == "drakostore-prod"


def test_editor_parses_flags_and_checks_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "config.yml"
    config.write_text("Port: 3000\n")
    monkeypatch.setenv("EDITOR", "code --wait")
    with mock.patch("plex_cli.shutil_which", return_value="/usr/bin/code"):
        with mock.patch(
            "plex_cli.subprocess.run",
            return_value=subprocess.CompletedProcess([], 7),
        ) as run:
            assert plex_cli._run_editor(config) == plex_cli.EXIT_ERROR
    assert run.call_args.args[0] == ["code", "--wait", str(config)]


def test_json_and_log_redaction_masks_secrets():
    source = json.dumps(
        {
            "token": "abc123",
            "nested": {"password": "hunter2"},
            "mongoURI": "mongodb://user:pass@example/db",
        }
    )
    redacted = plex_cli.redact_config_contents(source, ".json")
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert "user:pass" not in redacted
    assert "<REDACTED>" in redacted


def test_debug_upload_requires_confirmation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = tmp_path / "plexstore"
    app.mkdir()
    (app / "package.json").write_text("{}")
    (app / "config.json").write_text('{"token":"secret-value","port":3003}')
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    fake_requests = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "requests", fake_requests)

    with mock.patch("plex_cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout="ok")):
        assert plex_cli.debug_app("plexstore", non_interactive=True) == 0

    fake_requests.post.assert_not_called()


def test_setupdomain_rollback_removes_nginx_and_firewall(tmp_path: Path):
    available = tmp_path / "available"
    enabled = tmp_path / "enabled"
    available.mkdir()
    enabled.mkdir()
    config_file = available / "app.example.com.conf"
    link = enabled / "app.example.com.conf"
    config_file.write_text("bad")
    link.symlink_to(config_file)
    nginx = SimpleNamespace(config=SimpleNamespace(nginx_available=available, nginx_enabled=enabled))

    with mock.patch("plex_cli.subprocess.run") as run:
        plex_cli._rollback_setupdomain("app.example.com", nginx=nginx, ssl_manager=mock.MagicMock())

    assert not config_file.exists()
    assert not link.exists()
    assert any(call.args[0][:2] == ["certbot", "delete"] for call in run.call_args_list)


def test_domain_resources_are_recorded_atomically(tmp_path: Path):
    app = tmp_path / "plexstore"
    app.mkdir()

    plex_cli._record_domain_resources(app, "plexstore", "store.example.com", 3003)

    data = json.loads((app / ".plexinstaller-resources.json").read_text())
    assert data["domain"] == "store.example.com"
    assert data["certificate"] is True
    assert data["firewall_port"] is None


def test_setupdomain_persists_selected_json_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    app = tmp_path / "plexstore"
    app.mkdir()
    (app / "package.json").write_text("{}")
    config_path = app / "config.json"
    config_path.write_text('{"port": 3003}')
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(plex_cli.os, "geteuid", lambda: 0)
    answers = iter(["4123", "store.example.com", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    with (
        mock.patch("utils.DNSChecker.check", return_value=True),
        mock.patch("utils.NginxManager.setup"),
        mock.patch("utils.SSLManager.setup"),
        mock.patch("utils.FirewallManager.close_port"),
        mock.patch("plex_cli._record_domain_resources"),
    ):
        assert plex_cli.tool_setupdomain("plexstore") == 0

    assert json.loads(config_path.read_text())["port"] == 4123


@pytest.mark.parametrize("name", ["addon.zip", "addon.tar", "addon.tar.gz", "addon.tgz", "addon.txz"])
def test_addon_cli_accepts_hardened_archive_formats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str):
    app = tmp_path / "plextickets"
    app.mkdir()
    (app / "package.json").write_text("{}")
    archive = tmp_path / name
    archive.touch()
    manager = mock.MagicMock()
    manager.addon_exists.return_value = False
    manager.install_addon.return_value = (True, "ok", "addon")
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    monkeypatch.setattr(plex_cli, "_get_addon_manager", lambda: manager)

    assert plex_cli.addon_install("plextickets", str(archive)) == 0
