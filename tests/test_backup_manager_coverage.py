"""Additional coverage tests for backup_manager.py."""

import json
import subprocess
import tarfile
from pathlib import Path
from unittest import mock

import pytest

from backup_manager import BackupManager
from utils import ColorPrinter, SystemdManager


def _make_manager(tmp_path: Path) -> BackupManager:
    return BackupManager(
        printer=ColorPrinter(),
        systemd=SystemdManager(),
        install_dir=tmp_path / "plex",
    )


def _make_backup(mgr: BackupManager, product: str = "plextickets", content: str = "{}") -> Path:
    product_dir = mgr.install_dir / product
    product_dir.mkdir(parents=True, exist_ok=True)
    (product_dir / "package.json").write_text(content)
    mgr.backup_dir.mkdir(exist_ok=True)
    backup_file = mgr.backup_dir / f"{product}_backup_20240101_120000.tar.gz"
    with tarfile.open(backup_file, "w:gz") as tar:
        tar.add(product_dir, arcname=product)
    return backup_file


# ---------------------------------------------------------------------------
# menu
# ---------------------------------------------------------------------------


class TestMenu:
    def _run_menu(self, mgr, inputs):
        with mock.patch("backup_manager.os.system"), mock.patch("builtins.input", side_effect=inputs):
            mgr.menu()

    def test_exit_immediately(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        self._run_menu(mgr, ["0"])

    def test_each_option_dispatches(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        with (
            mock.patch.object(mgr, "create_backup") as c,
            mock.patch.object(mgr, "list_backups") as ls,
            mock.patch.object(mgr, "restore_backup") as r,
            mock.patch.object(mgr, "delete_backup") as d,
        ):
            self._run_menu(mgr, ["1", "", "2", "", "3", "", "4", "", "0"])
        c.assert_called_once()
        ls.assert_called_once()
        r.assert_called_once()
        d.assert_called_once()

    def test_invalid_choice(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        with mock.patch.object(mgr.printer, "error") as err:
            self._run_menu(mgr, ["99", "", "0"])
        err.assert_called_once_with("Invalid choice")


# ---------------------------------------------------------------------------
# create_backup
# ---------------------------------------------------------------------------


class TestCreateBackup:
    def test_no_products(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.install_dir.mkdir(parents=True)
        with mock.patch.object(mgr.printer, "warning") as warn:
            mgr.create_backup()
        warn.assert_called_once()

    def test_valid_selection(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        (mgr.install_dir / "plextickets").mkdir(parents=True)
        (mgr.install_dir / "backups").mkdir()
        with mock.patch("builtins.input", return_value="1"), mock.patch.object(mgr, "backup_product") as bp:
            mgr.create_backup()
        bp.assert_called_once_with("plextickets")

    def test_out_of_range(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        (mgr.install_dir / "plextickets").mkdir(parents=True)
        with mock.patch("builtins.input", return_value="5"), mock.patch.object(mgr.printer, "error") as err:
            mgr.create_backup()
        err.assert_called_once_with("Invalid choice")

    def test_non_numeric(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        (mgr.install_dir / "plextickets").mkdir(parents=True)
        with mock.patch("builtins.input", return_value="abc"), mock.patch.object(mgr.printer, "error") as err:
            mgr.create_backup()
        err.assert_called_once_with("Invalid choice")


# ---------------------------------------------------------------------------
# backup_product failure path
# ---------------------------------------------------------------------------


class TestBackupProductFailure:
    def test_tar_failure_cleans_up_and_restarts(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        (mgr.install_dir / "p").mkdir(parents=True)
        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="active"),
            mock.patch.object(mgr.systemd, "stop"),
            mock.patch.object(mgr.systemd, "start") as start,
            mock.patch("backup_manager.tarfile.open", side_effect=OSError("disk full")),
            mock.patch.object(mgr.printer, "error") as err,
        ):
            mgr.backup_product("p")
        start.assert_called_once_with("plex-p")
        err.assert_called_once()
        assert list(mgr.backup_dir.glob("*.tar.gz")) == []


# ---------------------------------------------------------------------------
# restore_backup (interactive)
# ---------------------------------------------------------------------------


class TestRestoreBackupInteractive:
    def test_no_backup_dir(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        with mock.patch.object(mgr.printer, "warning") as warn:
            mgr.restore_backup()
        warn.assert_called_once_with("No backups directory found")

    def test_empty_backup_dir(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.backup_dir.mkdir(parents=True)
        with mock.patch.object(mgr.printer, "warning") as warn:
            mgr.restore_backup()
        warn.assert_called_once_with("No backups found")

    def test_confirmed_restore(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr)
        with mock.patch("builtins.input", side_effect=["1", "y"]), mock.patch.object(mgr, "restore_from_backup") as rfb:
            mgr.restore_backup()
        rfb.assert_called_once_with(backup, "plextickets")

    def test_declined_restore(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        _make_backup(mgr)
        with (
            mock.patch("builtins.input", side_effect=["1", "n"]),
            mock.patch.object(mgr, "restore_from_backup") as rfb,
            mock.patch.object(mgr.printer, "step") as step,
        ):
            mgr.restore_backup()
        rfb.assert_not_called()
        step.assert_called_with("Restore cancelled")

    def test_invalid_id(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        _make_backup(mgr)
        with mock.patch("builtins.input", return_value="99"), mock.patch.object(mgr.printer, "error") as err:
            mgr.restore_backup()
        err.assert_called_once_with("Invalid backup ID")

    def test_non_numeric_id(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        _make_backup(mgr)
        with mock.patch("builtins.input", return_value="x"), mock.patch.object(mgr.printer, "error") as err:
            mgr.restore_backup()
        err.assert_called_once_with("Invalid input")


# ---------------------------------------------------------------------------
# restore_from_backup
# ---------------------------------------------------------------------------


class TestRestoreFromBackup:
    def test_successful_restore_replaces_existing(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr, content='{"v": 1}')
        install_path = mgr.install_dir / "plextickets"
        (install_path / "package.json").write_text('{"v": 2}')

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch.object(mgr, "_set_permissions"),
        ):
            mgr.restore_from_backup(backup, "plextickets")

        assert (install_path / "package.json").read_text() == '{"v": 1}'
        assert not list(mgr.install_dir.glob(".plextickets.rollback-*"))

    def test_stops_and_restarts_running_service(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr)
        statuses = iter(["active", "inactive"])
        with (
            mock.patch.object(mgr.systemd, "get_status", side_effect=lambda _n: next(statuses)),
            mock.patch.object(mgr.systemd, "stop") as stop,
            mock.patch.object(mgr.systemd, "start") as start,
            mock.patch.object(mgr, "_set_permissions"),
        ):
            mgr.restore_from_backup(backup, "plextickets")
        stop.assert_called_once()
        start.assert_called_once()

    def test_service_refuses_to_stop_aborts(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr, content='{"v": 1}')
        install_path = mgr.install_dir / "plextickets"
        (install_path / "package.json").write_text('{"v": 2}')

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="active"),
            mock.patch.object(mgr.systemd, "stop"),
            mock.patch.object(mgr.systemd, "start") as start,
            mock.patch.object(mgr, "_set_permissions"),
            mock.patch.object(mgr.printer, "error") as err,
        ):
            mgr.restore_from_backup(backup, "plextickets")

        err.assert_called_once()
        start.assert_called_once()
        # Original install untouched
        assert (install_path / "package.json").read_text() == '{"v": 2}'

    def test_failure_rolls_back_previous_install(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr, content='{"v": 1}')
        install_path = mgr.install_dir / "plextickets"
        (install_path / "package.json").write_text('{"v": 2}')

        original_rename = Path.rename
        calls = {"n": 0}

        def flaky_rename(self, target):
            calls["n"] += 1
            if calls["n"] == 2:  # fail when publishing the staged product
                raise OSError("simulated publish failure")
            return original_rename(self, target)

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch.object(mgr, "_set_permissions"),
            mock.patch.object(Path, "rename", flaky_rename),
            mock.patch.object(mgr.printer, "error"),
        ):
            mgr.restore_from_backup(backup, "plextickets")

        # Original installation restored via rollback
        assert (install_path / "package.json").read_text() == '{"v": 2}'

    def test_failure_removes_published_new_install(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr)
        install_path = mgr.install_dir / "plextickets"
        import shutil

        shutil.rmtree(install_path)  # no previous install

        def fail_after_publish(path):
            raise OSError("rmtree of rollback not applicable")

        # Make the final success print raise to trigger the except with published install
        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch.object(mgr, "_set_permissions"),
            mock.patch.object(mgr.printer, "success", side_effect=RuntimeError("boom")),
            mock.patch.object(mgr.printer, "error"),
        ):
            mgr.restore_from_backup(backup, "plextickets")

        assert not install_path.exists()

    def test_extraction_failure_reports_error(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.install_dir.mkdir(parents=True)
        bad = mgr.backup_dir
        bad.mkdir()
        backup = bad / "plextickets_backup_20240101_120000.tar.gz"
        backup.write_bytes(b"not a tarball")

        with (
            mock.patch.object(mgr.systemd, "get_status", return_value="inactive"),
            mock.patch.object(mgr.printer, "error") as err,
        ):
            mgr.restore_from_backup(backup, "plextickets")
        err.assert_called_once()


# ---------------------------------------------------------------------------
# _product_from_backup_name
# ---------------------------------------------------------------------------


class TestProductFromBackupName:
    def test_valid(self):
        p = BackupManager._product_from_backup_name(Path("plexstaff_backup_20240101_120000.tar.gz"))
        assert p == "plexstaff"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Invalid backup filename"):
            BackupManager._product_from_backup_name(Path("random.tar.gz"))


# ---------------------------------------------------------------------------
# _set_permissions
# ---------------------------------------------------------------------------


class TestSetPermissions:
    def _run(self, install_path: Path) -> list:
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with mock.patch("backup_manager.subprocess.run", side_effect=fake_run):
            BackupManager._set_permissions(install_path)
        return calls

    def test_defaults_to_root(self, tmp_path: Path):
        install = tmp_path / "p"
        install.mkdir()
        (install / "config.yml").write_text("k: v")
        (install / "cert.pem").write_text("pem")
        (install / "run.sh").write_text("#!/bin/sh")
        (install / "notes.txt").write_text("hi")
        calls = self._run(install)
        assert "root:root" in calls[0]
        assert (install / "config.yml").stat().st_mode & 0o777 == 0o600
        assert (install / "cert.pem").stat().st_mode & 0o777 == 0o600
        assert (install / "run.sh").stat().st_mode & 0o777 == 0o750
        assert (install / "notes.txt").stat().st_mode & 0o777 == 0o640

    def test_isolated_owner_from_manifest(self, tmp_path: Path):
        install = tmp_path / "tickets"
        install.mkdir()
        user = SystemdManager.service_user_name("tickets")
        (install / ".plexinstaller-resources.json").write_text(
            json.dumps({"service_isolated": True, "service_user": user})
        )
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0)

        with (
            mock.patch("backup_manager.subprocess.run", side_effect=fake_run),
            mock.patch("backup_manager.pwd.getpwnam", return_value=object()),
        ):
            BackupManager._set_permissions(install)
        assert f"{user}:{user}" in calls[0]

    def test_invalid_manifest_falls_back_to_root(self, tmp_path: Path):
        install = tmp_path / "tickets"
        install.mkdir()
        (install / ".plexinstaller-resources.json").write_text("{broken")
        calls = self._run(install)
        assert "root:root" in calls[0]

    def test_skips_symlinked_files(self, tmp_path: Path):
        install = tmp_path / "p"
        install.mkdir()
        real = install / "real.txt"
        real.write_text("x")
        (install / "link.txt").symlink_to(real)
        self._run(install)
        assert (install / "real.txt").stat().st_mode & 0o777 == 0o640


# ---------------------------------------------------------------------------
# delete_backup
# ---------------------------------------------------------------------------


class TestDeleteBackup:
    def test_no_backup_dir(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        with mock.patch.object(mgr.printer, "warning") as warn:
            mgr.delete_backup()
        warn.assert_called_once_with("No backups directory found")

    def test_no_backups(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.backup_dir.mkdir(parents=True)
        with mock.patch.object(mgr.printer, "warning") as warn:
            mgr.delete_backup()
        warn.assert_called_once_with("No backups found")

    def test_confirmed_delete(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr)
        with mock.patch("builtins.input", side_effect=["1", "y"]):
            mgr.delete_backup()
        assert not backup.exists()

    def test_declined_delete(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        backup = _make_backup(mgr)
        with mock.patch("builtins.input", side_effect=["1", "n"]), mock.patch.object(mgr.printer, "step") as step:
            mgr.delete_backup()
        assert backup.exists()
        step.assert_called_with("Deletion cancelled")

    def test_invalid_id(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        _make_backup(mgr)
        with mock.patch("builtins.input", return_value="42"), mock.patch.object(mgr.printer, "error") as err:
            mgr.delete_backup()
        err.assert_called_once_with("Invalid backup ID")

    def test_non_numeric_id(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        _make_backup(mgr)
        with mock.patch("builtins.input", return_value="oops"), mock.patch.object(mgr.printer, "error") as err:
            mgr.delete_backup()
        err.assert_called_once_with("Invalid input")


# ---------------------------------------------------------------------------
# list_backups
# ---------------------------------------------------------------------------


class TestListBackups:
    def test_no_dir_returns_empty(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        assert mgr.list_backups() == []

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        mgr = _make_manager(tmp_path)
        mgr.backup_dir.mkdir(parents=True)
        assert mgr.list_backups() == []

    def test_lists_and_sorts(self, tmp_path: Path):
        import os

        mgr = _make_manager(tmp_path)
        old = _make_backup(mgr, "plextickets")
        newer = _make_backup(mgr, "plexstaff")
        os.utime(old, (1, 1))
        result = mgr.list_backups()
        assert result[0] == newer
        assert result[1] == old
