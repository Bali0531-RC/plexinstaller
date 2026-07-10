"""Coverage tests for installer.py menus, SSL management, and addon flows."""

from pathlib import Path
from unittest import mock

import pytest

from config import Config
from installer import PlexInstaller


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
    return inst


def _answers(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))


@pytest.fixture(autouse=True)
def _no_clear(monkeypatch):
    monkeypatch.setattr("installer.os.system", lambda *_a: 0)


# ---------- main menu ----------


def test_main_menu_dispatches_all_products(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._display_banner = mock.MagicMock()
    inst._show_services_status = mock.MagicMock()
    inst._install_plextickets = mock.MagicMock(return_value=0)
    inst._install_product = mock.MagicMock(return_value=0)
    inst._manage_installations = mock.MagicMock()
    inst._manage_addons_menu = mock.MagicMock()
    inst._ssl_management_menu = mock.MagicMock()
    seq = [
        "1",
        "",
        "2",
        "",
        "3",
        "",
        "4",
        "",
        "5",
        "",
        "6",
        "",
        "7",
        "",
        "8",
        "",
        "9",
        "",
        "10",
        "",
        "11",
        "",
        "12",
        "",
        "13",
        "",
        "bogus",
        "",
        "0",
    ]
    _answers(monkeypatch, seq)
    assert inst._show_main_menu() == 0
    inst._install_plextickets.assert_called_once()
    assert inst._install_product.call_count == 7
    inst._manage_installations.assert_called_once()
    inst.backup_mgr.menu.assert_called_once()
    inst._manage_addons_menu.assert_called_once()
    inst._ssl_management_menu.assert_called_once()
    inst.health.system_health_check.assert_called_once()


def test_main_menu_missing_optional_managers(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._display_banner = mock.MagicMock()
    inst._show_services_status = mock.MagicMock()
    inst.backup_mgr = None
    inst.health = None
    _answers(monkeypatch, ["10", "", "13", "", "0"])
    assert inst._show_main_menu() == 0
    assert inst.printer.warning.call_count >= 2


# ---------- services status ----------


def test_show_services_status_table(monkeypatch, tmp_path, capsys):
    inst = _installer(tmp_path)
    for name in ("plexstaff", "drakostore", "other"):
        d = tmp_path / name
        d.mkdir()
        (d / "config.yml").write_text("Port: 3123\n")
    inst.systemd.get_status.side_effect = ["active", "inactive", "failed"]
    inst._show_services_status()
    out = capsys.readouterr().out
    assert "3123" in out
    assert "Product" in out


def test_show_services_status_matches_only_yaml_port_key(tmp_path, capsys):
    inst = _installer(tmp_path)
    misleading = tmp_path / "misleading"
    misleading.mkdir()
    (misleading / "config.yml").write_text("# port: 1111\ndbPort: 2222\ntransport: 3333\n")
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "config.yaml").write_text("PoRt: 4444 # public port\n")
    inst.systemd.get_status.return_value = "active"

    inst._show_services_status()

    out = capsys.readouterr().out
    assert "4444" in out
    assert "N/A" in out
    assert "1111" not in out
    assert "2222" not in out
    assert "3333" not in out


def test_show_services_status_empty_dirs(tmp_path):
    inst = _installer(tmp_path)
    inst.config.install_dir = tmp_path / "missing"
    inst._show_services_status()
    inst.config.install_dir = tmp_path
    inst._show_services_status()  # exists but no products


# ---------- plextickets menu ----------


def test_install_plextickets_choices(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._install_product = mock.MagicMock(return_value=0)
    _answers(monkeypatch, ["1"])
    assert inst._install_plextickets() == 0
    assert inst._install_product.call_args.kwargs.get("has_dashboard") is True
    _answers(monkeypatch, ["2"])
    assert inst._install_plextickets() == 0
    assert inst._install_product.call_args.kwargs.get("needs_web") is False
    _answers(monkeypatch, ["0"])
    assert inst._install_plextickets() == 0
    _answers(monkeypatch, ["x"])
    assert inst._install_plextickets() == 1


# ---------- manage installations ----------


def test_manage_installations_no_dir(tmp_path):
    inst = _installer(tmp_path)
    inst.config.install_dir = tmp_path / "missing"
    inst._manage_installations()
    inst.printer.warning.assert_called()


def test_manage_installations_no_products(tmp_path):
    inst = _installer(tmp_path)
    inst._manage_installations()
    inst.printer.warning.assert_called()


def test_manage_installations_selects_product(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "plexstaff").mkdir()
    inst.systemd.get_status.return_value = "active"
    inst._manage_product = mock.MagicMock()
    _answers(monkeypatch, ["1"])
    inst._manage_installations()
    inst._manage_product.assert_called_once_with("plexstaff")


def test_manage_installations_back_and_invalid(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "plexstaff").mkdir()
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["0"])
    inst._manage_installations()
    _answers(monkeypatch, ["abc"])
    inst._manage_installations()
    inst.printer.error.assert_called()


def test_manage_product_actions(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.systemd.get_status.return_value = "active"
    inst._edit_config = mock.MagicMock()
    inst._uninstall_product = mock.MagicMock(return_value=True)
    _answers(monkeypatch, ["1", "2", "3", "4", "5", "6"])
    inst._manage_product("plexstaff")
    inst.systemd.start.assert_called_once()
    inst.systemd.stop.assert_called_once()
    inst.systemd.restart.assert_called_once()
    inst.systemd.view_logs.assert_called_once()
    inst._edit_config.assert_called_once()
    inst._uninstall_product.assert_called_once()


def test_manage_product_back(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.systemd.get_status.return_value = "inactive"
    _answers(monkeypatch, ["0"])
    inst._manage_product("plexstaff")


def test_manage_product_stays_open_when_uninstall_returns_false(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.systemd.get_status.return_value = "active"
    inst._uninstall_product = mock.MagicMock(return_value=False)
    _answers(monkeypatch, ["6", "0"])

    inst._manage_product("plexstaff")

    inst._uninstall_product.assert_called_once_with("plexstaff")
    assert inst.systemd.get_status.call_count == 2


def test_edit_config_paths(tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "plexstaff"
    app.mkdir()
    inst._run_editor = mock.MagicMock(return_value=True)
    inst._edit_config("plexstaff")
    inst.printer.warning.assert_called()
    (app / "config.yml").write_text("Port: 1\n")
    inst._edit_config("plexstaff")
    inst._run_editor.assert_called_once()


# ---------- SSL menu ----------


def test_ssl_management_menu_all_options(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._show_ssl_status = mock.MagicMock()
    inst._view_ssl_logs = mock.MagicMock()
    inst._force_ssl_renewal = mock.MagicMock()
    inst._test_ssl_renewal = mock.MagicMock()
    _answers(monkeypatch, ["1", "", "2", "", "3", "", "4", "", "5", "", "x", "", "0"])
    inst._ssl_management_menu()
    inst._show_ssl_status.assert_called_once()
    inst._view_ssl_logs.assert_called_once()
    inst.ssl.setup_auto_renewal.assert_called_once()
    inst._force_ssl_renewal.assert_called_once()
    inst._test_ssl_renewal.assert_called_once()


def test_show_ssl_status(tmp_path):
    inst = _installer(tmp_path)
    with mock.patch("installer.subprocess.run") as run:
        inst._show_ssl_status()
    run.assert_called_once_with(["certbot", "certificates"])


def test_view_ssl_logs(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    with mock.patch("installer.Path.exists", return_value=True), mock.patch("installer.subprocess.run") as run:
        inst._view_ssl_logs()
    run.assert_called_once()
    with mock.patch("installer.Path.exists", return_value=False):
        inst._view_ssl_logs()
    inst.printer.warning.assert_called()


def test_force_ssl_renewal(monkeypatch, tmp_path):
    import subprocess as sp

    inst = _installer(tmp_path)
    _answers(monkeypatch, ["y"])
    with mock.patch("installer.subprocess.run") as run:
        inst._force_ssl_renewal()
    assert run.call_count == 2
    _answers(monkeypatch, ["y"])
    with mock.patch("installer.subprocess.run", side_effect=sp.CalledProcessError(1, "certbot")):
        inst._force_ssl_renewal()
    inst.printer.error.assert_called()
    _answers(monkeypatch, ["n"])
    inst._force_ssl_renewal()


def test_test_ssl_renewal(monkeypatch, tmp_path):
    import subprocess as sp

    inst = _installer(tmp_path)
    with mock.patch("installer.subprocess.run"):
        inst._test_ssl_renewal()
    inst.printer.success.assert_called()
    with mock.patch("installer.subprocess.run", side_effect=sp.CalledProcessError(1, "certbot")):
        inst._test_ssl_renewal()
    inst.printer.error.assert_called()


# ---------- addon management ----------


def _addon(name="MyAddon", has_config=True, tmp_path: Path | None = None):
    cfg = (tmp_path / f"{name}-config.yml") if tmp_path else Path(f"/tmp/{name}.yml")
    return {"name": name, "has_config": has_config, "config_path": cfg}


def test_manage_addons_menu_unavailable(tmp_path):
    inst = _installer(tmp_path)
    inst.addon_manager = None
    inst._manage_addons_menu()
    inst.printer.warning.assert_called()


def test_manage_addons_menu_no_products(tmp_path):
    inst = _installer(tmp_path)
    inst._manage_addons_menu()
    inst.printer.warning.assert_called()


def test_manage_addons_menu_selects_product(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    app = tmp_path / "plextickets"
    app.mkdir()
    inst.addon_manager.list_addons.return_value = []
    inst.systemd.get_status.return_value = "active"
    inst._manage_product_addons = mock.MagicMock()
    _answers(monkeypatch, ["1", "", "bogus", "", "0"])
    inst._manage_addons_menu()
    inst._manage_product_addons.assert_called_once_with("plextickets", app)


def test_get_addon_supported_products(tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "plextickets").mkdir()
    (tmp_path / "drakostore").mkdir()
    (tmp_path / "backups").mkdir()
    products = inst._get_addon_supported_products()
    assert [name for name, _ in products] == ["plextickets"]
    inst.config.install_dir = tmp_path / "missing"
    assert inst._get_addon_supported_products() == []


def test_require_addon_manager_guard(tmp_path):
    inst = _installer(tmp_path)
    assert inst._require_addon_manager() is inst.addon_manager
    inst.addon_manager = None
    with pytest.raises(RuntimeError, match="not available"):
        inst._require_addon_manager()


def test_manage_product_addons_dispatch(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.addon_manager.list_addons.side_effect = [
        [_addon(tmp_path=tmp_path)],  # first loop shows a table
        [],  # subsequent loops
        [],
        [],
        [],
        [],
    ]
    inst._install_addon = mock.MagicMock()
    inst._remove_addon = mock.MagicMock()
    inst._configure_addon = mock.MagicMock()
    inst._view_addon_backups = mock.MagicMock()
    _answers(monkeypatch, ["1", "", "2", "", "3", "", "4", "", "zzz", "", "0"])
    inst._manage_product_addons("plextickets", tmp_path)
    inst._install_addon.assert_called_once()
    inst._remove_addon.assert_called_once()
    inst._configure_addon.assert_called_once()
    inst._view_addon_backups.assert_called_once()


def test_install_addon_no_archives_manual_path(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.addon_manager.find_addon_archive.return_value = []
    archive = tmp_path / "cool-addon.zip"
    archive.write_bytes(b"x")
    inst.addon_manager.addon_exists.return_value = False
    inst.addon_manager.install_addon.return_value = (True, "installed", "cool")
    inst.systemd.get_status.return_value = "inactive"
    _answers(monkeypatch, [str(archive)])
    inst._install_addon("plextickets", tmp_path)
    inst.printer.success.assert_called()


def test_install_addon_manual_path_empty_and_missing(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.addon_manager.find_addon_archive.return_value = []
    _answers(monkeypatch, [""])
    inst._install_addon("plextickets", tmp_path)
    _answers(monkeypatch, ["/nope.zip"])
    inst._install_addon("plextickets", tmp_path)
    inst.printer.error.assert_called()
    inst.addon_manager.install_addon.assert_not_called()


def test_install_addon_selection_with_restart(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    archive = tmp_path / "great-addon-main.zip"
    archive.write_bytes(b"x" * 100)
    inst.addon_manager.find_addon_archive.return_value = [archive]
    inst.addon_manager.addon_exists.return_value = False
    inst.addon_manager.install_addon.return_value = (True, "ok", "great-addon")
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "y"])
    inst._install_addon("plextickets", tmp_path)
    inst.systemd.restart.assert_called_once()


def test_install_addon_selection_decline_restart(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    archive = tmp_path / "great-addon.zip"
    archive.write_bytes(b"x")
    inst.addon_manager.find_addon_archive.return_value = [archive]
    inst.addon_manager.addon_exists.return_value = False
    inst.addon_manager.install_addon.return_value = (True, "ok", "great-addon")
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "n"])
    inst._install_addon("plextickets", tmp_path)
    inst.systemd.restart.assert_not_called()


def test_install_addon_invalid_choices(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    archive = tmp_path / "a-addon.zip"
    archive.write_bytes(b"x")
    inst.addon_manager.find_addon_archive.return_value = [archive]
    _answers(monkeypatch, ["99"])
    inst._install_addon("plextickets", tmp_path)
    _answers(monkeypatch, ["abc"])
    inst._install_addon("plextickets", tmp_path)
    _answers(monkeypatch, ["0", ""])
    inst._install_addon("plextickets", tmp_path)
    _answers(monkeypatch, ["0", "/missing.zip"])
    inst._install_addon("plextickets", tmp_path)
    inst.addon_manager.install_addon.assert_not_called()


def test_install_addon_existing_collision(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    archive = tmp_path / "dup-addon-master.zip"
    archive.write_bytes(b"x")
    inst.addon_manager.find_addon_archive.return_value = [archive]
    inst.addon_manager.addon_exists.return_value = True
    _answers(monkeypatch, ["1"])
    inst._install_addon("plextickets", tmp_path)
    inst.addon_manager.install_addon.assert_not_called()


def test_install_addon_failure_message(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    archive = tmp_path / "bad-addon.zip"
    archive.write_bytes(b"x")
    inst.addon_manager.find_addon_archive.return_value = [archive]
    inst.addon_manager.addon_exists.return_value = False
    inst.addon_manager.install_addon.return_value = (False, "corrupt archive", None)
    _answers(monkeypatch, ["1"])
    inst._install_addon("plextickets", tmp_path)
    inst.printer.error.assert_called_with("corrupt archive")


def test_remove_addon_flows(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons = [_addon(tmp_path=tmp_path)]
    inst._remove_addon("p", tmp_path, [])  # empty warns
    _answers(monkeypatch, ["0"])
    inst._remove_addon("p", tmp_path, addons)  # cancel
    inst.addon_manager.remove_addon.return_value = (True, "removed")
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "n", "y", "y"])
    inst._remove_addon("p", tmp_path, addons)
    inst.addon_manager.remove_addon.assert_called_once_with("MyAddon", tmp_path, backup_first=False)
    inst.systemd.restart.assert_called_once()


def test_remove_addon_failure_and_declines(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons = [_addon(tmp_path=tmp_path)]
    inst.addon_manager.remove_addon.return_value = (False, "nope")
    _answers(monkeypatch, ["1", "", "y"])
    inst._remove_addon("p", tmp_path, addons)
    inst.printer.error.assert_called_with("nope")
    _answers(monkeypatch, ["1", "", "n"])
    inst._remove_addon("p", tmp_path, addons)
    _answers(monkeypatch, ["5"])
    inst._remove_addon("p", tmp_path, addons)
    _answers(monkeypatch, ["abc"])
    inst._remove_addon("p", tmp_path, addons)


def test_configure_addon_valid_yaml(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons = [_addon(tmp_path=tmp_path)]
    inst._run_editor = mock.MagicMock(return_value=True)
    inst.addon_manager.validate_yaml.return_value = (True, None)
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "n"])
    inst._configure_addon("p", tmp_path, addons)
    inst.printer.success.assert_called()


def test_configure_addon_invalid_yaml_fix_cycle(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons = [_addon(tmp_path=tmp_path)]
    inst._run_editor = mock.MagicMock(return_value=True)
    inst.addon_manager.validate_yaml.side_effect = [(False, "bad"), (False, "still bad")]
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "y", "y"])
    inst._configure_addon("p", tmp_path, addons)
    assert inst.addon_manager.validate_yaml.call_count == 2
    inst.systemd.restart.assert_called_once()


def test_configure_addon_edge_cases(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst._configure_addon("p", tmp_path, [_addon(has_config=False, tmp_path=tmp_path)])
    inst.printer.warning.assert_called()
    addons = [_addon(tmp_path=tmp_path)]
    _answers(monkeypatch, ["0"])
    inst._configure_addon("p", tmp_path, addons)
    _answers(monkeypatch, ["9"])
    inst._configure_addon("p", tmp_path, addons)
    _answers(monkeypatch, ["abc"])
    inst._configure_addon("p", tmp_path, addons)
    inst._run_editor = mock.MagicMock(return_value=False)
    _answers(monkeypatch, ["1"])
    inst._configure_addon("p", tmp_path, addons)
    inst.addon_manager.validate_yaml.assert_not_called()


def _backup(tmp_path, name="MyAddon"):
    import datetime

    return {
        "addon_name": name,
        "timestamp": datetime.datetime(2026, 1, 1),
        "size_mb": 1.5,
        "path": str(tmp_path / "backup.tar.gz"),
    }


def test_view_addon_backups_flows(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    inst.addon_manager.list_addon_backups.return_value = []
    inst._view_addon_backups("p", tmp_path)
    inst.printer.warning.assert_called()

    backups = [_backup(tmp_path)]
    inst.addon_manager.list_addon_backups.return_value = backups
    _answers(monkeypatch, ["0"])
    inst._view_addon_backups("p", tmp_path)
    _answers(monkeypatch, ["7"])
    inst._view_addon_backups("p", tmp_path)
    _answers(monkeypatch, ["abc"])
    inst._view_addon_backups("p", tmp_path)
    inst.addon_manager.addon_exists.return_value = True
    inst._restore_addon_backup = mock.MagicMock()
    _answers(monkeypatch, ["1", "y"])
    inst._view_addon_backups("p", tmp_path)
    inst._restore_addon_backup.assert_called_once()
    _answers(monkeypatch, ["1", "n"])
    inst._view_addon_backups("p", tmp_path)


def test_restore_addon_backup_success(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons_path = tmp_path / "addons"
    inst.addon_manager.get_addons_path.return_value = addons_path

    def fake_extract(_backup, root, expected_top_level):
        (root / expected_top_level).mkdir(parents=True)

    monkeypatch.setattr("installer.safe_extract_tar", fake_extract)
    installed = mock.MagicMock()
    monkeypatch.setattr("installer.install_staged_directory", installed)
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["y"])
    inst._restore_addon_backup("p", tmp_path, _backup(tmp_path))
    installed.assert_called_once()
    inst.systemd.restart.assert_called_once()
    inst.printer.success.assert_called()


def test_restore_addon_backup_rolls_back_previous(monkeypatch, tmp_path):
    inst = _installer(tmp_path)
    addons_path = tmp_path / "addons"
    addons_path.mkdir()
    previous = addons_path / "MyAddon"
    previous.mkdir()
    (previous / "old.txt").write_text("old")
    inst.addon_manager.get_addons_path.return_value = addons_path

    def fake_extract(_backup, root, expected_top_level):
        (root / expected_top_level).mkdir(parents=True)

    monkeypatch.setattr("installer.safe_extract_tar", fake_extract)
    monkeypatch.setattr("installer.install_staged_directory", mock.MagicMock(side_effect=RuntimeError("disk full")))
    inst._restore_addon_backup("p", tmp_path, _backup(tmp_path))
    inst.printer.error.assert_called()
    assert (previous / "old.txt").read_text() == "old"


def test_restore_addon_backup_invalid_name(tmp_path):
    inst = _installer(tmp_path)
    bad = _backup(tmp_path, name="../evil")
    inst._restore_addon_backup("p", tmp_path, bad)
    inst.printer.error.assert_called_with("Restore failed: Invalid addon name: '../evil'")


def test_restore_addon_backup_missing_metadata_key(tmp_path):
    inst = _installer(tmp_path)
    inst._restore_addon_backup("p", tmp_path, {"addon_name": "MyAddon"})
    inst.printer.error.assert_called_with("Restore failed: 'path'")
