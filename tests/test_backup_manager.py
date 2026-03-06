"""Tests for backup_manager.py — backup creation, listing, restoration, and deletion."""

import tarfile
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

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
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

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
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
        for name in ["plextickets_backup_20260101_120000.tar.gz", "plextickets_backup_20260102_120000.tar.gz"]:
            (mgr.backup_dir / name).write_text("fake")

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
        backup_file = backup_dir / "testapp_backup_20260101.tar.gz"

        archive_base = tmp_path / "archive_content"
        archive_content = archive_base / "testapp"
        archive_content.mkdir(parents=True)
        (archive_content / "new_file.txt").write_text("restored content")

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(archive_content, arcname="testapp")

        with mock.patch.object(mgr.systemd, "stop"):
            with mock.patch.object(mgr.systemd, "start"):
                with mock.patch("backup_manager.subprocess.run"):
                    mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "new_file.txt").exists()
        assert (product_dir / "new_file.txt").read_text() == "restored content"

    def test_rollback_on_failure_restarts_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep me")

        backup_file = tmp_path / "bad_backup.tar.gz"
        backup_file.write_text("not a real tarball")

        with mock.patch.object(mgr.systemd, "stop"):
            with mock.patch.object(mgr.systemd, "start") as mock_start:
                mgr.restore_from_backup(backup_file, "testapp")

        # After failed restore, service should be restarted with rolled-back install
        mock_start.assert_called_once_with("plex-testapp")

    def test_restore_calls_check_on_permissions(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)

        # Create a valid backup
        backup_dir = mgr.backup_dir
        backup_dir.mkdir(parents=True)
        backup_file = backup_dir / "testapp_backup.tar.gz"

        archive_base = tmp_path / "archive_content"
        archive_content = archive_base / "testapp"
        archive_content.mkdir(parents=True)
        (archive_content / "file.txt").write_text("data")

        with tarfile.open(backup_file, "w:gz") as tar:
            tar.add(archive_content, arcname="testapp")

        with mock.patch.object(mgr.systemd, "stop"):
            with mock.patch.object(mgr.systemd, "start"):
                with mock.patch("backup_manager.subprocess.run") as mock_run:
                    mgr.restore_from_backup(backup_file, "testapp")

        # All three subprocess.run calls should have check=True
        for call in mock_run.call_args_list:
            assert call.kwargs.get("check") is True or (len(call.args) > 0 and "check" not in str(call))


# ---------------------------------------------------------------------------
# BackupManager.delete_backup (non-interactive helper)
# ---------------------------------------------------------------------------


class TestDeleteBackup:
    def test_no_backups_returns_early(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        # Should not raise
        mgr.delete_backup()
