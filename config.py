#!/usr/bin/env python3
"""
Configuration module for PlexDevelopment Installer
"""

import json
import os
import re
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - dependency is declared by the package
    yaml = None  # type: ignore[assignment]


@dataclass
class ProductConfig:
    """Configuration for a specific product"""

    name: str
    default_port: int
    display_name: str = ""
    requires_mongodb: bool = False
    has_dashboard_option: bool = False
    supports_addons: bool = False
    description: str = ""
    legacy_names: tuple[str, ...] = ()


class Config:
    """Global configuration"""

    # Installation paths
    INSTALL_DIR = Path("/var/www/plex")
    NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
    NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
    PLEX_SETUP_FILE = Path("/etc/plex/setup")
    TELEMETRY_ENDPOINT = os.environ.get("PLEX_TELEMETRY_URL", "https://plexdev.xyz/tel")
    TELEMETRY_LOG_DIR = Path(os.environ.get("PLEX_TELEMETRY_LOG_DIR", "/opt/plexinstaller/telemetry/logs"))
    PASTE_ENDPOINT = os.environ.get("PLEX_INSTALLER_PASTE_URL", "https://paste.plexdev.xyz/documents")
    TELEMETRY_PREF_FILE = Path(os.environ.get("PLEX_TELEMETRY_PREF_FILE", "/etc/plex/telemetry_pref"))

    # Node.js
    NODE_MIN_VERSION = 20

    # Products configuration (from beta.sh)
    PRODUCTS: dict[str, ProductConfig] = {
        "plextickets": ProductConfig(
            name="plextickets",
            display_name="PlexTickets",
            default_port=3000,
            requires_mongodb=True,
            has_dashboard_option=True,
            supports_addons=True,
            description="Ticket management system with optional dashboard",
        ),
        "plexstaff": ProductConfig(
            name="plexstaff",
            display_name="PlexStaff",
            default_port=3001,
            requires_mongodb=True,
            supports_addons=True,
            description="Staff management system",
        ),
        "drakostatus": ProductConfig(
            name="drakostatus",
            display_name="DrakoStatus",
            default_port=3002,
            requires_mongodb=True,
            description="Status page and monitoring",
            legacy_names=("plexstatus",),
        ),
        "drakostore": ProductConfig(
            name="drakostore",
            display_name="DrakoStore",
            default_port=3003,
            requires_mongodb=True,
            description="Store management system",
            legacy_names=("plexstore",),
        ),
        "drakoforms": ProductConfig(
            name="drakoforms",
            display_name="DrakoForms",
            default_port=3004,
            requires_mongodb=True,
            description="Form builder and management",
            legacy_names=("plexforms",),
        ),
        "drakolinks": ProductConfig(
            name="drakolinks",
            display_name="DrakoLinks",
            default_port=3005,
            requires_mongodb=True,
            description="Link management and shortener",
            legacy_names=("plexlinks",),
        ),
        "drakopaste": ProductConfig(
            name="drakopaste",
            display_name="DrakoPaste",
            default_port=3006,
            requires_mongodb=True,
            description="Pastebin service",
            legacy_names=("plexpaste",),
        ),
        "drakotracker": ProductConfig(
            name="drakotracker",
            display_name="DrakoTracker",
            default_port=3007,
            requires_mongodb=True,
            description="Bug and Suggestion tracker",
            legacy_names=("plextracker",),
        ),
    }

    PRODUCT_ALIASES: dict[str, str] = {
        "plexstatus": "drakostatus",
        "plexstore": "drakostore",
        "plexforms": "drakoforms",
        "plexlinks": "drakolinks",
        "plexpaste": "drakopaste",
        "plextracker": "drakotracker",
    }

    # System packages by package manager
    SYSTEM_PACKAGES = {
        "apt": [
            "curl",
            "wget",
            "git",
            "unzip",
            "nginx",
            "certbot",
            "python3-certbot-nginx",
            "dnsutils",
            "net-tools",
            "nano",
            "zip",
            "tar",
            "ca-certificates",
            "gnupg",
            "coreutils",
            "python3-pip",
        ],
        "dnf": [
            "curl",
            "wget",
            "git",
            "unzip",
            "nginx",
            "certbot",
            "python3-certbot-nginx",
            "bind-utils",
            "net-tools",
            "nano",
            "zip",
            "tar",
            "dnf-plugins-core",
            "coreutils",
            "python3-pip",
        ],
        "yum": [
            "curl",
            "wget",
            "git",
            "unzip",
            "nginx",
            "certbot",
            "python3-certbot-nginx",
            "bind-utils",
            "net-tools",
            "nano",
            "zip",
            "tar",
            "yum-utils",
            "coreutils",
            "python3-pip",
        ],
        "pacman": [
            "curl",
            "wget",
            "git",
            "unzip",
            "nginx",
            "certbot",
            "certbot-nginx",
            "bind",
            "dnsutils",
            "net-tools",
            "nano",
            "zip",
            "tar",
            "coreutils",
            "python-pip",
        ],
        "zypper": [
            "curl",
            "wget",
            "git",
            "unzip",
            "nginx",
            "certbot",
            "python3-certbot-nginx",
            "bind-utils",
            "net-tools",
            "nano",
            "zip",
            "tar",
            "coreutils",
            "python3-pip",
        ],
    }

    # MongoDB installation
    MONGODB_VERSION = "8.0"
    MONGODB_REPO_VERSION_BOOKWORM = "8.2"  # Bookworm uses 8.2 repo per MongoDB official docs

    def __init__(self):
        """Initialize configuration"""
        self.install_dir = self.INSTALL_DIR
        self.nginx_available = self.NGINX_AVAILABLE
        self.nginx_enabled = self.NGINX_ENABLED
        self.plex_setup_file = self.PLEX_SETUP_FILE
        self.telemetry_pref_file = self.TELEMETRY_PREF_FILE

    def get_product(self, name: str) -> ProductConfig | None:
        """Get canonical product configuration for a current or legacy name."""
        base = self.instance_product_base(name)
        canonical = self.PRODUCT_ALIASES.get(base, base)
        return self.PRODUCTS.get(canonical)

    @classmethod
    def instance_product_base(cls, name: str) -> str:
        """Return the recognized product prefix from an instance name."""
        normalized = name.strip().lower()
        known_names = set(cls.PRODUCTS) | set(cls.PRODUCT_ALIASES)
        for candidate in sorted(known_names, key=len, reverse=True):
            if normalized == candidate or normalized.startswith(f"{candidate}-"):
                return candidate
        return normalized.split("-", 1)[0]

    @classmethod
    def canonical_product_name(cls, name: str) -> str:
        """Map a product or instance name to its canonical product ID."""
        base = cls.instance_product_base(name)
        return cls.PRODUCT_ALIASES.get(base, base)

    @classmethod
    def equivalent_product_names(cls, name: str) -> tuple[str, ...]:
        """Return canonical and legacy base names for one product family."""
        canonical = cls.canonical_product_name(name)
        product = cls.PRODUCTS.get(canonical)
        if product is None:
            return (canonical,)
        return (canonical, *product.legacy_names)

    @classmethod
    def equivalent_instance_names(cls, name: str) -> tuple[str, ...]:
        """Return current and legacy spellings while preserving an instance suffix."""
        normalized = name.strip().lower()
        base = cls.instance_product_base(normalized)
        suffix = normalized[len(base) :]
        return tuple(f"{candidate}{suffix}" for candidate in cls.equivalent_product_names(base))

    @staticmethod
    def find_app_config(install_path: Path) -> Path | None:
        """Return the preferred YAML/JSON application config, if present."""
        for name in ("config.yml", "config.yaml", "config.json"):
            candidate = install_path / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
        """Return whether *port* can be bound locally without committing config changes."""
        if not 1 <= port <= 65535:
            return False
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
            return True
        except OSError:
            return False

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Atomically replace text while preserving mode and ownership."""
        metadata = path.stat()
        mode = metadata.st_mode & 0o777
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, mode)
            if os.geteuid() == 0:
                os.chown(temporary, metadata.st_uid, metadata.st_gid)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def persist_app_port(self, install_path: Path, port: int) -> Path:
        """Validate and atomically persist an application's selected port.

        JSON is parsed strictly. YAML is parsed for validation when PyYAML is
        available, then patched without reformatting the rest of the user's file.
        A missing port key is added using the conventional ``Port`` spelling.
        """
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")

        config_file = self.find_app_config(install_path)
        if config_file is None:
            raise FileNotFoundError(f"No config.yml, config.yaml, or config.json found in {install_path}")

        original = config_file.read_text(encoding="utf-8")
        if config_file.suffix.lower() == ".json":
            data = json.loads(original)
            if not isinstance(data, dict):
                raise ValueError("Application JSON config must contain an object")
            key = next((candidate for candidate in ("Port", "port", "PORT") if candidate in data), "Port")
            data[key] = port
            updated = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        else:
            if yaml is not None:
                parsed = yaml.safe_load(original) if original.strip() else {}
                if parsed is not None and not isinstance(parsed, dict):
                    raise ValueError("Application YAML config must contain a mapping")
            pattern = re.compile(
                r"^(?P<indent>\s*)(?P<key>port)(?P<separator>\s*:\s*).*$", re.IGNORECASE | re.MULTILINE
            )
            if pattern.search(original):
                updated = pattern.sub(
                    lambda match: f"{match.group('indent')}{match.group('key')}{match.group('separator')}{port}",
                    original,
                    count=1,
                )
            else:
                updated = original
                if updated and not updated.endswith("\n"):
                    updated += "\n"
                updated += f"Port: {port}\n"

        self._atomic_write(config_file, updated)
        return config_file

    @property
    def product_list(self) -> list[str]:
        """Get list of available products"""
        return list(self.PRODUCTS.keys())
