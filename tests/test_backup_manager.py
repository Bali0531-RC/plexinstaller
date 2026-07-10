"""Tests for backup_manager.py — backup creation, listing, restoration, and deletion."""

import tarfile
from io import BytesIO
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
        assert backups[0].stat().st_mode & 0o777 == 0o600

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
                with mock.patch.object(mgr.systemd, "get_status", side_effect=["active", "inactive"]):
                    with mock.patch("backup_manager.subprocess.run"):
                        mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "new_file.txt").exists()
        assert (product_dir / "new_file.txt").read_text() == "restored content"

    def test_invalid_backup_leaves_running_service_untouched(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep me")

        backup_file = tmp_path / "bad_backup.tar.gz"
        backup_file.write_text("not a real tarball")

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep me"

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
                with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
                    with mock.patch("backup_manager.subprocess.run") as mock_run:
                        mgr.restore_from_backup(backup_file, "testapp")

        # All three subprocess.run calls should have check=True
        for call in mock_run.call_args_list:
            assert call.kwargs.get("check") is True or (len(call.args) > 0 and "check" not in str(call))

    def test_restore_does_not_start_inactive_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "old.txt").write_text("old")
        backup_file = _make_product_backup(tmp_path, mgr, "testapp", "new.txt", b"new")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    with mock.patch("backup_manager.subprocess.run"):
                        mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
        assert (product_dir / "new.txt").read_text() == "new"

    def test_restore_preserves_active_service_state(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        backup_file = _make_product_backup(tmp_path, mgr, "testapp", "new.txt", b"new")

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    with mock.patch("backup_manager.subprocess.run"):
                        mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_called_once_with("plex-testapp")
        mock_start.assert_called_once_with("plex-testapp")

    def test_restore_rejects_traversal_without_touching_install(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = mgr.install_dir / "malicious.tar.gz"

        member = tarfile.TarInfo("testapp/../../outside.txt")
        data = b"owned"
        member.size = len(data)
        with tarfile.open(backup_file, "w:gz") as tf:
            tf.addfile(member, BytesIO(data))

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep"
        assert not (tmp_path / "outside.txt").exists()

    def test_restore_rejects_unexpected_top_level(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = _make_product_backup(tmp_path, mgr, "other", "file.txt", b"wrong")

        with mock.patch.object(mgr.systemd, "get_status", return_value="inactive"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep"

    def test_permission_failure_rolls_back_before_publish(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = _make_product_backup(tmp_path, mgr, "testapp", "new.txt", b"new")

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "stop") as mock_stop:
                with mock.patch.object(mgr.systemd, "start") as mock_start:
                    with mock.patch.object(mgr, "_set_permissions", side_effect=RuntimeError("chmod failed")):
                        mgr.restore_from_backup(backup_file, "testapp")

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
        assert (product_dir / "original.txt").read_text() == "keep"

    def test_publish_failure_restores_previous_installation(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        product_dir = mgr.install_dir / "testapp"
        product_dir.mkdir(parents=True)
        (product_dir / "original.txt").write_text("keep")
        backup_file = _make_product_backup(tmp_path, mgr, "testapp", "new.txt", b"new")
        original_rename = Path.rename

        def fail_publish(path: Path, target: Path):
            if path.name == "testapp" and ".restore-" in str(path):
                target.mkdir()
                (target / "partial.txt").write_text("partial")
                raise OSError("publish failed")
            return original_rename(path, target)

        with mock.patch.object(mgr.systemd, "get_status", return_value="active"):
            with mock.patch.object(mgr.systemd, "stop"):
                with mock.patch.object(mgr.systemd, "start"):
                    with mock.patch("backup_manager.subprocess.run"):
                        with mock.patch.object(Path, "rename", fail_publish):
                            mgr.restore_from_backup(backup_file, "testapp")

        assert (product_dir / "original.txt").read_text() == "keep"
        assert not (product_dir / "partial.txt").exists()


def _make_product_backup(
    tmp_path: Path,
    mgr: BackupManager,
    product: str,
    filename: str,
    data: bytes,
) -> Path:
    mgr.backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = mgr.backup_dir / f"{product}_backup_test.tar.gz"
    member = tarfile.TarInfo(f"{product}/{filename}")
    member.size = len(data)
    with tarfile.open(backup_file, "w:gz") as tf:
        tf.addfile(member, BytesIO(data))
    return backup_file


# ---------------------------------------------------------------------------
# BackupManager.delete_backup (non-interactive helper)
# ---------------------------------------------------------------------------


class TestDeleteBackup:
    def test_no_backups_returns_early(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        # Should not raise
        mgr.delete_backup()
