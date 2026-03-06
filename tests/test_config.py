"""Tests for config.py — product metadata and system package lists."""

from pathlib import Path

from config import Config, ProductConfig


class TestConfig:
    def test_products_exist(self):
        config = Config()
        assert len(config.PRODUCTS) == 8

    def test_known_products(self):
        config = Config()
        expected = [
            "plextickets",
            "plexstaff",
            "plexstatus",
            "plexstore",
            "plexforms",
            "plexlinks",
            "plexpaste",
            "plextracker",
        ]
        for name in expected:
            assert name in config.PRODUCTS, f"Missing product: {name}"

    def test_get_product_returns_config(self):
        config = Config()
        product = config.get_product("plextickets")
        assert product is not None
        assert isinstance(product, ProductConfig)
        assert product.name == "plextickets"
        assert product.default_port == 3000
        assert product.requires_mongodb is True

    def test_get_product_case_insensitive(self):
        config = Config()
        assert config.get_product("PlexTickets") is not None

    def test_get_product_unknown_returns_none(self):
        config = Config()
        assert config.get_product("nonexistent") is None

    def test_product_list(self):
        config = Config()
        assert isinstance(config.product_list, list)
        assert "plextickets" in config.product_list

    def test_all_products_have_ports(self):
        config = Config()
        for name, product in config.PRODUCTS.items():
            assert isinstance(product.default_port, int), f"{name} missing port"
            assert 1 <= product.default_port <= 65535

    def test_system_packages_all_managers(self):
        config = Config()
        for mgr in ["apt", "dnf", "yum", "pacman", "zypper"]:
            pkgs = config.SYSTEM_PACKAGES.get(mgr)
            assert pkgs is not None, f"Missing packages for {mgr}"
            assert len(pkgs) > 0

    def test_plextickets_supports_addons(self):
        config = Config()
        pt = config.get_product("plextickets")
        assert pt.supports_addons is True

    def test_plexstatus_no_addons(self):
        config = Config()
        ps = config.get_product("plexstatus")
        assert ps.supports_addons is False


# ---------------------------------------------------------------------------
# ProductConfig dataclass
# ---------------------------------------------------------------------------


class TestProductConfig:
    def test_defaults(self):
        p = ProductConfig(name="test", default_port=5000)
        assert p.requires_mongodb is False
        assert p.has_dashboard_option is False
        assert p.supports_addons is False
        assert p.description == ""

    def test_all_fields(self):
        p = ProductConfig(
            name="foo",
            default_port=8080,
            requires_mongodb=True,
            has_dashboard_option=True,
            supports_addons=True,
            description="desc",
        )
        assert p.name == "foo"
        assert p.default_port == 8080
        assert p.requires_mongodb is True
        assert p.has_dashboard_option is True
        assert p.supports_addons is True
        assert p.description == "desc"


# ---------------------------------------------------------------------------
# Per-product validation
# ---------------------------------------------------------------------------


class TestProductDetails:
    def test_all_products_require_mongodb(self):
        """All current PlexDev products use MongoDB."""
        config = Config()
        for name, product in config.PRODUCTS.items():
            assert product.requires_mongodb is True, f"{name} should require MongoDB"

    def test_all_products_have_descriptions(self):
        config = Config()
        for name, product in config.PRODUCTS.items():
            assert product.description != "", f"{name} missing description"

    def test_ports_are_unique(self):
        config = Config()
        ports = [p.default_port for p in config.PRODUCTS.values()]
        assert len(ports) == len(set(ports)), "Duplicate default ports found"

    def test_port_range_sequential(self):
        """Products use sequential ports starting from 3000."""
        config = Config()
        ports = sorted(p.default_port for p in config.PRODUCTS.values())
        assert ports[0] == 3000
        assert ports[-1] == 3007

    def test_plextickets_has_dashboard_option(self):
        config = Config()
        pt = config.get_product("plextickets")
        assert pt.has_dashboard_option is True

    def test_other_products_no_dashboard_option(self):
        config = Config()
        for name in ["plexstatus", "plexstore", "plexforms", "plexlinks", "plexpaste", "plextracker"]:
            p = config.get_product(name)
            assert p.has_dashboard_option is False, f"{name} should not have dashboard option"

    def test_product_name_matches_key(self):
        config = Config()
        for key, product in config.PRODUCTS.items():
            assert key == product.name, f"Key {key} != product.name {product.name}"


# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------


class TestSystemPackages:
    def test_all_managers_have_common_packages(self):
        """All package managers include essential tools."""
        config = Config()
        for mgr, pkgs in config.SYSTEM_PACKAGES.items():
            for required in ["curl", "wget", "git", "nginx", "sudo"]:
                assert required in pkgs, f"{mgr} missing {required}"

    def test_apt_has_dnsutils(self):
        config = Config()
        assert "dnsutils" in config.SYSTEM_PACKAGES["apt"]

    def test_dnf_has_bind_utils(self):
        config = Config()
        assert "bind-utils" in config.SYSTEM_PACKAGES["dnf"]


# ---------------------------------------------------------------------------
# Config class-level attributes
# ---------------------------------------------------------------------------


class TestConfigAttributes:
    def test_install_dir(self):
        config = Config()
        assert config.install_dir == Path("/var/www/plex")

    def test_mongodb_version(self):
        config = Config()
        assert config.MONGODB_VERSION == "8.0"

    def test_node_min_version(self):
        assert Config.NODE_MIN_VERSION == 20

    def test_get_product_whitespace(self):
        config = Config()
        # lowercased but not stripped — should return None
        assert config.get_product("  plextickets  ") is None

    def test_product_list_returns_list(self):
        config = Config()
        pl = config.product_list
        assert isinstance(pl, list)
        assert len(pl) == 8

    def test_product_list_order_matches_keys(self):
        config = Config()
        assert config.product_list == list(config.PRODUCTS.keys())
