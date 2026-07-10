"""Additional coverage tests for addon_manager.py."""

import json
import subprocess
import tarfile
from pathlib import Path
from unittest import mock

from addon_manager import AddonManager
from utils import SystemdManager


def _manager() -> AddonManager:
    return AddonManager()


# ---------------------------------------------------------------------------
# list_addons
# ---------------------------------------------------------------------------


class TestListAddons:
    def test_no_addons_dir_returns_empty(self, tmp_path: Path):
        assert _manager().list_addons(tmp_path / "product") == []

    def test_lists_dirs_skips_files_and_symlinks(self, tmp_path: Path):
        product = tmp_path / "product"
        addons = product / "addons"
        addons.mkdir(parents=True)
        (addons / "Alpha").mkdir()
        (addons / "Alpha" / "config.yml").write_text("a: 1\n")
        (addons / "Beta").mkdir()
        (addons / "loose.txt").write_text("x")
        (addons / "Link").symlink_to(addons / "Alpha")

        result = _manager().list_addons(product)

        names = [a["name"] for a in result]
        assert names == ["Alpha", "Beta"]
        assert result[0]["has_config"] is True
        assert result[0]["config_path"].name == "config.yml"
        assert result[1]["has_config"] is False
        assert result[1]["config_path"] is None

    def test_finds_yaml_extension(self, tmp_path: Path):
        product = tmp_path / "product"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        (addon / "config.yaml").write_text("k: v\n")
        result = _manager().list_addons(product)
        assert result[0]["config_path"].name == "config.yaml"


# ---------------------------------------------------------------------------
# _service_owner
# ---------------------------------------------------------------------------


class TestServiceOwner:
    def test_none_product_path_is_root(self):
        assert AddonManager._service_owner(None) == "root"

    def test_missing_manifest_is_root(self, tmp_path: Path):
        assert AddonManager._service_owner(tmp_path / "product") == "root"

    def test_invalid_json_is_root(self, tmp_path: Path):
        product = tmp_path / "product"
        product.mkdir()
        (product / ".plexinstaller-resources.json").write_text("{not json")
        assert AddonManager._service_owner(product) == "root"

    def test_not_isolated_is_root(self, tmp_path: Path):
        product = tmp_path / "product"
        product.mkdir()
        (product / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": False, "service_user": "plex-product"})
        )
        assert AddonManager._service_owner(product) == "root"

    def test_unexpected_user_is_root(self, tmp_path: Path):
        product = tmp_path / "product"
        product.mkdir()
        (product / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": True, "service_user": "evil"})
        )
        assert AddonManager._service_owner(product) == "root"

    def test_valid_isolated_user_returned(self, tmp_path: Path):
        product = tmp_path / "tickets"
        product.mkdir()
        expected = SystemdManager.service_user_name("tickets")
        (product / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": True, "service_user": expected})
        )
        with mock.patch("addon_manager.pwd.getpwnam", return_value=object()):
            assert AddonManager._service_owner(product) == expected

    def test_legacy_long_isolated_user_returned(self, tmp_path: Path):
        product = tmp_path / ("tickets-" + "x" * 40)
        product.mkdir()
        legacy = SystemdManager.legacy_service_user_name(product.name)
        assert legacy != SystemdManager.service_user_name(product.name)
        (product / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": True, "service_user": legacy})
        )
        with mock.patch("addon_manager.pwd.getpwnam", return_value=object()):
            assert AddonManager._service_owner(product) == legacy

    def test_missing_system_user_is_root(self, tmp_path: Path):
        product = tmp_path / "tickets"
        product.mkdir()
        expected = SystemdManager.service_user_name("tickets")
        (product / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": True, "service_user": expected})
        )
        with mock.patch("addon_manager.pwd.getpwnam", side_effect=KeyError(expected)):
            assert AddonManager._service_owner(product) == "root"


# ---------------------------------------------------------------------------
# _set_permissions
# ---------------------------------------------------------------------------


class TestSetPermissions:
    def test_sets_owner_and_modes(self, tmp_path: Path):
        addon = tmp_path / "addon"
        addon.mkdir()
        (addon / "config.yml").write_text("k: v\n")
        (addon / "run.sh").write_text("#!/bin/sh\n")
        (addon / "readme.txt").write_text("hi\n")
        sub = addon / "sub"
        sub.mkdir()
        (sub / "index.js").write_text("x")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch("subprocess.run", side_effect=fake_run):
            _manager()._set_permissions(addon, product_path=None)

        assert calls[0][:2] == ["chown", "-R"]
        assert "root:root" in calls[0]
        assert calls[1][0] == "find"
        assert (addon / "config.yml").stat().st_mode & 0o777 == 0o600
        assert (addon / "run.sh").stat().st_mode & 0o777 == 0o750
        assert (addon / "readme.txt").stat().st_mode & 0o777 == 0o640
        assert (sub / "index.js").stat().st_mode & 0o777 == 0o640

    def test_skips_symlinks(self, tmp_path: Path):
        addon = tmp_path / "addon"
        addon.mkdir()
        real = addon / "real.txt"
        real.write_text("x")
        (addon / "link.txt").symlink_to(real)

        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            _manager()._set_permissions(addon)

        assert (addon / "real.txt").stat().st_mode & 0o777 == 0o640


