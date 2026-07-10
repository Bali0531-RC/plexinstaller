"""Gap-closing coverage tests for installer.py (no system interaction)."""

import datetime
import importlib
import sys
from pathlib import Path
from unittest import mock

import installer as installer_module
from config import Config
from installer import InstallationContext, PlexInstaller


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


# ---------- ImportError fallbacks (lines 42-43, 65-84) ----------


def test_import_fallbacks_when_optional_modules_missing():
    blocked = ["addon_manager", "shared", "mongodb_manager", "backup_manager", "health_checker"]
    saved = {name: sys.modules.get(name) for name in blocked}
    saved_installer = sys.modules.get("installer")
    try:
        for name in blocked:
            sys.modules[name] = None  # forces ImportError on import
        sys.modules.pop("installer", None)
        fresh = importlib.import_module("installer")
        assert fresh.AddonManager is None
        assert fresh.MongoDBManager is None
        assert fresh.BackupManager is None
        assert fresh.HealthChecker is None
        assert fresh.SelfTestResult is None
        assert fresh._shared_is_newer is None
        assert fresh.INSTALLER_DIR == Path("/opt/plexinstaller")
    finally:
        for name, value in saved.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
        if saved_installer is not None:
            sys.modules["installer"] = saved_installer


# ---------- locking (217-218, 231-234) ----------


