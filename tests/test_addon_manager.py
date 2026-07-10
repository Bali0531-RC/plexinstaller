"""Security and transactional tests for addon_manager.py."""

import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from addon_manager import AddonManager


def test_install_single_folder_zip(tmp_path: Path):
    manager = AddonManager()
    product = tmp_path / "product"
    archive = tmp_path / "Stats.zip"
    with zipfile.ZipFile(archive, "w") as zip_ref:
        zip_ref.writestr("Stats/index.js", "module.exports = {};")
        zip_ref.writestr("Stats/config.yml", "enabled: true\n")

    success, message, name = manager.install_addon(archive, product)

    assert success is True
    assert name == "Stats"
    assert "config.yml" in message
    assert (product / "addons" / "Stats" / "index.js").exists()


def test_install_loose_tar_normalizes_archive_name(tmp_path: Path):
    manager = AddonManager()
    product = tmp_path / "product"
    archive = tmp_path / "TicketStats-main.tar.gz"
    payload = tmp_path / "index.js"
    payload.write_text("module.exports = {};")
    with tarfile.open(archive, "w:gz") as tar_ref:
        tar_ref.add(payload, arcname="index.js")

    success, _message, name = manager.install_addon(archive, product)

    assert success is True
    assert name == "TicketStats"
    assert (product / "addons" / "TicketStats" / "index.js").exists()


def test_install_collision_never_overwrites_existing_addon(tmp_path: Path):
    manager = AddonManager()
    product = tmp_path / "product"
    installed = product / "addons" / "Stats"
    installed.mkdir(parents=True)
    (installed / "index.js").write_text("original")
    archive = tmp_path / "Stats.zip"
    with zipfile.ZipFile(archive, "w") as zip_ref:
        zip_ref.writestr("Stats/index.js", "replacement")
        zip_ref.writestr("Stats/new.js", "new")

    success, message, name = manager.install_addon(archive, product)

    assert success is False
    assert "already exists" in message
    assert name is None
    assert (installed / "index.js").read_text() == "original"
    assert not (installed / "new.js").exists()


def test_install_rejects_traversal_without_partial_files(tmp_path: Path):
    manager = AddonManager()
    product = tmp_path / "product"
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zip_ref:
        zip_ref.writestr("../escape.txt", "bad")

    success, message, name = manager.install_addon(archive, product)

    assert success is False
    assert "traversal" in message.lower()
    assert name is None
    assert not (tmp_path / "escape.txt").exists()
    assert not (product / "addons").exists()


def test_find_addon_archive_explicit_dirs_supports_zip_tar_and_rar(tmp_path: Path):
    manager = AddonManager()
    nested = tmp_path / "nested"
    nested.mkdir()
    expected = [tmp_path / "one.zip", nested / "two.tar.gz", nested / "three.rar"]
    for path in expected:
        path.write_bytes(b"archive")
    (nested / "ignore.txt").write_text("not an archive")

    found = manager.find_addon_archive([tmp_path, tmp_path])

    assert set(found) == {path.resolve() for path in expected}


def test_default_archive_search_is_shallow_and_avoids_temp(tmp_path: Path):
    manager = AddonManager()
    home = tmp_path / "home"
    downloads = home / "Downloads"
    desktop = home / "Desktop"
    cwd = tmp_path / "cwd"
    for directory in (downloads, desktop, cwd):
        directory.mkdir(parents=True)
    direct = downloads / "direct.zip"
    direct.write_bytes(b"zip")
    nested = downloads / "nested"
    nested.mkdir()
    (nested / "hidden.zip").write_bytes(b"zip")

    with (
        mock.patch("addon_manager._automatic_temp_roots", return_value=()),
        mock.patch("addon_manager.Path.home", return_value=home),
        mock.patch("addon_manager.Path.cwd", return_value=cwd),
    ):
        found = manager.find_addon_archive()

    assert direct.resolve() in found
    assert (nested / "hidden.zip").resolve() not in found


def test_addon_backup_timestamp_parsing_uses_full_tar_gz_suffix(tmp_path: Path):
    manager = AddonManager()
    product = tmp_path / "product_with_name"
    backup_dir = product.parent / "backups" / "addons"
    backup_dir.mkdir(parents=True)
    backup = backup_dir / "product_with_name_stats_addon_extra_addon_20260710_123456.tar.gz"
    backup.write_bytes(b"data")

    results = manager.list_addon_backups(product)

    assert len(results) == 1
    assert results[0]["addon_name"] == "stats_addon_extra"
    assert results[0]["timestamp"] == datetime(2026, 7, 10, 12, 34, 56)
