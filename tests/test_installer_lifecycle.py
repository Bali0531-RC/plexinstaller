"""Focused installer lifecycle and resource-ownership tests."""

import json
from pathlib import Path
from unittest import mock

import pytest

from config import Config
from health_checker import SelfTestResult
from installer import InstallationContext, PlexInstaller, UserAbortError


def _installer(tmp_path: Path) -> PlexInstaller:
    installer = object.__new__(PlexInstaller)
    installer.config = Config()
    installer.config.install_dir = tmp_path
    installer.printer = mock.MagicMock()
    installer.assume_yes = False
    installer.non_interactive = False
    installer.isolate_services = None
    installer.telemetry_enabled = True
    installer.systemd = mock.MagicMock()
    installer.firewall = mock.MagicMock()
    installer.mongo_manager = mock.MagicMock()
    installer.health = mock.MagicMock()
    installer.backup_mgr = mock.MagicMock()
    return installer


def test_declining_multi_instance_aborts_without_overwrite(tmp_path: Path):
    installer = _installer(tmp_path)
    existing = tmp_path / "plexstore"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("important")
    installer._confirm = mock.MagicMock(return_value=False)

    with pytest.raises(UserAbortError, match="preserved"):
        installer._handle_multi_instance("plexstore")

    assert marker.read_text() == "important"


def test_custom_instance_name_must_not_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    (tmp_path / "plexstore").mkdir()
    (tmp_path / "taken").mkdir()
    installer._confirm = mock.MagicMock(return_value=True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "taken")

    with pytest.raises(UserAbortError, match="already exists"):
        installer._handle_multi_instance("plexstore")


def test_drako_install_detects_legacy_plex_instance(tmp_path: Path):
    installer = _installer(tmp_path)
    legacy = tmp_path / "plexstore"
    legacy.mkdir()
    marker = legacy / "keep.txt"
    marker.write_text("legacy")
    installer._confirm = mock.MagicMock(return_value=False)

    with pytest.raises(UserAbortError, match="preserved"):
        installer._handle_multi_instance("drakostore")

    assert marker.read_text() == "legacy"


def test_new_drako_install_uses_canonical_name(tmp_path: Path):
    installer = _installer(tmp_path)
    assert installer._handle_multi_instance("plexstore") == "drakostore"


def test_drako_archive_search_accepts_legacy_plex_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    archive = tmp_path / "plexstore-release.zip"
    archive.write_bytes(b"archive")
    monkeypatch.setattr("installer.Path.home", lambda: tmp_path)
    monkeypatch.setattr("installer.Path.cwd", lambda: tmp_path)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "1")

    assert installer._find_archive("drakostore") == archive.resolve()


def test_failed_cleanup_preserves_preexisting_install_path(tmp_path: Path):
    installer = _installer(tmp_path)
    existing = tmp_path / "plexstore"
    existing.mkdir()
    marker = existing / "keep.txt"
    marker.write_text("safe")
    context = InstallationContext("plexstore", "plexstore", existing, 3003, install_path_created=False)

    installer._cleanup_failed_install(context)

    assert marker.exists()


def test_failed_cleanup_removes_only_current_run_path(tmp_path: Path):
    installer = _installer(tmp_path)
    created = tmp_path / "plexstore-new"
    created.mkdir()
    context = InstallationContext("plexstore", "plexstore-new", created, 3003, install_path_created=True)

    installer._cleanup_failed_install(context)

    assert not created.exists()


def test_port_persistence_yaml_and_json(tmp_path: Path):
    yaml_dir = tmp_path / "yaml"
    yaml_dir.mkdir()
    yaml_config = yaml_dir / "config.yml"
    yaml_config.write_text("Token: x\nPort: 3000\n")
    json_dir = tmp_path / "json"
    json_dir.mkdir()
    json_config = json_dir / "config.json"
    json_config.write_text('{"port": 3000, "name": "test"}')
    config = Config()

    config.persist_app_port(yaml_dir, 4123)
    config.persist_app_port(json_dir, 4124)

    assert "Port: 4123" in yaml_config.read_text()
    assert json.loads(json_config.read_text())["port"] == 4124


def test_port_conflict_detected_before_config_commit(tmp_path: Path):
    installer = _installer(tmp_path)
    installer.non_interactive = True
    installer.config.is_port_available = mock.MagicMock(return_value=False)

    with pytest.raises(UserAbortError, match="already in use"):
        installer._select_available_port(3003)


def test_optional_managers_can_be_absent(tmp_path: Path):
    installer = _installer(tmp_path)
    installer.health = None
    installer.backup_mgr = None
    assert installer.health is None
    assert installer.backup_mgr is None


