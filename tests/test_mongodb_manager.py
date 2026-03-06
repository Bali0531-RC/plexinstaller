"""Tests for mongodb_manager.py — check_installed, credential saving, YAML patching, Arch install."""

import os
import subprocess
from pathlib import Path
from unittest import mock

from mongodb_manager import MongoDBManager
from utils import ColorPrinter, SystemDetector


def _make_manager(**overrides) -> MongoDBManager:
    system = SystemDetector()
    system.distribution = overrides.get("distro", "ubuntu")
    return MongoDBManager(
        printer=ColorPrinter(),
        system=system,
        mongodb_version=overrides.get("version", "8.0"),
        mongodb_repo_version_bookworm=overrides.get("bookworm_ver", "8.2"),
    )


# ---------------------------------------------------------------------------
# check_installed
# ---------------------------------------------------------------------------


class TestCheckInstalled:
    def test_returns_true_when_mongosh_found(self):
        mgr = _make_manager()
        result = subprocess.CompletedProcess(args=[], returncode=0, stdout="2.1.0\n")
        with mock.patch("mongodb_manager.subprocess.run", return_value=result):
            assert mgr.check_installed() is True

    def test_returns_true_when_only_mongo_found(self):
        """mongosh missing (FileNotFoundError) should fall back to mongo."""
        mgr = _make_manager()

        call_count = 0

        def side_effect(cmd, **kw):
            nonlocal call_count
            call_count += 1
            if cmd[0] == "mongosh":
                raise FileNotFoundError("mongosh")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="5.0.0\n")

        with mock.patch("mongodb_manager.subprocess.run", side_effect=side_effect):
            assert mgr.check_installed() is True
        assert call_count == 2  # tried mongosh then mongo

    def test_returns_false_when_neither_found(self):
        mgr = _make_manager()
        with mock.patch("mongodb_manager.subprocess.run", side_effect=FileNotFoundError("not found")):
            assert mgr.check_installed() is False

    def test_returns_false_on_timeout(self):
        mgr = _make_manager()
        with mock.patch("mongodb_manager.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 10)):
            assert mgr.check_installed() is False

    def test_returns_false_when_both_have_nonzero_exit(self):
        mgr = _make_manager()
        bad_result = subprocess.CompletedProcess(args=[], returncode=127, stdout="")
        with mock.patch("mongodb_manager.subprocess.run", return_value=bad_result):
            assert mgr.check_installed() is False


# ---------------------------------------------------------------------------
# save_credentials
# ---------------------------------------------------------------------------


class TestSaveCredentials:
    def test_creates_file_with_restrictive_permissions(self, tmp_path: Path):
        mgr = _make_manager()
        creds_dir = tmp_path / "etc" / "plex"

        creds = {
            "database": "plextickets",
            "username": "plex_user",
            "password": "s3cret",
            "uri": "mongodb://plex_user:s3cret@localhost:27017/plextickets",
        }

        with mock.patch("mongodb_manager.Path", side_effect=lambda p: tmp_path / p.lstrip("/")):
            # Directly call after setting up the path
            pass

        # Simpler approach: mock the os.open to verify mode
        original_open = os.open

        created_mode = None

        def tracking_open(path, flags, mode=0o777):
            nonlocal created_mode
            created_mode = mode
            return original_open(str(tmp_path / "creds_file"), flags, mode)

        creds_dir.mkdir(parents=True, exist_ok=True)

        with mock.patch("mongodb_manager.Path") as mock_path_cls:
            mock_creds_dir = mock.MagicMock()
            mock_path_cls.return_value = mock_creds_dir
            mock_creds_dir.__truediv__ = mock.MagicMock(return_value=tmp_path / "creds_file")
            mock_creds_dir.mkdir = mock.MagicMock()

            with mock.patch("mongodb_manager.os.open", side_effect=tracking_open):
                mgr.save_credentials("plextickets", creds)

        # Verify os.open was called with 0o600 mode
        assert created_mode == 0o600

    def test_appends_credentials_content(self, tmp_path: Path):
        mgr = _make_manager()
        creds_dir = tmp_path / "plex"
        creds_file = creds_dir / "mongodb_credentials"

        creds = {
            "database": "plextickets",
            "username": "plex_user",
            "password": "s3cret",
            "uri": "mongodb://plex_user:s3cret@localhost:27017/plextickets",
        }

        with mock.patch("mongodb_manager.Path", return_value=creds_dir):
            mgr.save_credentials("plextickets", creds)

        content = creds_file.read_text()
        assert "DATABASE=plextickets" in content
        assert "USERNAME=plex_user" in content
        assert "PASSWORD=s3cret" in content
        assert "URI=mongodb://plex_user:s3cret@localhost:27017/plextickets" in content


# ---------------------------------------------------------------------------
# update_config — YAML regex patching
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_patches_mongo_uri_in_yaml(self, tmp_path: Path):
        mgr = _make_manager()
        config_file = tmp_path / "config.yml"
        config_file.write_text('mongoURI: ""\nPort: 3000\n')

        creds = {"uri": "mongodb://user:pass@localhost:27017/db"}
        mgr.update_config(tmp_path, creds)

        content = config_file.read_text()
        assert "mongodb://user:pass@localhost:27017/db" in content
        assert "Port: 3000" in content

    def test_skips_commented_lines(self, tmp_path: Path):
        """Anchored regex should NOT match lines starting with #."""
        mgr = _make_manager()
        config_file = tmp_path / "config.yml"
        config_file.write_text('# mongoURI: old_value\nmongoURI: ""\n')

        creds = {"uri": "mongodb://user:pass@localhost:27017/db"}
        mgr.update_config(tmp_path, creds)

        content = config_file.read_text()
        lines = content.splitlines()
        # The comment line should remain unchanged
        assert lines[0] == "# mongoURI: old_value"
        # The actual config line should be updated
        assert "mongodb://user:pass@localhost:27017/db" in lines[1]

    def test_patches_mongodb_uri_variant(self, tmp_path: Path):
        mgr = _make_manager()
        config_file = tmp_path / "config.yml"
        config_file.write_text('mongodb_uri: ""\n')

        creds = {"uri": "mongodb://u:p@host/db"}
        mgr.update_config(tmp_path, creds)

        assert "mongodb://u:p@host/db" in config_file.read_text()

    def test_patches_database_url_variant(self, tmp_path: Path):
        mgr = _make_manager()
        config_file = tmp_path / "config.yml"
        config_file.write_text('database_url: ""\n')

        creds = {"uri": "mongodb://u:p@host/db"}
        mgr.update_config(tmp_path, creds)

        assert "mongodb://u:p@host/db" in config_file.read_text()

    def test_patches_json_config(self, tmp_path: Path):
        mgr = _make_manager()
        config_file = tmp_path / "config.json"
        config_file.write_text('{"mongoURI": "", "port": 3000}')

        creds = {"uri": "mongodb://u:p@host/db"}
        mgr.update_config(tmp_path, creds)

        import json

        data = json.loads(config_file.read_text())
        assert data["mongoURI"] == "mongodb://u:p@host/db"

    def test_no_config_files_logs_warning(self, tmp_path: Path, capsys):
        mgr = _make_manager()
        creds = {"uri": "mongodb://u:p@host/db"}
        mgr.update_config(tmp_path, creds)

        captured = capsys.readouterr()
        assert "No config" in captured.err or "not found" in captured.err.lower()


# ---------------------------------------------------------------------------
# _install_arch
# ---------------------------------------------------------------------------


class TestInstallArch:
    def test_errors_without_aur_helper(self, capsys):
        mgr = _make_manager(distro="arch")

        with mock.patch("mongodb_manager.shutil.which", return_value=None):
            result = mgr._install_arch()

        assert result is False
        captured = capsys.readouterr()
        assert "AUR" in captured.err

    def test_uses_yay_when_available(self):
        mgr = _make_manager(distro="arch")

        def mock_which(cmd):
            return "/usr/bin/yay" if cmd == "yay" else None

        with mock.patch("mongodb_manager.shutil.which", side_effect=mock_which):
            with mock.patch("mongodb_manager.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                result = mgr._install_arch()

        assert result is True
        first_call_args = mock_run.call_args_list[0].args[0]
        assert first_call_args[0] == "yay"

    def test_uses_paru_when_yay_missing(self):
        mgr = _make_manager(distro="arch")

        def mock_which(cmd):
            return "/usr/bin/paru" if cmd == "paru" else None

        with mock.patch("mongodb_manager.shutil.which", side_effect=mock_which):
            with mock.patch("mongodb_manager.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                result = mgr._install_arch()

        assert result is True
        first_call_args = mock_run.call_args_list[0].args[0]
        assert first_call_args[0] == "paru"

    def test_prefers_yay_over_paru(self):
        mgr = _make_manager(distro="arch")

        def mock_which(cmd):
            if cmd in ("yay", "paru"):
                return f"/usr/bin/{cmd}"
            return None

        with mock.patch("mongodb_manager.shutil.which", side_effect=mock_which):
            with mock.patch("mongodb_manager.subprocess.run") as mock_run:
                mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
                mgr._install_arch()

        first_call_args = mock_run.call_args_list[0].args[0]
        assert first_call_args[0] == "yay"