# ---------------------------------------------------------------------------
# addon_exists / get_addon_config_path
# ---------------------------------------------------------------------------


class TestAddonExists:
    def test_exists_true(self, tmp_path: Path):
        product = tmp_path / "p"
        (product / "addons" / "A").mkdir(parents=True)
        assert _manager().addon_exists("A", product) is True

    def test_missing_false(self, tmp_path: Path):
        assert _manager().addon_exists("A", tmp_path / "p") is False

    def test_file_not_dir_false(self, tmp_path: Path):
        product = tmp_path / "p"
        (product / "addons").mkdir(parents=True)
        (product / "addons" / "A").write_text("x")
        assert _manager().addon_exists("A", product) is False


class TestGetAddonConfigPath:
    def test_missing_addon_returns_none(self, tmp_path: Path):
        assert _manager().get_addon_config_path("A", tmp_path / "p") is None

    def test_symlink_addon_returns_none(self, tmp_path: Path):
        product = tmp_path / "p"
        addons = product / "addons"
        real = addons / "Real"
        real.mkdir(parents=True)
        (addons / "A").symlink_to(real)
        assert _manager().get_addon_config_path("A", product) is None

    def test_returns_config(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        (addon / "config.yml").write_text("k: v\n")
        result = _manager().get_addon_config_path("A", product)
        assert result is not None and result.name == "config.yml"

    def test_no_config_returns_none(self, tmp_path: Path):
        product = tmp_path / "p"
        (product / "addons" / "A").mkdir(parents=True)
        assert _manager().get_addon_config_path("A", product) is None


# ---------------------------------------------------------------------------
# backup_addon
# ---------------------------------------------------------------------------


class TestBackupAddon:
    def test_backup_missing_addon(self, tmp_path: Path):
        ok, msg, path = _manager().backup_addon("A", tmp_path / "p")
        assert ok is False
        assert "not found" in msg
        assert path is None

    def test_backup_symlink_rejected(self, tmp_path: Path):
        product = tmp_path / "p"
        addons = product / "addons"
        real = addons / "Real"
        real.mkdir(parents=True)
        (addons / "A").symlink_to(real)
        ok, msg, path = _manager().backup_addon("A", product)
        assert ok is False

    def test_backup_success(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        (addon / "index.js").write_text("x")

        ok, msg, path = _manager().backup_addon("A", product)

        assert ok is True
        assert path is not None and path.exists()
        assert path.stat().st_mode & 0o777 == 0o600
        with tarfile.open(path) as tar:
            assert "A/index.js" in tar.getnames()

    def test_backup_failure_removes_partial_file(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        with mock.patch("addon_manager.tarfile.open", side_effect=OSError("boom")):
            ok, msg, path = _manager().backup_addon("A", product)
        assert ok is False
        assert "boom" in msg
        assert path is None
        assert list((product.parent / "backups" / "addons").glob("*.tar.gz")) == []


# ---------------------------------------------------------------------------
# remove_addon
# ---------------------------------------------------------------------------


class TestRemoveAddon:
    def test_remove_missing(self, tmp_path: Path):
        ok, msg = _manager().remove_addon("A", tmp_path / "p")
        assert ok is False
        assert "not found" in msg

    def test_remove_with_backup(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        (addon / "file").write_text("x")

        ok, msg = _manager().remove_addon("A", product, backup_first=True)

        assert ok is True
        assert not addon.exists()
        assert len(list((product.parent / "backups" / "addons").glob("*.tar.gz"))) == 1

    def test_remove_without_backup(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        ok, _ = _manager().remove_addon("A", product, backup_first=False)
        assert ok is True
        assert not addon.exists()
        assert not (product.parent / "backups").exists()

    def test_backup_failure_aborts_removal(self, tmp_path: Path):
        manager = _manager()
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        with mock.patch.object(manager, "backup_addon", return_value=(False, "no space", None)):
            ok, msg = manager.remove_addon("A", product)
        assert ok is False
        assert "no space" in msg
        assert addon.exists()

    def test_rmtree_failure_reported(self, tmp_path: Path):
        product = tmp_path / "p"
        addon = product / "addons" / "A"
        addon.mkdir(parents=True)
        with mock.patch("addon_manager.shutil.rmtree", side_effect=OSError("locked")):
            ok, msg = _manager().remove_addon("A", product, backup_first=False)
        assert ok is False
        assert "locked" in msg


# ---------------------------------------------------------------------------
# validate_yaml
# ---------------------------------------------------------------------------


class TestValidateYaml:
    def test_valid_yaml(self, tmp_path: Path):
        cfg = tmp_path / "config.yml"
        cfg.write_text("key: value\nlist:\n  - a\n")
        ok, err = _manager().validate_yaml(cfg)
        assert ok is True
        assert err is None

    def test_invalid_yaml_reports_line(self, tmp_path: Path):
        cfg = tmp_path / "config.yml"
        cfg.write_text("key: value\n  bad indent: [\n")
        ok, err = _manager().validate_yaml(cfg)
        assert ok is False
        assert err

    def test_missing_file(self, tmp_path: Path):
        ok, err = _manager().validate_yaml(tmp_path / "nope.yml")
        assert ok is False
        assert err


# ---------------------------------------------------------------------------
# find_addon_archive
# ---------------------------------------------------------------------------


class TestFindAddonArchive:
    def test_skips_missing_dirs_and_dedupes(self, tmp_path: Path):
        d = tmp_path / "search"
        d.mkdir()
        (d / "Beta.zip").write_bytes(b"")
        (d / "alpha.tar.gz").write_bytes(b"")
        sub = d / "sub"
        sub.mkdir()
        (sub / "gamma.tgz").write_bytes(b"")
        missing = tmp_path / "missing"

        result = _manager().find_addon_archive([d, missing, d])

        names = [p.name for p in result]
        assert names == ["alpha.tar.gz", "Beta.zip", "gamma.tgz"]

    def test_default_dirs_used_when_none(self, tmp_path: Path):
        with (
            mock.patch("addon_manager.Path.home", return_value=tmp_path / "none"),
            mock.patch("addon_manager.Path.cwd", return_value=tmp_path / "none"),
        ):
            result = _manager().find_addon_archive(None)
        assert isinstance(result, list)

    def test_default_search_does_not_scan_system_temp(self, tmp_path: Path):
        rglob = mock.MagicMock(side_effect=AssertionError("system temp directory was scanned"))
        with (
            mock.patch("addon_manager._SYSTEM_TEMP_ROOTS", frozenset({tmp_path.resolve()})),
            mock.patch("addon_manager.Path.home", return_value=tmp_path),
            mock.patch("addon_manager.Path.cwd", return_value=tmp_path / "nested"),
            mock.patch.object(Path, "rglob", rglob),
        ):
            assert _manager().find_addon_archive() == []
        rglob.assert_not_called()

    def test_explicit_system_temp_search_is_still_supported(self, tmp_path: Path):
        archive = tmp_path / "addon.zip"
        archive.write_bytes(b"")
        with mock.patch("addon_manager._SYSTEM_TEMP_ROOTS", frozenset({tmp_path.resolve()})):
            assert _manager().find_addon_archive([tmp_path]) == [archive.resolve()]


# ---------------------------------------------------------------------------
# list_addon_backups
# ---------------------------------------------------------------------------


class TestListAddonBackups:
    def test_no_backup_dir(self, tmp_path: Path):
        assert _manager().list_addon_backups(tmp_path / "p") == []

    def test_parses_backup_metadata(self, tmp_path: Path):
        product = tmp_path / "p"
        product.mkdir()
        backup_dir = tmp_path / "backups" / "addons"
        backup_dir.mkdir(parents=True)
        f = backup_dir / "p_MyAddon_addon_20240101_120000.tar.gz"
        f.write_bytes(b"data" * 100)

        backups = _manager().list_addon_backups(product)

        assert len(backups) == 1
        assert backups[0]["addon_name"] == "MyAddon"
        assert backups[0]["timestamp"].year == 2024
        assert backups[0]["size_mb"] > 0

    def test_bad_timestamp_falls_back_to_mtime(self, tmp_path: Path):
        product = tmp_path / "p"
        product.mkdir()
        backup_dir = tmp_path / "backups" / "addons"
        backup_dir.mkdir(parents=True)
        (backup_dir / "p_X_addon_notadate.tar.gz").write_bytes(b"z")

        backups = _manager().list_addon_backups(product)

        assert len(backups) == 1
        assert backups[0]["addon_name"] == "X"

    def test_nonmatching_files_ignored(self, tmp_path: Path):
        product = tmp_path / "p"
        product.mkdir()
        backup_dir = tmp_path / "backups" / "addons"
        backup_dir.mkdir(parents=True)
        (backup_dir / "other_X_addon_20240101_120000.tar.gz").write_bytes(b"z")

        assert _manager().list_addon_backups(product) == []


# ---------------------------------------------------------------------------
# install_addon edge cases
# ---------------------------------------------------------------------------


class TestInstallAddonEdge:
    def test_race_after_permissions_rejected(self, tmp_path: Path):
        manager = _manager()
        product = tmp_path / "product"
        archive = tmp_path / "Example.zip"
        import zipfile

        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("Example/index.js", "x")

        addons = product / "addons"

        def create_conflict(*args, **kwargs):
            (addons / "Example").mkdir(parents=True)

        with mock.patch.object(manager, "_set_permissions", side_effect=create_conflict):
            ok, msg, name = manager.install_addon(archive, product)

        assert ok is False
        assert "already exists" in msg
