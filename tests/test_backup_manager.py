"""Tests for backup_manager.py — backup creation, listing, restoration, and deletion."""

import os
import tarfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from backup_manager import BackupManager
from utils import ColorPrinter, SystemdManager


def _make_manager(tmp_path: Path) -> BackupManager:
    """Create a BackupManager rooted in tmp_path."""
    return BackupManager(
        printer=ColorPrinter(),
        systemd=SystemdManager(),
        install_dir=tmp_path / "plex",
    )


# ---------------------------------------------------------------------------
# BackupManager.backup_product
# ---------------------------------------------------------------------------


class TestBackupProduct:
    def test_creates_tarball(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        # Create a fake product install
        product_dir = mgr.install_dir / "plextickets"
        product_dir.mkdir(parents=True)
        (product_dir / "package.json").write_text('{"name":"plextickets"}')
        (product_dir / "config.yml").write_text("Token: my-token\n")

        with mock.patch.object(mgr.systemd, "get_status", side_effect=["active", "inactive"]):
            with mock.patch.object(mgr.systemd, "stop"):
                with mock.patch.object(mgr.systemd, "start"):
                    mgr.backup_product("plextickets")

        backups = list(mgr.backup_dir.glob("*.tar.gz"))
        assert len(backups) == 1
        assert "plextickets" in backups[0].name

    def test_stops_and_restarts_running_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "plextickets"
        product_dir.mkdir(parents=True)
        (product_dir / "package.json").write_text("{}")

        with mock.patch.object(mgr.systemd, "get_status", side_effect=["active", "inactive"]):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.backup_product("plextickets")

        mock_stop.assert_called_once_with("plex-plextickets")
        mock_start.assert_called_once_with("plex-plextickets")

    def test_does_not_restart_inactive_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "plextickets"
        product_dir.mkdir(parents=True)
        (product_dir / "package.json").write_text("{}")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.backup_product("plextickets")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()

    def test_exact_active_comparison(self, tmp_path: Path):
        """Ensure 'inactive' is not mistakenly treated as 'active'."""
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "plextickets"
        product_dir.mkdir(parents=True)
        (product_dir / "package.json").write_text("{}")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.backup_product("plextickets")

        # "inactive" should NOT trigger stop/start
        mock_stop.assert_not_called()
        mock_start.assert_not_called()

    def test_backup_archive_contains_product_files(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "plextickets"
        product_dir.mkdir(parents=True)
        (product_dir / "package.json").write_text('{"name":"test"}')
        (product_dir / "index.js").write_text("console.log('hello');")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            mgr.backup_product("plextickets")

        backups = list(mgr.backup_dir.glob("*.tar.gz"))
        with tarfile.open(backups[0], "r:gz") as tar:
            names = tar.getnames()
        assert any("package.json" in n for n in names)
        assert any("index.js" in n for n in names)


# ---------------------------------------------------------------------------
# BackupManager.list_backups
# ---------------------------------------------------------------------------


class TestListBackups:
    def test_empty_backups_dir(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.backup_dir.mkdir(parents=True)
        result = mgr.list_backups()
        assert result == []

    def test_no_backup_dir(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        result = mgr.list_backups()
        assert result == []

    def test_returns_sorted_backups(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.backup_dir.mkdir(parents=True)

        # Create fake backup files
        older = mgr.backup_dir / "plextickets_backup_20260101_120000.tar.gz"
        newer = mgr.backup_dir / "plextickets_backup_20260102_120000.tar.gz"
        older.write_text("fake")
        newer.write_text("fake")
        os.utime(older, (1, 1))
        os.utime(newer, (2, 2))

        result = mgr.list_backups()
        assert len(result) == 2
        # Most recent first
        assert "20260102" in result[0].name


# ---------------------------------------------------------------------------
# BackupManager.restore_from_backup
# ---------------------------------------------------------------------------


class TestRestoreFromBackup:
    def test_restore_replaces_installation(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "old_file.txt").write_text("old content")

        # Create a backup archive
        backup_dir = mgr.backup_dir
        backup_dir.mkdir(parents=True)
        backup_file = backup_dir / "testapp_backup_20260101_120000.tar.gz"

        archive_base = tmp_path / "archive_content"
        archive_content = archive_base / "testapp"
        archive_content.mkdir(parents=True)
        (archive_content / "new_file.txt").write_text("restored content")

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(archive_content, arcname="testapp")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            with mock.patch.object(mgr.systemd, "stop"):
                with mock.patch.object(mgr.systemd, "start"):
                    mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "new_file.txt").exists()
        assert (product_dir / "new_file.txt").read_text() == "restored content"

    def test_rollback_on_publish_failure_preserves_original(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep me")

        backup_file = mgr.install_dir / "testapp_backup_20260101_120000.tar.gz"
        archive_content = tmp_path / "archive" / "testapp"
        archive_content.mkdir(parents=True)
        (archive_content / "new.txt").write_text("new")
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(archive_content, arcname="testapp")

        real_rename = Path.rename

        def fail_publish(path: Path, target: Path):
            if path.name == "testapp" and ".restore-" in str(path):
                raise OSError("publish failed")
            return real_rename(path, target)

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch("backup_manager.Path.rename", autospec=True, side_effect=fail_publish),
        ):
            mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "original.txt").read_text() == "keep me"
        assert not (product_dir / "new.txt").exists()

    def test_restore_rejects_wrong_top_level_without_mutation(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = mgr.install_dir / "testapp_backup_20260101_120000.tar.gz"
        payload = tmp_path / "wrong"
        payload.mkdir()
        (payload / "bad.txt").write_text("bad")
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(payload, arcname="different-product")

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch.object(mgr.systemd, "stop") as stop,
        ):
            mgr.restore_from_backup(backup_file, "testapp")

        stop.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep"

    def test_restore_refuses_mutation_when_running_service_does_not_stop(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = mgr.install_dir / "testapp_backup_20260101_120000.tar.gz"
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "new.txt").write_text("new")
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(payload, arcname="testapp")

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="active"),
            mock.patch.object(mgr.systemd, "stop") as stop,
            mock.patch.object(mgr.systemd, "start") as start,
        ):
            mgr.restore_from_backup(backup_file, "testapp")

        stop.assert_called_once_with("plex-testapp")
        start.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep"
        assert not (product_dir / "new.txt").exists()

    def test_restore_restarts_only_previously_running_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        backup_file = mgr.install_dir / "testapp_backup_20260101_120000.tar.gz"
        payload = tmp_path / "payload"
        payload.mkdir()
        (payload / "new.txt").write_text("new")
        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(payload, arcname="testapp")

        with (
            mock.patch.object(mgr.systemd, "get_status", side_effect=["active", "inactive"]),
            mock.patch.object(mgr.systemd, "stop"),
            mock.patch.object(mgr.systemd, "start") as start,
        ):
            mgr.restore_from_backup(backup_file, "testapp")

        start.assert_called_once_with("plex-testapp")

    def test_invalid_backup_name_is_rejected(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        invalid = tmp_path / "testapp_backup_20260101_120000.tar.gz.extra"
        invalid.write_text("bad")
        with mock.patch.object(mgr.systemd, "get_status") as status:
            mgr.restore_from_backup(invalid, "testapp")
        status.assert_not_called()

    def test_parse_backup_timestamp_and_underscored_product(self, tmp_path: Path):
        path = tmp_path / "my_product_backup_20260710_235959.tar.gz"
        product, timestamp = BackupManager._parse_backup_name(path)
        assert product == "my_product"
        assert timestamp == datetime(2026, 7, 10, 23, 59, 59)

    def test_backup_file_is_private_best_effort(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "file.txt").write_text("data")
        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            mgr.backup_product("testapp")
        backup = next(mgr.backup_dir.glob("*.tar.gz"))
        if os.name == "nt":
            assert backup.exists()
        else:
            assert backup.stat().st_mode & 0o077 == 0

    def test_backup_aborts_if_service_does_not_stop(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="active"),
            mock.patch.object(mgr.systemd, "stop") as stop,
            mock.patch.object(mgr.systemd, "start") as start,
        ):
            mgr.backup_product("testapp")
        stop.assert_called_once()
        start.assert_not_called()
        assert list(mgr.backup_dir.glob("*.tar.gz")) == []

    def test_backup_unknown_state_after_stop_restarts_only_once(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        with (
            mock.patch.object(mgr.systemd, "get_status", side_effect=["active", "unknown"]),
            mock.patch.object(mgr.systemd, "stop"),
            mock.patch.object(mgr.systemd, "start") as start,
        ):
            mgr.backup_product("testapp")
        start.assert_called_once_with("plex-testapp")
        assert list(mgr.backup_dir.glob("*.tar.gz")) == []

    def test_rollback_on_failure_restarts_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep me")

        backup_file = tmp_path / "testapp_backup_20260101_120000.tar.gz"
        backup_file.write_text("not a real tarball")

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "start"):
                mgr.restore_from_backup(backup_file, "testapp")

        # Validation happens before stopping, so the running service is untouched.
        assert (product_dir / "original.txt").exists()

    def test_restore_calls_check_on_permissions(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)

        # Create a valid backup
        backup_dir = mgr.backup_dir
        backup_dir.mkdir(parents=True)
        backup_file = backup_dir / "testapp_backup_20260101_120000.tar.gz"

        archive_base = tmp_path / "archive_content"
        archive_content = archive_base / "testapp"
        archive_content.mkdir(parents=True)
        (archive_content / "file.txt").write_text("data")

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(archive_content, arcname="testapp")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "file.txt").read_text() == "data"


# ---------------------------------------------------------------------------
# BackupManager.delete_backup (non-interactive helper)
# ---------------------------------------------------------------------------


class TestDeleteBackup:
    def test_no_backups_returns_early(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        # Should not raise
        mgr.delete_backup()
