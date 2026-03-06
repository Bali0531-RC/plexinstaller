"""Tests for config.py — product metadata and system package lists."""

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
