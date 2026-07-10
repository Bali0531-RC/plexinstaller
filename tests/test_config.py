"""Windows-specific configuration contracts."""

import json
from pathlib import Path
from unittest import mock

import pytest

from config import Config, ProductConfig


def test_canonical_products_and_legacy_aliases():
    assert list(Config.PRODUCTS) == [
        "plextickets",
        "plexstaff",
        "drakostatus",
        "drakostore",
        "drakoforms",
        "drakolinks",
        "drakopaste",
        "drakotracker",
    ]
    assert Config.canonical_product_name("plexstore") == "drakostore"
    assert Config.canonical_product_name("PlexStore-prod") == "drakostore"
    assert Config.canonical_product_name("plexstore_prod") == "drakostore"
    assert Config.equivalent_product_names("drakostore") == ("drakostore", "plexstore")
    assert Config.equivalent_instance_names("plexstore-prod") == ("drakostore-prod", "plexstore-prod")


def test_product_lookup_is_case_and_whitespace_tolerant():
    product = Config().get_product("  PlexStore  ")
    assert product is not None
    assert product.name == "drakostore"
    assert product.display_name == "DrakoStore"
    assert Config().get_product("missing") is None


def test_product_defaults_and_capabilities():
    product = ProductConfig(name="test", default_port=5000)
    assert product.display_name == ""
    assert product.requires_mongodb is False
    assert product.has_dashboard_option is False
    assert product.supports_addons is False
    assert product.legacy_names == ()
    assert Config.PRODUCTS["plextickets"].has_dashboard_option is True
    assert Config.PRODUCTS["plextickets"].supports_addons is True
    assert Config.PRODUCTS["plexstaff"].supports_addons is True
    assert all(product.requires_mongodb for product in Config.PRODUCTS.values())


def test_ports_are_unique_and_sequential():
    ports = [product.default_port for product in Config.PRODUCTS.values()]
    assert sorted(ports) == list(range(3000, 3008))
    assert len(ports) == len(set(ports))


def test_windows_package_managers_only():
    assert set(Config.SYSTEM_PACKAGES) == {"winget", "choco"}
    assert "OpenJS.NodeJS.LTS" in Config.SYSTEM_PACKAGES["winget"]
    assert "nodejs-lts" in Config.SYSTEM_PACKAGES["choco"]
    assert "7zip.7zip" in Config.SYSTEM_PACKAGES["winget"]


def test_paths_are_derived_from_programdata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(Config, "INSTALL_DIR", tmp_path / "plex" / "apps")
    monkeypatch.setattr(Config, "NGINX_AVAILABLE", tmp_path / "plex" / "nginx" / "sites-available")
    monkeypatch.setattr(Config, "NGINX_ENABLED", tmp_path / "plex" / "nginx" / "sites-enabled")
    config = Config()
    assert config.install_dir == tmp_path / "plex" / "apps"
    assert config.nginx_available == tmp_path / "plex" / "nginx" / "sites-available"
    assert config.nginx_enabled == tmp_path / "plex" / "nginx" / "sites-enabled"


def test_find_app_config_prefers_yaml(tmp_path: Path):
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "config.yml").write_text("Port: 3000\n")
    assert Config.find_app_config(tmp_path) == tmp_path / "config.yml"


def test_persist_yaml_port_updates_exact_key_atomically(tmp_path: Path):
    config_file = tmp_path / "config.yml"
    config_file.write_text("dbPort: 27017\nPort: 3000\n")
    Config().persist_app_port(tmp_path, 4123)
    assert config_file.read_text() == "dbPort: 27017\nPort: 4123\n"


def test_persist_json_port_preserves_other_values(tmp_path: Path):
    config_file = tmp_path / "config.json"
    config_file.write_text('{"port": 3000, "name": "app"}')
    Config().persist_app_port(tmp_path, 4124)
    assert json.loads(config_file.read_text()) == {"port": 4124, "name": "app"}


@pytest.mark.parametrize("port", [0, 65536, True, "3000"])
def test_persist_port_rejects_invalid_values(tmp_path: Path, port):
    (tmp_path / "config.yml").write_text("Port: 3000\n")
    with pytest.raises(ValueError, match="between 1 and 65535"):
        Config().persist_app_port(tmp_path, port)


def test_is_port_available_validates_range():
    assert Config.is_port_available(0) is False
    with mock.patch("config.socket.socket") as socket_cls:
        assert Config.is_port_available(3000) is True
    socket_cls.return_value.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 3000))


def test_product_list_matches_canonical_order():
    assert Config().product_list == list(Config.PRODUCTS)
    assert Config.MONGODB_VERSION == "8.0"
    assert Config.NODE_MIN_VERSION == 20