def test_main_menu_propagates_install_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    installer._display_banner = mock.MagicMock()
    installer._show_services_status = mock.MagicMock()
    installer._install_product = mock.MagicMock(return_value=2)
    monkeypatch.setattr("installer.os.system", lambda *_args: 0)
    answers = iter(["4", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert installer._show_main_menu() == 2


def test_run_returns_main_menu_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    installer.telemetry_enabled = False
    installer.check_updates = False
    installer.system = mock.MagicMock()
    installer._display_banner = mock.MagicMock()
    installer._missing_dependencies = mock.MagicMock(return_value=[])
    installer._show_main_menu = mock.MagicMock(return_value=2)
    monkeypatch.setattr("installer.os.system", lambda *_args: 0)

    assert installer.run() == 2


def test_required_self_test_failure_is_not_reported_as_install_success(tmp_path: Path):
    installer = _installer(tmp_path)
    installer.telemetry = mock.MagicMock()
    installer.extractor = mock.MagicMock()
    installer.extractor.extract.return_value = tmp_path / "plexstore"
    installer._find_archive = mock.MagicMock(return_value=tmp_path / "plexstore.zip")
    installer._install_npm_dependencies = mock.MagicMock(return_value=True)
    installer._create_502_page = mock.MagicMock()
    installer.mongo_manager.setup.return_value = None
    installer.config.persist_app_port = mock.MagicMock()
    installer.config.is_port_available = mock.MagicMock(return_value=True)
    installer.firewall.open_port = mock.MagicMock()
    installer._setup_systemd = mock.MagicMock(return_value=True)
    installer._write_resource_manifest = mock.MagicMock()
    installer._post_install = mock.MagicMock()
    installer._confirm = mock.MagicMock(return_value=False)
    installer.non_interactive = True
    installer.health.run_post_install_self_tests.return_value = [
        SelfTestResult("Local TCP port reachable", "fail", "refused")
    ]

    assert installer._install_product("plexstore", 3003) == 2
    installer.telemetry.finish_session.assert_called_once()
    assert installer.telemetry.finish_session.call_args.args[0] == "failure"
    installer._post_install.assert_not_called()


def test_isolation_falls_back_to_root_for_legacy_systemd_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    installer._confirm = mock.MagicMock(return_value=True)
    monkeypatch.setenv("PLEX_ISOLATE_SERVICES", "1")

    def legacy_create(name, path):
        return None

    installer.systemd.create_service = mock.MagicMock(side_effect=legacy_create)
    assert installer._setup_systemd("plexstore", tmp_path) is True
    assert installer.systemd.create_service.call_args_list[-1] == mock.call("plexstore", tmp_path)
    assert installer._last_service_isolated is False


def test_isolation_uses_supported_systemd_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    installer = _installer(tmp_path)
    installer._confirm = mock.MagicMock(return_value=True)
    monkeypatch.setenv("PLEX_ISOLATE_SERVICES", "1")

    assert installer._setup_systemd("plexstore", tmp_path) is True
    installer.systemd.create_service.assert_called_once_with("plexstore", tmp_path, isolated=True)
    assert installer._last_service_isolated is True


def test_npm_lifecycle_runs_as_isolated_user(tmp_path: Path):
    installer = _installer(tmp_path)
    (tmp_path / "package.json").write_text("{}")

    with mock.patch("installer.subprocess.run", return_value=mock.MagicMock(returncode=0)) as run:
        assert installer._install_npm_dependencies(tmp_path, run_as_user="plex-example") is True

    assert run.call_args.args[0][:5] == ["runuser", "--user", "plex-example", "--", "npm"]


def test_failed_cleanup_removes_mongo_identity_and_credentials(tmp_path: Path):
    installer = _installer(tmp_path)
    context = InstallationContext(
        "plexstore",
        "plexstore-a",
        tmp_path / "missing",
        3003,
        mongo_identity={"database": "db-a", "username": "user-a"},
    )

    installer._cleanup_failed_install(context)

    installer.mongo_manager.cleanup_identity.assert_called_once_with("db-a", "user-a", drop_database=False)
    installer.mongo_manager.remove_saved_credentials.assert_called_once_with("plexstore-a")


def test_noninteractive_first_run_telemetry_defaults_off(tmp_path: Path):
    installer = _installer(tmp_path)
    installer.non_interactive = True
    pref = tmp_path / "telemetry_pref"

    with mock.patch("builtins.input", side_effect=AssertionError("must not prompt")):
        assert installer._prompt_telemetry_preference(pref) is False
    assert pref.read_text() == "disabled\n"


def test_manifest_uninstall_preserves_mongo_data_by_default(tmp_path: Path):
    installer = _installer(tmp_path)
    app = tmp_path / "plexstore-a"
    app.mkdir()
    context = InstallationContext(
        "plexstore",
        "plexstore-a",
        app,
        4100,
        domain="store.example.com",
        service_created=True,
        nginx_configured=True,
        ssl_configured=True,
        opened_port=4100,
        mongo_identity={"database": "db_a", "username": "user_a"},
    )
    installer._write_resource_manifest(context)
    installer._remove_nginx_config = mock.MagicMock()
    installer._remove_ssl_certificate = mock.MagicMock()
    installer._confirm = mock.MagicMock(side_effect=[True, False])

    assert installer._uninstall_product("plexstore-a") is True
    assert not app.exists()
    installer.mongo_manager.cleanup_identity.assert_called_once_with("db_a", "user_a", drop_database=False)
    installer.mongo_manager.remove_saved_credentials.assert_called_once_with("plexstore-a")
    installer.firewall.close_port.assert_called_once_with(4100)


def test_uninstall_without_cleanup_removes_only_install_path(tmp_path: Path):
    installer = _installer(tmp_path)
    app = tmp_path / "legacy"
    app.mkdir()
    (app / "package.json").write_text("{}")
    installer._confirm = mock.MagicMock(return_value=True)

    assert installer._uninstall_product("legacy") is True
    assert not app.exists()
    installer.systemd.remove_service.assert_called_once_with("plex-legacy")
    installer.mongo_manager.remove_saved_credentials.assert_called_once_with("legacy")
