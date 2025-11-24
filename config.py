#!/usr/bin/env python3
"""
Configuration module for PlexDevelopment Installer
"""

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class ProductConfig:
    """Configuration for a specific product"""
    name: str
    default_port: int
    requires_mongodb: bool = False
    has_dashboard_option: bool = False
    description: str = ""

class Config:
    """Global configuration"""
    
    # Installation paths
    INSTALL_DIR = Path("/var/www/plex")
    NGINX_AVAILABLE = Path("/etc/nginx/sites-available")
    NGINX_ENABLED = Path("/etc/nginx/sites-enabled")
    PLEX_SETUP_FILE = Path("/etc/plex/setup")
    TELEMETRY_ENDPOINT = os.environ.get("PLEX_TELEMETRY_URL", "https://plexdev.live/tel")
    TELEMETRY_LOG_DIR = Path(os.environ.get("PLEX_TELEMETRY_LOG_DIR", "/opt/plexinstaller/telemetry/logs"))
    PASTE_ENDPOINT = os.environ.get("PLEX_INSTALLER_PASTE_URL", "https://paste.plexdev.live/documents")
    TELEMETRY_PREF_FILE = Path(os.environ.get("PLEX_TELEMETRY_PREF_FILE", "/etc/plex/telemetry_pref"))
    
    # Node.js
    NODE_MIN_VERSION = 20
    
    # Products configuration (from beta.sh)
    PRODUCTS: Dict[str, ProductConfig] = {
        "plextickets": ProductConfig(
            name="plextickets",
            default_port=3000,
            requires_mongodb=True,
            has_dashboard_option=True,
            description="Ticket management system with optional dashboard"
        ),
        "plexstaff": ProductConfig(
            name="plexstaff",
            default_port=3001,
            requires_mongodb=True,
            description="Staff management system"
        ),
        "plexstatus": ProductConfig(
            name="plexstatus",
            default_port=3002,
            requires_mongodb=True,
            description="Status page and monitoring"
        ),
        "plexstore": ProductConfig(
            name="plexstore",
            default_port=3003,
            requires_mongodb=True,
            description="Store management system"
        ),
        "plexforms": ProductConfig(
            name="plexforms",
            default_port=3004,
            requires_mongodb=True,
            description="Form builder and management"
        ),
        "plexlinks": ProductConfig(
            name="plexlinks",
            default_port=3005,
            requires_mongodb=True,
            description="Link management and shortener"
        ),
        "plexpaste": ProductConfig(
            name="plexpaste",
            default_port=3006,
            requires_mongodb=True,
            description="Pastebin service"
        )
    }
    
    # System packages by package manager
    SYSTEM_PACKAGES = {
        "apt": [
            "curl", "wget", "git", "unzip", "nginx", "certbot",
            "python3-certbot-nginx", "dnsutils", "net-tools",
            "nano", "zip", "tar", "software-properties-common",
            "apt-transport-https", "ca-certificates", "gnupg",
            "sudo", "coreutils", "python3-pip"
        ],
        "dnf": [
            "curl", "wget", "git", "unzip", "nginx", "certbot",
            "python3-certbot-nginx", "bind-utils", "net-tools",
            "nano", "zip", "tar", "dnf-plugins-core", "sudo",
            "coreutils", "python3-pip"
        ],
        "yum": [
            "curl", "wget", "git", "unzip", "nginx", "certbot",
            "python3-certbot-nginx", "bind-utils", "net-tools",
            "nano", "zip", "tar", "yum-utils", "sudo",
            "coreutils", "python3-pip"
        ],
        "pacman": [
            "curl", "wget", "git", "unzip", "nginx", "certbot",
            "certbot-nginx", "bind", "dnsutils", "net-tools",
            "nano", "zip", "tar", "sudo", "coreutils",
            "python-pip"
        ],
        "zypper": [
            "curl", "wget", "git", "unzip", "nginx", "certbot",
            "python3-certbot-nginx", "bind-utils", "net-tools",
            "nano", "zip", "tar", "sudo", "coreutils",
            "python3-pip"
        ]
    }
    
    # MongoDB installation
    MONGODB_VERSION = "8.2"
    
    def __init__(self):
        """Initialize configuration"""
        self.install_dir = self.INSTALL_DIR
        self.nginx_available = self.NGINX_AVAILABLE
        self.nginx_enabled = self.NGINX_ENABLED
        self.plex_setup_file = self.PLEX_SETUP_FILE
        self.telemetry_pref_file = self.TELEMETRY_PREF_FILE
    
    def get_product(self, name: str) -> ProductConfig:
        """Get product configuration"""
        return self.PRODUCTS.get(name.lower())
    
    @property
    def product_list(self) -> List[str]:
        """Get list of available products"""
        return list(self.PRODUCTS.keys())
