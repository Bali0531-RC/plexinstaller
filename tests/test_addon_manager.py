"""Security and transactional-install tests for addon_manager.py."""

import tarfile
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest

from addon_manager import AddonManager


def _write_zip(path: Path, members: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


class TestInstallAddon:
    def test_installs_single_directory_atomically(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        archive = tmp_path / "Example.zip"
        _write_zip(archive, {"Example/index.js": "module.exports = {};", "Example/config.yml": "enabled: true\n"})

        with mock.patch.object(manager, "_set_permissions"):
            success, message, name = manager.install_addon(archive, product)

        assert success is True
        assert name == "Example"
        assert "config.yml" in message
        assert (product / "addons" / "Example" / "index.js").exists()

    def test_wraps_loose_files_using_archive_name(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        archive = tmp_path / "Stats-main.zip"
        _write_zip(archive, {"index.js": "content", "config.yml": "enabled: true\n"})

        with mock.patch.object(manager, "_set_permissions"):
            success, _, name = manager.install_addon(archive, product)

        assert success is True
        assert name == "Stats"
        assert (product / "addons" / "Stats" / "index.js").read_text() == "content"

    def test_never_overwrites_existing_addon(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        existing = product / "addons" / "Example"
        existing.mkdir(parents=True)
        (existing / "index.js").write_text("original")
        archive = tmp_path / "replacement.zip"
        _write_zip(archive, {"Example/index.js": "replacement"})

        with mock.patch.object(manager, "_set_permissions"):
            success, message, name = manager.install_addon(archive, product)

        assert success is False
        assert "already exists" in message
        assert name is None
        assert (existing / "index.js").read_text() == "original"

    def test_malicious_archive_does_not_touch_addons(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        existing = product / "addons" / "Existing"
        existing.mkdir(parents=True)
        (existing / "keep.txt").write_text("keep")
        archive = tmp_path / "evil.zip"
        _write_zip(archive, {"../../outside": "owned"})

        success, message, name = manager.install_addon(archive, product)

        assert success is False
        assert "Path traversal" in message
        assert name is None
        assert (existing / "keep.txt").read_text() == "keep"
        assert not (tmp_path / "outside").exists()

    def test_permission_failure_leaves_no_addon(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        archive = tmp_path / "Example.zip"
        _write_zip(archive, {"Example/index.js": "content"})

        with mock.patch.object(manager, "_set_permissions", side_effect=RuntimeError("chmod failed")):
            success, _, name = manager.install_addon(archive, product)

        assert success is False
        assert name is None
        assert not (product / "addons" / "Example").exists()

    def test_supports_safe_tar_archive(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        archive = tmp_path / "Example.tar.gz"
        data = b"content"
        member = tarfile.TarInfo("Example/index.js")
        member.size = len(data)
        with tarfile.open(archive, "w:gz") as tf:
            tf.addfile(member, BytesIO(data))

        with mock.patch.object(manager, "_set_permissions"):
            success, _, name = manager.install_addon(archive, product)

        assert success is True
        assert name == "Example"


class TestAddonNameValidation:
    @pytest.mark.parametrize("name", ["", ".", "..", "../escape", "nested/addon", r"nested\\addon", "/absolute"])
    @pytest.mark.parametrize(
        "method",
        ["addon_exists", "backup_addon", "remove_addon", "get_addon_config_path"],
    )
    def test_public_path_methods_reject_invalid_names(self, tmp_path: Path, method: str, name: str):
        manager = AddonManager()

        with pytest.raises(ValueError, match="Invalid addon name"):
            getattr(manager, method)(name, tmp_path / "product")

    def test_backup_is_private(self, tmp_path: Path):
        manager = AddonManager()
        product = tmp_path / "product"
        addon = product / "addons" / "Example"
        addon.mkdir(parents=True)
        (addon / "config.yml").write_text("secret: value\n")

        success, _, backup = manager.backup_addon("Example", product)

        assert success is True
        assert backup is not None
        assert backup.stat().st_mode & 0o777 == 0o600


def test_find_addon_archive_discovers_zip_and_tar_only(tmp_path: Path):
    manager = AddonManager()
    zip_archive = tmp_path / "one.zip"
    tar_archive = tmp_path / "two.tar.gz"
    rar_archive = tmp_path / "unsafe.rar"
    for archive in (zip_archive, tar_archive, rar_archive):
        archive.touch()

    found = manager.find_addon_archive([tmp_path])

    assert zip_archive.resolve() in found
    assert tar_archive.resolve() in found
    assert rar_archive.resolve() not in found
