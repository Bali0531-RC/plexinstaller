"""Focused Windows installer lifecycle regressions."""

import json
import tarfile
from pathlib import Path
from unittest import mock

import pytest

import installer as installer_module
from addon_manager import AddonManager
from config import Config
from installer import InstallationContext, PlexInstaller, UserAbortError


def _installer(tmp_path: Path) -> PlexInstaller:
    instance = object.__new__(PlexInstaller)
    instance.config = Config()
    instance.config.install_dir = tmp_path / "apps"
    instance.config.nginx_available = tmp_path / "nginx" / "available"
    instance.config.nginx_enabled = tmp_path / "nginx" / "enabled"
    instance.printer = mock.MagicMock()
    instance.firewall = mock.MagicMock()
    instance.dns_checker = mock.MagicMock()
    instance.nginx = mock.MagicMock()
    instance.ssl = mock.MagicMock()
    instance.systemd = mock.MagicMock()
    instance.mongo_manager = mock.MagicMock()
    instance.addon_manager = AddonManager()
    return instance


def test_domain_setup_persists_port_and_opens_owned_firewall_rule(monkeypatch, tmp_path: Path):
    instance = _installer(tmp_path)
    install_path = instance.config.install_dir / "drakostore"
    install_path.mkdir(parents=True)
    (install_path / "config.yml").write_text("Port: 3003\n")
    instance.config.is_port_available = mock.MagicMock(return_value=True)
    instance.config.persist_app_port = mock.MagicMock()
    instance.dns_checker.check.return_value = True
    answers = iter(["3103", "store.example.com", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    context = InstallationContext("drakostore", "drakostore", install_path, 3003)

    domain, port, email = instance._setup_web("drakostore", 3003, install_path, context)

    assert (domain, port, email) == ("store.example.com", 3103, "admin@example.com")
    instance.config.persist_app_port.assert_called_once_with(install_path, 3103)
    instance.firewall.open_port.assert_called_once_with(3103, "drakostore")
    assert context.opened_port == 3103
    assert context.nginx_configured is True
    assert context.ssl_configured is True


def test_declined_legacy_multi_instance_preserves_existing_install(monkeypatch, tmp_path: Path):
    instance = _installer(tmp_path)
    legacy = instance.config.install_dir / "plexstore_prod"
    legacy.mkdir(parents=True)
    marker = legacy / "keep.txt"
    marker.write_text("legacy")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    with pytest.raises(UserAbortError, match="preserved"):
        instance._handle_multi_instance("drakostore")

    assert marker.read_text() == "legacy"


def test_missing_shared_module_refuses_unauthenticated_file_repair(monkeypatch, tmp_path: Path):
    instance = _installer(tmp_path)
    monkeypatch.setattr(installer_module, "_shared_download_missing", None)

    instance._download_missing_files(
        {
            "download_urls": {"installer": "https://evil.example/installer.py"},
            "checksums": {"installer": "0" * 64},
        }
    )

    instance.printer.error.assert_called_once()
    assert "refusing unauthenticated" in instance.printer.error.call_args.args[0]


def test_addon_restore_rejects_traversal_without_replacing_existing(tmp_path: Path):
    instance = _installer(tmp_path)
    product_path = instance.config.install_dir / "plextickets"
    addon_path = product_path / "addons" / "Stats"
    addon_path.mkdir(parents=True)
    (addon_path / "index.js").write_text("original")
    archive = tmp_path / "Stats.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("bad")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname="../escape.txt")

    instance._restore_addon_backup(
        "plextickets",
        product_path,
        {"addon_name": "Stats", "path": archive},
    )

    assert (addon_path / "index.js").read_text() == "original"
    assert not (tmp_path / "escape.txt").exists()
    assert "Restore failed" in instance.printer.error.call_args.args[0]


def test_uninstall_uses_manifest_for_all_owned_resources(monkeypatch, tmp_path: Path):
    instance = _installer(tmp_path)
    install_path = instance.config.install_dir / "drakostore"
    install_path.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "instance": "drakostore",
        "product": "drakostore",
        "install_path": str(install_path.resolve()),
        "service": "plex-drakostore",
        "firewall_port": 3103,
        "firewall_description": "drakostore",
        "domain": "store.example.com",
        "nginx": True,
        "certificate": True,
        "mongodb": {"database": "store_db", "username": "store_user"},
    }
    (install_path / installer_module.RESOURCE_MANIFEST).write_text(json.dumps(manifest))
    instance.mongo_manager.cleanup_identity.return_value = True
    instance.ssl.delete.return_value = True
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")

    assert instance._uninstall_product("drakostore") is True

    instance.systemd.remove_service.assert_called_once_with("plex-drakostore")
    instance.firewall.close_port.assert_called_once_with(3103, "drakostore")
    instance.nginx.remove.assert_called_once_with("store.example.com")
    instance.ssl.delete.assert_called_once_with("store.example.com")
    instance.mongo_manager.cleanup_identity.assert_called_once_with("store_db", "store_user", drop_database=False)
    instance.mongo_manager.remove_saved_credentials.assert_called_once_with("drakostore")
    assert not install_path.exists()