def test_acquire_lock_closes_fd_on_flock_failure(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    monkeypatch.setattr(installer_module, "LOCK_FILE", str(tmp_path / "lock"))
    monkeypatch.setattr(installer_module.fcntl, "flock", mock.MagicMock(side_effect=OSError("busy")))
    assert inst._acquire_lock() is False
    assert inst._lock_fd is None


def test_release_lock_swallows_unlink_error(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    lock_file = tmp_path / "lock"
    monkeypatch.setattr(installer_module, "LOCK_FILE", str(lock_file))
    assert inst._acquire_lock() is True
    monkeypatch.setattr(installer_module.os, "unlink", mock.MagicMock(side_effect=OSError("nope")))
    inst._release_lock()
    assert inst._lock_fd is None


def test_release_lock_swallows_generic_exception(tmp_path):
    inst = _installer(tmp_path)
    bad_fd = mock.MagicMock()
    bad_fd.fileno.side_effect = RuntimeError("boom")
    inst._lock_fd = bad_fd
    inst._release_lock()  # must not raise


# ---------- telemetry preference (301->307) ----------


def test_telemetry_preference_prompts_when_file_missing(tmp_path):
    inst = _installer(tmp_path)
    inst.config.telemetry_pref_file = tmp_path / "missing-pref"
    inst._prompt_telemetry_preference = mock.MagicMock(return_value=True)
    assert inst._initialize_telemetry_preference() is True
    inst._prompt_telemetry_preference.assert_called_once()


# ---------- main menu loop (518->448) ----------


def test_main_menu_invalid_choice_then_exit(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    inst._display_banner = mock.MagicMock()
    inst._show_services_status = mock.MagicMock()
    monkeypatch.setattr(installer_module.os, "system", lambda _cmd: 0)
    answers = iter(["banana", "", "0"])
    monkeypatch.setattr("builtins.input", lambda _p="": next(answers))
    assert inst._show_main_menu() == 0
    inst.printer.error.assert_called_with("Invalid choice")


# ---------- services status table (543->555, 549->543, 552-553) ----------


def test_show_services_status_config_edge_cases(tmp_path):
    inst = _installer(tmp_path)
    # product with unreadable config (config.yml is a directory -> read_text raises)
    broken = tmp_path / "broken"
    (broken / "config.yml").mkdir(parents=True)
    # product with config missing a port entry
    noport = tmp_path / "noport"
    noport.mkdir()
    (noport / "config.yaml").write_text("name: hello\n")
    # product without any config files
    bare = tmp_path / "bare"
    bare.mkdir()
    inst.systemd.get_status.side_effect = ["active", "inactive", "failed"]
    inst._show_services_status()
    assert inst.systemd.get_status.call_count == 3


# ---------- _install_product error paths ----------


def test_install_product_existing_path_aborts(tmp_path):
    inst = _installer(tmp_path)
    (tmp_path / "plexstore").mkdir()
    inst._handle_multi_instance = mock.MagicMock(return_value="plexstore")
    assert inst._install_product("plexstore", 3003) == 1
    inst.printer.warning.assert_any_call(mock.ANY)


def test_install_product_keyboardinterrupt_without_telemetry(tmp_path):
    inst = _installer(tmp_path)
    inst.telemetry = None
    inst._handle_multi_instance = mock.MagicMock(side_effect=KeyboardInterrupt)
    assert inst._install_product("plexstore", 3003) == 1


def test_install_product_userabort_without_telemetry(tmp_path):
    inst = _installer(tmp_path)
    inst.telemetry = None
    inst._handle_multi_instance = mock.MagicMock(side_effect=installer_module.UserAbortError("no"))
    assert inst._install_product("plexstore", 3003) == 1


def test_install_product_failure_with_telemetry_disabled(tmp_path):
    inst = _installer(tmp_path)
    inst.telemetry_enabled = False
    inst._handle_multi_instance = mock.MagicMock(side_effect=RuntimeError("boom"))
    assert inst._install_product("plexstore", 3003) == 1
    inst.telemetry.finish_session.assert_not_called()


def test_install_product_failure_uploads_log(tmp_path):
    inst = _installer(tmp_path)
    inst._handle_multi_instance = mock.MagicMock(return_value="plexstore")
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "a.zip")
    inst._extract_product = mock.MagicMock(side_effect=RuntimeError("explode"))
    inst._confirm = mock.MagicMock(return_value=True)
    inst._cleanup_failed_install = mock.MagicMock()
    inst.telemetry.share_log.return_value = "https://paste/xyz"
    assert inst._install_product("plexstore", 3003) == 1
    inst._cleanup_failed_install.assert_called_once()
    inst.printer.warning.assert_any_call("Failure log uploaded: https://paste/xyz")


def test_full_install_success_without_web_with_dashboard(tmp_path):
    inst = _installer(tmp_path)
    extracted = tmp_path / "plextickets"
    inst._handle_multi_instance = mock.MagicMock(return_value="plextickets")
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "a.zip")

    def fake_extract(_archive, _name):
        extracted.mkdir()
        return extracted

    inst._extract_product = mock.MagicMock(side_effect=fake_extract)
    inst._isolation_requested = mock.MagicMock(return_value=False)
    inst._install_npm_dependencies = mock.MagicMock(return_value=True)
    inst._create_502_page = mock.MagicMock()
    inst.mongo_manager.setup.return_value = None
    inst._install_dashboard = mock.MagicMock()
    inst._setup_systemd = mock.MagicMock(return_value=False)
    inst.health.run_post_install_self_tests.return_value = []
    inst._write_resource_manifest = mock.MagicMock()
    inst._post_install = mock.MagicMock()
    result = inst._install_product("plextickets", 3000, has_dashboard=True, needs_web=False)
    assert result == 0
    inst._install_dashboard.assert_called_once()


# ---------- multi-instance & archive search ----------


def test_multi_instance_when_install_dir_missing(tmp_path):
    inst = _installer(tmp_path)
    inst.config.install_dir = tmp_path / "does-not-exist"
    assert inst._handle_multi_instance("plexstaff") == "plexstaff"


def test_find_archive_skips_missing_search_dirs(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    archive = tmp_path / "plexstaff.zip"
    archive.write_bytes(b"data")
    monkeypatch.setattr(installer_module.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(installer_module.Path, "cwd", classmethod(lambda cls: tmp_path))
    real_exists = Path.exists

    def fake_exists(self, **kwargs):
        if str(self) in {"/root", "/tmp", "/var/tmp"}:
            return False
        return real_exists(self, **kwargs)

    monkeypatch.setattr(Path, "exists", fake_exists)
    _answers(monkeypatch, ["1"])
    found = inst._find_archive("plexstaff")
    assert found is not None and found.name == "plexstaff.zip"


# ---------- dashboard install (1119->exit, 1120->1122) ----------


def test_install_dashboard_extraction_returns_nothing(tmp_path):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "dash.zip")
    inst.extractor.extract.return_value = None
    inst._install_npm_dependencies = mock.MagicMock()
    inst._install_dashboard(tmp_path, run_as_user=None)
    inst._install_npm_dependencies.assert_not_called()


def test_install_dashboard_without_run_as_user(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "dash.zip")
    inst.extractor.extract.return_value = tmp_path / "dash"
    inst._install_npm_dependencies = mock.MagicMock()
    run = mock.MagicMock()
    monkeypatch.setattr(installer_module.subprocess, "run", run)
    inst._install_dashboard(tmp_path, run_as_user=None)
    run.assert_not_called()
    inst._install_npm_dependencies.assert_called_once()


# ---------- systemd setup (1139->1155) ----------


def test_setup_systemd_root_mode_when_isolation_declined(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=True)
    inst._isolation_requested = mock.MagicMock(return_value=False)
    inst._create_systemd_service = mock.MagicMock()
    assert inst._setup_systemd("plexstaff", tmp_path) is True
    inst._create_systemd_service.assert_called_once_with("plexstaff", tmp_path, isolated=False)


# ---------- post install (1199-1211) ----------


def test_post_install_skip_editor_with_domain(tmp_path):
    inst = _installer(tmp_path)
    install = tmp_path / "app"
    install.mkdir()
    (install / "config.yml").write_text("port: 3000\n")
    inst._confirm = mock.MagicMock(return_value=False)
    inst._post_install("plexstaff", install, "example.com", True)
    inst.printer.success.assert_any_call("Access at: https://example.com")


def test_post_install_editor_success_no_web(tmp_path):
    inst = _installer(tmp_path)
    install = tmp_path / "app"
    install.mkdir()
    (install / "config.yaml").write_text("port: 3000\n")
    inst._confirm = mock.MagicMock(return_value=True)
    inst._run_editor = mock.MagicMock(return_value=True)
    inst._post_install("plexstaff", install, None, False)
    inst._run_editor.assert_called_once()


# ---------- cleanup / nginx removal (1251-1252, 1271->1273, 1281-1297) ----------


def test_cleanup_failed_install_rmtree_failure(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    install = tmp_path / "app"
    install.mkdir()
    context = InstallationContext(
        product="plexstaff",
        instance_name="plexstaff",
        install_path=install,
        port=3001,
        install_path_created=True,
    )
    monkeypatch.setattr(installer_module.shutil, "rmtree", mock.MagicMock(side_effect=RuntimeError("locked")))
    inst._cleanup_failed_install(context)
    inst.printer.warning.assert_any_call("Failed to remove install directory: locked")


def test_cleanup_failed_install_mongo_identity_without_database(tmp_path):
    inst = _installer(tmp_path)
    context = InstallationContext(
        product="plexstaff",
        instance_name="plexstaff",
        install_path=tmp_path / "app",
        port=3001,
        mongo_identity={"database": "", "username": "user"},
    )
    inst._cleanup_failed_install(context)
    inst.mongo_manager.cleanup_identity.assert_not_called()
    inst.mongo_manager.remove_saved_credentials.assert_called_once_with("plexstaff")


def test_remove_nginx_config_handles_all_failures(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    available = tmp_path / "avail"
    enabled = tmp_path / "enabled"
    available.mkdir()
    enabled.mkdir()
    inst.config.nginx_available = available
    inst.config.nginx_enabled = enabled
    (available / "example.com.conf").write_text("server {}")
    (enabled / "example.com.conf").write_text("server {}")
    monkeypatch.setattr(Path, "unlink", mock.MagicMock(side_effect=OSError("readonly")))
    monkeypatch.setattr(installer_module.subprocess, "run", mock.MagicMock(side_effect=RuntimeError("no nginx")))
    inst._remove_nginx_config("example.com")
    warnings = [str(c.args[0]) for c in inst.printer.warning.call_args_list]
    assert any("enabled nginx config" in w for w in warnings)
    assert any("Failed to remove nginx config" in w for w in warnings)


# ---------- manage menus ----------


def test_manage_installations_out_of_range_choice(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    (tmp_path / "plexstaff").mkdir()
    inst.systemd.get_status.return_value = "active"
    inst._manage_product = mock.MagicMock()
    _answers(monkeypatch, ["99"])
    inst._manage_installations()
    inst._manage_product.assert_not_called()


def test_manage_product_unknown_choice_then_back(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["7", "0"])
    inst._manage_product("plexstaff")


# ---------- uninstall (1426, 1446, 1449, 1456, 1460) ----------


def test_uninstall_domain_without_certificate_and_no_mongo(tmp_path):
    inst = _installer(tmp_path)
    inst._confirm = mock.MagicMock(return_value=True)
    inst._remove_nginx_config = mock.MagicMock()
    inst._remove_ssl_certificate = mock.MagicMock()
    inst._load_resource_manifest = mock.MagicMock(
        return_value={
            "instance": "plexstaff",
            "service": "plex-plexstaff",
            "domain": "example.com",
            "certificate": False,
            "mongodb": {},
        }
    )
    inst.mongo_manager.cleanup_identity.return_value = True
    assert inst._uninstall_product("plexstaff") is True
    inst._remove_nginx_config.assert_called_once_with("example.com")
    inst._remove_ssl_certificate.assert_not_called()


def test_uninstall_with_drop_data_and_existing_path(tmp_path):
    inst = _installer(tmp_path)
    install = tmp_path / "plexstaff"
    install.mkdir()
    inst._confirm = mock.MagicMock(return_value=True)
    inst._load_resource_manifest = mock.MagicMock(
        return_value={
            "instance": "plexstaff",
            "service": "plex-plexstaff",
            "firewall_port": 3001,
            "mongodb": {"database": "db", "username": "user"},
        }
    )
    inst.mongo_manager.cleanup_identity.return_value = True
    assert inst._uninstall_product("plexstaff") is True
    assert not install.exists()
    inst.mongo_manager.cleanup_identity.assert_called_once_with("db", "user", drop_database=True)


# ---------- resource manifest defaults (1503->1526) ----------


def test_load_manifest_instance_mismatch_uses_defaults(tmp_path):
    inst = _installer(tmp_path)
    install = tmp_path / "plexstaff"
    install.mkdir()
    (install / installer_module.RESOURCE_MANIFEST).write_text(f'{{"instance": "other", "install_path": "{install}"}}')
    manifest = inst._load_resource_manifest(install, "plexstaff")
    assert manifest["schema_version"] == 0
    assert manifest["service"] == "plex-plexstaff"


# ---------- SSL menu (1536-1564) ----------


def test_ssl_menu_invalid_choice_then_back(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    monkeypatch.setattr(installer_module.os, "system", lambda _cmd: 0)
    _answers(monkeypatch, ["nope", "", "0"])
    inst._ssl_management_menu()
    inst.printer.error.assert_called_with("Invalid choice")


# ---------- addon menus ----------


def test_manage_addons_menu_invalid_and_out_of_range(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    monkeypatch.setattr(installer_module.os, "system", lambda _cmd: 0)
    inst._get_addon_supported_products = mock.MagicMock(return_value=[("plextickets", tmp_path)])
    inst.addon_manager.list_addons.return_value = []
    inst.systemd.get_status.return_value = "active"
    inst._manage_product_addons = mock.MagicMock()
    _answers(monkeypatch, ["abc", "", "9", "", "0"])
    inst._manage_addons_menu()
    inst._manage_product_addons.assert_not_called()


def test_manage_product_addons_invalid_choice(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    monkeypatch.setattr(installer_module.os, "system", lambda _cmd: 0)
    inst.addon_manager.list_addons.return_value = []
    _answers(monkeypatch, ["zzz", "", "0"])
    inst._manage_product_addons("plextickets", tmp_path)
    inst.printer.error.assert_called_with("Invalid choice")


def test_install_addon_many_archives_custom_path_collision(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    archives = []
    for i in range(25):
        f = tmp_path / f"addon-{i}.zip"
        f.write_bytes(b"x" * 10)
        archives.append(f)
    custom = tmp_path / "myaddon-main.zip"
    custom.write_bytes(b"y")
    inst.addon_manager.find_addon_archive.return_value = archives
    inst.addon_manager.addon_exists.return_value = True
    _answers(monkeypatch, ["0", str(custom)])
    inst._install_addon("plextickets", tmp_path)
    inst.addon_manager.addon_exists.assert_called_once_with("myaddon", tmp_path)
    inst.addon_manager.install_addon.assert_not_called()


def test_remove_addon_service_not_active(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    addons = [{"name": "myaddon"}]
    inst.addon_manager.remove_addon.return_value = (True, "removed")
    inst.systemd.get_status.return_value = "inactive"
    _answers(monkeypatch, ["1", "n", "y"])
    inst._remove_addon("plextickets", tmp_path, addons)
    inst.systemd.restart.assert_not_called()


def test_remove_addon_restart_declined(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    addons = [{"name": "myaddon"}]
    inst.addon_manager.remove_addon.return_value = (True, "removed")
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "n", "y", "n"])
    inst._remove_addon("plextickets", tmp_path, addons)
    inst.systemd.restart.assert_not_called()


def test_configure_addon_fix_succeeds_service_inactive(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    config_path = tmp_path / "config.yml"
    config_path.write_text("a: 1\n")
    addons = [{"name": "myaddon", "has_config": True, "config_path": config_path}]
    inst._run_editor = mock.MagicMock(return_value=True)
    inst.addon_manager.validate_yaml.side_effect = [(False, "bad"), (True, None)]
    inst.systemd.get_status.return_value = "inactive"
    _answers(monkeypatch, ["1", "y"])
    inst._configure_addon("plextickets", tmp_path, addons)
    inst.printer.success.assert_any_call("Configuration file is now valid YAML")


def test_configure_addon_fix_declined_restart_declined(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    config_path = tmp_path / "config.yml"
    config_path.write_text("a: 1\n")
    addons = [{"name": "myaddon", "has_config": True, "config_path": config_path}]
    inst._run_editor = mock.MagicMock(return_value=True)
    inst.addon_manager.validate_yaml.return_value = (False, "bad")
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["1", "n", "n"])
    inst._configure_addon("plextickets", tmp_path, addons)
    inst.systemd.restart.assert_not_called()


def test_view_addon_backups_restore_when_addon_missing(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    backup = {
        "addon_name": "myaddon",
        "timestamp": datetime.datetime(2026, 1, 1, 12, 0, 0),
        "size_mb": 1.5,
        "path": str(tmp_path / "b.tar.gz"),
    }
    inst.addon_manager.list_addon_backups.return_value = [backup]
    inst.addon_manager.addon_exists.return_value = False
    inst._restore_addon_backup = mock.MagicMock()
    _answers(monkeypatch, ["1", "y"])
    inst._view_addon_backups("plextickets", tmp_path)
    inst._restore_addon_backup.assert_called_once()


# ---------- addon backup restore (2004-2016) ----------


def _restore_env(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    product_path = tmp_path / "plextickets"
    addons_path = product_path / "addons"
    addons_path.mkdir(parents=True)
    inst.addon_manager.get_addons_path.return_value = addons_path
    inst.addon_manager._set_permissions = mock.MagicMock()

    def fake_extract(_backup, extraction_root, expected_top_level=None):
        staged = Path(extraction_root) / expected_top_level
        staged.mkdir(parents=True)
        (staged / "index.js").write_text("ok")
        return Path(extraction_root)

    monkeypatch.setattr(installer_module, "safe_extract_tar", fake_extract)
    backup = {"addon_name": "myaddon", "path": str(tmp_path / "b.tar.gz")}
    return inst, product_path, addons_path, backup


def test_restore_addon_backup_success_service_inactive(tmp_path, monkeypatch):
    inst, product_path, addons_path, backup = _restore_env(tmp_path, monkeypatch)
    inst.systemd.get_status.return_value = "inactive"
    inst._restore_addon_backup("plextickets", product_path, backup)
    assert (addons_path / "myaddon" / "index.js").exists()
    inst.systemd.restart.assert_not_called()


def test_restore_addon_backup_restart_declined(tmp_path, monkeypatch):
    inst, product_path, addons_path, backup = _restore_env(tmp_path, monkeypatch)
    inst.systemd.get_status.return_value = "active"
    _answers(monkeypatch, ["n"])
    inst._restore_addon_backup("plextickets", product_path, backup)
    assert (addons_path / "myaddon").exists()
    inst.systemd.restart.assert_not_called()


def test_restore_addon_backup_publish_failure_without_rollback(tmp_path, monkeypatch):
    inst, product_path, _addons_path, backup = _restore_env(tmp_path, monkeypatch)
    monkeypatch.setattr(
        installer_module,
        "install_staged_directory",
        mock.MagicMock(side_effect=RuntimeError("publish failed")),
    )
    inst._restore_addon_backup("plextickets", product_path, backup)
    inst.printer.error.assert_called_with("Restore failed: publish failed")


def test_restore_addon_backup_publish_failure_rolls_back_previous(tmp_path, monkeypatch):
    inst, product_path, addons_path, backup = _restore_env(tmp_path, monkeypatch)
    existing = addons_path / "myaddon"
    existing.mkdir()
    (existing / "old.js").write_text("old")
    monkeypatch.setattr(
        installer_module,
        "install_staged_directory",
        mock.MagicMock(side_effect=RuntimeError("publish failed")),
    )
    inst._restore_addon_backup("plextickets", product_path, backup)
    assert (addons_path / "myaddon" / "old.js").exists()
    inst.printer.error.assert_called_with("Restore failed: publish failed")


# ---------- extra branch sweeps ----------


def test_full_install_without_mongo_manager(tmp_path):
    inst = _installer(tmp_path)
    inst.mongo_manager = None
    inst.config.get_product = lambda _p: None
    extracted = tmp_path / "drakopaste"
    inst._handle_multi_instance = mock.MagicMock(return_value="drakopaste")
    inst._find_archive = mock.MagicMock(return_value=tmp_path / "a.zip")

    def fake_extract(_archive, _name):
        extracted.mkdir()
        return extracted

    inst._extract_product = mock.MagicMock(side_effect=fake_extract)
    inst._isolation_requested = mock.MagicMock(return_value=False)
    inst._install_npm_dependencies = mock.MagicMock(return_value=True)
    inst._create_502_page = mock.MagicMock()
    inst._setup_systemd = mock.MagicMock(return_value=False)
    inst.health.run_post_install_self_tests.return_value = []
    inst._write_resource_manifest = mock.MagicMock()
    inst._post_install = mock.MagicMock()
    assert inst._install_product("drakopaste", 3006, needs_web=False) == 0


def test_remove_nginx_config_only_available_file(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    available = tmp_path / "avail"
    enabled = tmp_path / "enabled"
    available.mkdir()
    enabled.mkdir()
    inst.config.nginx_available = available
    inst.config.nginx_enabled = enabled
    (available / "only.example.conf").write_text("server {}")
    monkeypatch.setattr(installer_module.subprocess, "run", mock.MagicMock())
    inst._remove_nginx_config("only.example")
    assert not (available / "only.example.conf").exists()


def test_remove_nginx_config_only_enabled_link(tmp_path, monkeypatch):
    inst = _installer(tmp_path)
    available = tmp_path / "avail"
    enabled = tmp_path / "enabled"
    available.mkdir()
    enabled.mkdir()
    inst.config.nginx_available = available
    inst.config.nginx_enabled = enabled
    (enabled / "link.example.conf").write_text("server {}")
    monkeypatch.setattr(installer_module.subprocess, "run", mock.MagicMock())
    inst._remove_nginx_config("link.example")
    assert not (enabled / "link.example.conf").exists()


def test_uninstall_without_mongo_manager_and_empty_manifest_mongo(tmp_path):
    inst = _installer(tmp_path)
    inst.mongo_manager = None
    inst._confirm = mock.MagicMock(return_value=True)
    inst._load_resource_manifest = mock.MagicMock(
        return_value={
            "instance": "plexstaff",
            "service": "plex-plexstaff",
            "mongodb": {},
        }
    )
    assert inst._uninstall_product("plexstaff") is True
