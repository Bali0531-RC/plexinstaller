#!/usr/bin/env python3
"""
PlexDevelopment Products Installer - Python Version
Modular, maintainable installer for Plex products
"""

import atexit
import io
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - exercised on non-Windows test hosts
    _msvcrt = None  # type: ignore[assignment]

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised on Windows
    _fcntl = None  # type: ignore[assignment]

from config import Config
from utils import (
    ArchiveExtractor,
    ColorPrinter,
    DNSChecker,
    FirewallManager,
    NginxManager,
    SSLManager,
    SystemDetector,
    SystemdManager,
    clear_terminal,
    is_admin,
    validate_path_component,
)

try:
    from addon_manager import AddonManager
except ImportError:
    AddonManager = None  # type: ignore[assignment,misc]
from telemetry_client import TelemetryClient

try:
    from shared import (
        INSTALLER_DIR,
    )
    from shared import (
        download_missing_files as _shared_download_missing,
    )
    from shared import (
        ensure_cli_entrypoints as _shared_ensure_cli,
    )
    from shared import (
        is_newer_version as _shared_is_newer,
    )
    from shared import (
        perform_update as _shared_perform_update,
    )
    from shared import (
        verify_gpg_signature as _shared_verify_gpg,
    )
except ImportError:
    _shared_is_newer = None  # type: ignore[assignment]
    _shared_verify_gpg = None  # type: ignore[assignment]
    _shared_perform_update = None  # type: ignore[assignment]
    _shared_ensure_cli = None  # type: ignore[assignment]
    _shared_download_missing = None  # type: ignore[assignment]
    INSTALLER_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "plexinstaller"
try:
    from mongodb_manager import MongoDBManager
except ImportError:
    MongoDBManager = None  # type: ignore[assignment,misc]
try:
    from backup_manager import BackupManager
except ImportError:
    BackupManager = None  # type: ignore[assignment,misc]
try:
    from health_checker import HealthChecker, SelfTestResult
except ImportError:
    HealthChecker = None  # type: ignore[assignment,misc]
    SelfTestResult = None  # type: ignore[assignment,misc]
from utils import setup_logging

# Current installer version
INSTALLER_VERSION = "3.2.1"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/windows-experimental/version.json"
LOCK_FILE = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "plexinstaller" / "plexinstaller.lock"
RESOURCE_MANIFEST = ".plexinstaller-resources.json"
_SYSTEM_TEMP_ROOTS = frozenset(
    path.resolve()
    for path in {
        Path(tempfile.gettempdir()),
        Path(os.environ.get("TEMP", tempfile.gettempdir())),
        Path(os.environ.get("TMP", tempfile.gettempdir())),
    }
)


class UserAbortError(Exception):
    """Raised when the installation cannot continue due to a user action (bad input, declining a prompt, etc.)."""


@dataclass
class InstallationContext:
    """Context for an installation session"""

    product: str
    instance_name: str
    install_path: Path
    port: int
    domain: str | None = None
    email: str | None = None
    needs_web_setup: bool = True
    has_dashboard: bool = False
    install_path_ready: bool = False
    install_path_created: bool = False
    service_created: bool = False
    nginx_configured: bool = False
    ssl_configured: bool = False
    nginx_paths_created: bool = False
    domain_skipped: bool = False
    opened_port: int | None = None
    telemetry_session: str | None = None
    log_path: Path | None = None
    mongo_identity: dict[str, str] | None = None


class PlexInstaller:
    """Main installer class"""

    def __init__(self, version: str = "stable"):
        self.version = version
        self.config = Config()
        self.printer = ColorPrinter()
        self._lock_fd: io.TextIOWrapper | None = None

        # Check admin FIRST before any file operations
        if not is_admin():
            self.printer.error("This installer must be run as Administrator")
            sys.exit(1)

        # Acquire lock to prevent concurrent runs
        if not self._acquire_lock():
            self.printer.error("Another instance of PlexInstaller is already running.")
            sys.exit(1)

        self.system = SystemDetector()
        self.dns_checker = DNSChecker()
        self.firewall = FirewallManager()
        self.nginx = NginxManager()
        self.ssl = SSLManager()
        self.systemd = SystemdManager()
        self.extractor = ArchiveExtractor()
        self.addon_manager = AddonManager() if AddonManager is not None else None
        self.mongo_manager = (
            MongoDBManager(
                printer=self.printer,
                system=self.system,
                mongodb_version=self.config.MONGODB_VERSION,
            )
            if MongoDBManager is not None
            else None
        )
        self.backup_mgr = (
            BackupManager(
                printer=self.printer,
                systemd=self.systemd,
                install_dir=self.config.install_dir,
            )
            if BackupManager is not None
            else None
        )
        self.health = (
            HealthChecker(
                printer=self.printer,
                systemd=self.systemd,
                install_dir=self.config.install_dir,
                node_min_version=self.config.NODE_MIN_VERSION,
                nginx_available=self.config.nginx_available,
                nginx_enabled=self.config.nginx_enabled,
            )
            if HealthChecker is not None
            else None
        )
        self.telemetry_enabled = self._initialize_telemetry_preference()
        self.telemetry = TelemetryClient(
            endpoint=self.config.TELEMETRY_ENDPOINT,
            log_dir=self.config.TELEMETRY_LOG_DIR,
            paste_endpoint=self.config.PASTE_ENDPOINT,
            enabled=self.telemetry_enabled,
        )

        # Register cleanup on exit
        atexit.register(self._release_lock)

    def _acquire_lock(self) -> bool:
        """Acquire exclusive lock to prevent concurrent installer runs"""
        try:
            LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = LOCK_FILE.open("a+", encoding="utf-8")
            if _msvcrt is not None:
                lock_api: Any = _msvcrt
                self._lock_fd.seek(0)
                if not self._lock_fd.read(1):
                    self._lock_fd.write("\0")
                    self._lock_fd.flush()
                self._lock_fd.seek(0)
                lock_api.locking(self._lock_fd.fileno(), lock_api.LK_NBLCK, 1)
            elif _fcntl is not None:
                _fcntl.flock(self._lock_fd.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
            self._lock_fd.seek(0)
            self._lock_fd.truncate()
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except OSError:
            if self._lock_fd:
                self._lock_fd.close()
                self._lock_fd = None
            return False

    def _release_lock(self):
        """Release the lock file"""
        if self._lock_fd:
            try:
                if _msvcrt is not None:
                    lock_api: Any = _msvcrt
                    self._lock_fd.seek(0)
                    lock_api.locking(self._lock_fd.fileno(), lock_api.LK_UNLCK, 1)
                elif _fcntl is not None:
                    _fcntl.flock(self._lock_fd.fileno(), _fcntl.LOCK_UN)
                self._lock_fd.close()
                self._lock_fd = None
                # Remove lock file
                try:
                    LOCK_FILE.unlink()
                except OSError:
                    pass
            except Exception:
                pass

    def run(self):
        """Main entry point"""
        clear_terminal()
        self._display_banner()

        if not self.telemetry_enabled:
            self.printer.step(f"Telemetry is disabled. Edit {self.config.telemetry_pref_file} to re-enable it.")

        # Check for updates
        self._check_for_updates()

        # Root already checked in __init__, detect system and install deps
        self.system.detect()
        self.system.install_dependencies()

        # Main menu
        self._show_main_menu()

    def _display_banner(self):
        """Display PlexDevelopment banner"""
        print(f"{ColorPrinter.BOLD}{ColorPrinter.CYAN}", end="")
        print(r"  _____  _           _____                 _                                  _   ")
        print(r" |  __ \| |         |  __ \               | |                                | |  ")
        print(r" | |__) | | _____  _| |  | | _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ ")
        print(r" |  ___/| |/ _ \ \/ / |  | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ \` _ \ / _ \ '_ \| __|")
        print(r" | |    | |  __/>  <| |__| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ ")
        print(r" |_|    |_|\___/_/\_\_____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|")
        print(r"                                                  | |                             ")
        print(r"                                                  |_|                             ")
        print(ColorPrinter.NC)
        print(
            f"{ColorPrinter.BOLD}{ColorPrinter.PURPLE} UNOFFICIAL Installation Script for PlexDevelopment Products{ColorPrinter.NC}"
        )
        print(f"{ColorPrinter.CYAN}{self.version.upper()} Version - Python-Based Installer{ColorPrinter.NC}\n")

    def _initialize_telemetry_preference(self) -> bool:
        """Load or prompt for the user's telemetry preference."""
        pref_file = self.config.telemetry_pref_file

        try:
            if pref_file.exists():
                stored = pref_file.read_text().strip().lower()
                return stored not in {"disabled", "opted_out", "false", "0"}
        except Exception as exc:
            self.printer.warning(f"Could not read telemetry preference: {exc}")

        return self._prompt_telemetry_preference(pref_file)

    def _prompt_telemetry_preference(self, pref_file: Path) -> bool:
        """Prompt the user to opt in or out of telemetry on first launch."""
        print(f"{ColorPrinter.BOLD}{ColorPrinter.CYAN}Telemetry Preference{ColorPrinter.NC}")
        print(
            "We collect anonymous install diagnostics (steps completed, errors, log snippets)"
            " to improve PlexInstaller reliability. No API keys or customer data are sent."
        )
        choice = input("Share anonymous telemetry to help improve the installer? (Y/n): ").strip().lower()
        enabled = choice not in {"n", "no"}

        try:
            pref_file.parent.mkdir(parents=True, exist_ok=True)
            pref_file.write_text("enabled\n" if enabled else "disabled\n")
        except Exception as exc:
            self.printer.warning(f"Could not save telemetry preference: {exc}")

        if enabled:
            self.printer.success("Telemetry enabled – thank you for helping us improve!")
        else:
            self.printer.warning(f"Telemetry disabled. You can re-enable it by editing {pref_file}")

        return enabled

    def _check_for_updates(self):
        """Check for installer updates and auto-update if newer version available"""
        try:
            self.printer.step("Checking for installer updates...")

            if _shared_download_missing is None or _shared_verify_gpg is None:
                raise RuntimeError("Shared update security module is unavailable")

            from shared import MAX_MANIFEST_BYTES, _download_bytes

            version_json_bytes = _download_bytes(
                VERSION_CHECK_URL,
                timeout=5,
                max_bytes=MAX_MANIFEST_BYTES,
            )
            if not self._verify_gpg_signature(version_json_bytes):
                raise RuntimeError("Version manifest signature verification failed")
            version_data = json.loads(version_json_bytes.decode())

            remote_version = version_data.get("version", "0.0.0")

            # Compare versions
            if self._is_newer_version(remote_version, INSTALLER_VERSION):
                self.printer.warning(
                    f"New installer version available: {remote_version} (current: {INSTALLER_VERSION})"
                )
                print(f"\n{ColorPrinter.CYAN}Changelog:{ColorPrinter.NC}")
                for item in version_data.get("changelog", []):
                    print(f"  • {item}")

                choice = (
                    input(f"\n{ColorPrinter.YELLOW}Auto-update to latest version? (y/n): {ColorPrinter.NC}")
                    .strip()
                    .lower()
                )

                if choice == "y":
                    self._perform_update(version_data, version_json_bytes)
                else:
                    self.printer.step("Continuing with current version...")
            else:
                self.printer.success(f"Installer is up to date (v{INSTALLER_VERSION})")

            # Download any managed files that are missing on disk
            self._download_missing_files(version_data)

            # Ensure CLI entrypoints are wired correctly (older installs used a copied plex CLI).
            self._ensure_cli_entrypoints()

            print()  # Add spacing

        except Exception as e:
            self.printer.warning(f"Could not check for updates: {e}")
            self.printer.step("Continuing with current version...")
            print()

    def _download_missing_files(self, version_data: dict) -> None:
        """Download any managed files that are missing from the install directory.

        The shared security module re-fetches and authenticates the manifest
        before using any download URL. Missing shared.py disables repair.
        """
        if _shared_download_missing is not None:
            _shared_download_missing(
                print_info=self.printer.step,
                print_success=self.printer.success,
                print_warning=self.printer.warning,
                print_error=self.printer.error,
            )
            return

        self.printer.error("shared.py is unavailable — refusing unauthenticated missing-file repair")

    def _ensure_cli_entrypoints(self):
        """Ensure `plexinstaller` and `plex` commands point at the current installer bundle."""
        if _shared_ensure_cli is not None:
            _shared_ensure_cli()

    def _is_newer_version(self, remote: str, local: str) -> bool:
        """Compare version strings (semantic versioning)"""
        if _shared_is_newer is not None:
            return _shared_is_newer(remote, local)
        try:
            r = [int(x) for x in remote.split(".")]
            loc = [int(x) for x in local.split(".")]
            while len(r) < len(loc):
                r.append(0)
            while len(loc) < len(r):
                loc.append(0)
            return r > loc
        except Exception:
            return False

    def _verify_gpg_signature(self, version_json_bytes: bytes) -> bool:
        """Download version.json.sig and verify version.json against it."""
        if _shared_verify_gpg is None:
            self.printer.error("shared.py is unavailable — refusing to verify or install updates")
            return False
        return _shared_verify_gpg(
            version_json_bytes,
            print_info=self.printer.step,
            print_success=self.printer.success,
            print_warning=self.printer.warning,
            print_error=self.printer.error,
        )

    def _perform_update(self, version_data: dict, version_json_bytes: bytes = b""):
        """Download and install new installer version with checksum verification"""
        if _shared_perform_update is None:
            self.printer.warning("shared.py not available — cannot auto-update")
            return
        _shared_perform_update(
            version_data,
            version_json_bytes,
            print_info=self.printer.step,
            print_success=self.printer.success,
            print_warning=self.printer.warning,
            print_error=self.printer.error,
        )

    def _show_main_menu(self):
        """Display main menu and handle user choice"""
        while True:
            clear_terminal()
            self._display_banner()
            self.printer.header("Main Menu")

            # Show quick status overview
            self._show_services_status()
            print()

            print("Plex Development Products")
            print("1) Install PlexTickets")
            print("2) Install PlexStaff")
            print("Drako Development Products")
            print("3) Install DrakoStatus")
            print("4) Install DrakoStore")
            print("5) Install DrakoForms")
            print("6) Install DrakoLinks")
            print("7) Install DrakoPaste")
            print("8) Install DrakoTracker")
            print("----------------------------------------")
            print("9) Manage Installations")
            print("10) Manage Backups")
            print("11) Manage Addons (PlexTickets/PlexStaff)")
            print("12) SSL Certificate Management")
            print("13) System Health Check")
            print("----------------------------------------")
            print("0) Exit")

            choice = input("\nEnter your choice: ").strip()

            if choice == "0":
                self.printer.success("Goodbye!")
                break
            elif choice == "1":
                self._install_plextickets()
            elif choice == "2":
                self._install_product("plexstaff", 3001)
            elif choice == "3":
                self._install_product("drakostatus", 3002)
            elif choice == "4":
                self._install_product("drakostore", 3003)
            elif choice == "5":
                self._install_product("drakoforms", 3004)
            elif choice == "6":
                self._install_product("drakolinks", 3005)
            elif choice == "7":
                self._install_product("drakopaste", 3006)
            elif choice == "8":
                self._install_product("drakotracker", 3007)
            elif choice == "9":
                self._manage_installations()
            elif choice == "10":
                self.backup_mgr.menu()
            elif choice == "11":
                self._manage_addons_menu()
            elif choice == "12":
                self._ssl_management_menu()
            elif choice == "13":
                self.health.system_health_check()
            else:
                self.printer.error("Invalid choice")

            if choice != "0":
                input("\nPress Enter to continue...")

    def _show_services_status(self):
        """Show quick status overview of all services"""
        if not self.config.install_dir.exists():
            return

        products = [d for d in self.config.install_dir.iterdir() if d.is_dir() and d.name != "backups"]

        if not products:
            return

        print("\n+--------------+------------------+------+")
        print("| Product      | Service Status   | Port |")
        print("+--------------+------------------+------+")

        for product_dir in products:
            product = product_dir.name
            service_name = f"plex-{product}"
            status = self.systemd.get_status(service_name)

            # Get port from config if possible
            port = "N/A"
            for config_file in list(product_dir.glob("config.y*ml")) + list(product_dir.glob("config.json")):
                try:
                    content = config_file.read_text()
                    if config_file.suffix.lower() == ".json":
                        data = json.loads(content)
                        value = next((data[key] for key in ("Port", "port", "PORT") if key in data), None)
                        match_port = str(value) if isinstance(value, int) and 1 <= value <= 65535 else None
                    else:
                        match = re.search(
                            r"^[ \t]*port[ \t]*:[ \t]*(\d+)(?:[ \t]*(?:#.*)?)?$",
                            content,
                            re.IGNORECASE | re.MULTILINE,
                        )
                        match_port = match.group(1) if match else None
                    if match_port:
                        port = match_port
                        break
                except Exception:
                    pass

            status_display = status
            normalized = status.strip().lower()
            if normalized == "active":
                status_display = f"{ColorPrinter.GREEN}{status}{ColorPrinter.NC}"
            elif normalized == "inactive":
                status_display = f"{ColorPrinter.YELLOW}{status}{ColorPrinter.NC}"
            else:
                status_display = f"{ColorPrinter.RED}{status}{ColorPrinter.NC}"

            print(f"| {product:<12} | {status_display:<16} | {port:<4} |")

        print("+--------------+------------------+------+")

    def _install_plextickets(self):
        """Special handling for PlexTickets with dashboard option"""
        self.printer.header("PlexTickets Installation")
        print("\n1) Install with Web Dashboard (Port 3000)")
        print("2) Install Bot Only (no web interface)")
        print("0) Back")

        choice = input("\nEnter your choice: ").strip()

        if choice == "1":
            self._install_product("plextickets", 3000, has_dashboard=True)
        elif choice == "2":
            self._install_product("plextickets", 3000, has_dashboard=False, needs_web=False)
        elif choice == "0":
            return
        else:
            self.printer.error("Invalid choice")

    def _install_product(self, product: str, default_port: int, has_dashboard: bool = False, needs_web: bool = True):
        """Install a product"""
        instance_name = None
        context: InstallationContext | None = None
        current_step = "initializing"

        try:
            # Check for multi-instance
            instance_name = self._handle_multi_instance(product)
            install_path = self.config.install_dir / instance_name
            if install_path.exists():
                raise UserAbortError(f"Install path already exists: {install_path}")
            context = InstallationContext(
                product=product,
                instance_name=instance_name,
                install_path=install_path,
                port=default_port,
                needs_web_setup=needs_web,
                has_dashboard=has_dashboard,
            )
            session_id = self.telemetry.start_session(product, instance_name)
            context.telemetry_session = session_id
            context.log_path = self.telemetry.log_path
            self.telemetry.log_step("instance", "success", f"Instance: {instance_name}")

            # Find archive
            current_step = "archive_selection"
            self.telemetry.log_step(current_step, "start", "Searching for product archive")
            archive_path = self._find_archive(product)
            if not archive_path:
                self.telemetry.log_step(current_step, "uncompleted", "No archive selected")
                self.telemetry.finish_session("uncompleted", current_step, "Archive not provided")
                return
            self.telemetry.log_step(current_step, "success", str(archive_path))

            # Extract product
            current_step = "extraction"
            self.telemetry.log_step(current_step, "start", f"-> {install_path}")
            extracted_path = self._extract_product(archive_path, instance_name)
            if not extracted_path:
                raise UserAbortError("Archive extraction failed — check the file path and format")
            context.install_path = extracted_path
            context.install_path_ready = True
            context.install_path_created = True
            self.telemetry.log_step(current_step, "success", f"Extracted to {extracted_path}")

            # Install NPM dependencies
            current_step = "npm_install"
            self.telemetry.log_step(current_step, "start")
            if not self._install_npm_dependencies(extracted_path):
                raise RuntimeError("NPM install failed")
            self.telemetry.log_step(current_step, "success")

            # Create 502 error page
            current_step = "error_page"
            self._create_502_page(extracted_path, product)
            self.telemetry.log_step(current_step, "success")

            # MongoDB setup
            current_step = "mongodb"
            product_config = self.config.get_product(product) if hasattr(self.config, "get_product") else None
            requires_mongo = bool(getattr(product_config, "requires_mongodb", False))
            if self.mongo_manager is None:
                if requires_mongo:
                    raise RuntimeError("MongoDB manager is unavailable for a product that requires MongoDB")
                mongo_creds = None
            else:
                wait_for_port = self.health.wait_for_tcp_port if self.health is not None else None
                mongo_creds = self.mongo_manager.setup(
                    instance_name,
                    extracted_path,
                    required=requires_mongo,
                    wait_for_tcp_port=wait_for_port,
                )
            if mongo_creds:
                context.mongo_identity = {
                    "database": str(mongo_creds.get("database", "")),
                    "username": str(mongo_creds.get("username", "")),
                }
            detail = "configured" if mongo_creds else "skipped"
            self.telemetry.log_step(current_step, "success", detail)

            # Web setup (domain, SSL, nginx)
            domain = None
            port = default_port
            if needs_web:
                current_step = "web_setup"
                has_domain = input("Do you have a domain name for this instance? (y/n): ").strip().lower()
                if has_domain == "y":
                    domain, port, email = self._setup_web(instance_name, default_port, extracted_path, context)
                    context.domain = domain
                    context.email = email
                    context.port = port
                    self.telemetry.log_step(current_step, "success", f"{domain}:{port}")
                else:
                    # Let user pick a port but skip domain/nginx/SSL
                    port = self._select_available_port(default_port)
                    context.port = port
                    context.domain_skipped = True
                    self.config.persist_app_port(extracted_path, port)
                    self.firewall.open_port(port, instance_name)
                    context.opened_port = port
                    self.printer.warning("Domain setup skipped. You can set it up later with:")
                    self.printer.step(f"  plex tool setupdomain {instance_name}")
                    self.telemetry.log_step(current_step, "success", f"domain_skipped, port:{port}")

            # Dashboard setup for PlexTickets
            if has_dashboard:
                current_step = "dashboard"
                self._install_dashboard(extracted_path)
                self.telemetry.log_step(current_step, "success")

            # Systemd service
            current_step = "systemd"
            context.service_created = self._setup_systemd(instance_name, extracted_path)
            self.telemetry.log_step(current_step, "success")

            # Post-install self-tests
            current_step = "self_tests"
            results = (
                self.health.run_post_install_self_tests(
                    context,
                    mongo_creds=mongo_creds,
                    config=self.config,
                    mongo_manager=self.mongo_manager,
                )
                if self.health is not None
                else []
            )
            failed = [r for r in results if r.status == "fail"]
            warned = [r for r in results if r.status == "warn"]
            if failed:
                self.telemetry.log_step(current_step, "failure", f"failures={len(failed)} warnings={len(warned)}")
            elif warned:
                self.telemetry.log_step(current_step, "warning", f"warnings={len(warned)}")
            else:
                self.telemetry.log_step(current_step, "success")

            self._write_resource_manifest(context)

            if failed:
                self.printer.error(f"{product} is installed but unhealthy: {len(failed)} required self-test(s) failed")
                self.telemetry.finish_session("failure", "self_tests", f"failures={len(failed)}")
                return False

            # Post-installation
            current_step = "post_install"
            self._post_install(instance_name, extracted_path, domain, needs_web)
            self.telemetry.log_step(current_step, "success")

            self.printer.success(f"{product} installed successfully!")
            self.telemetry.finish_session("success")
            return True
        except KeyboardInterrupt:
            self.printer.warning("\nInstallation cancelled by user")
            if self.telemetry:
                self.telemetry.log_step(current_step, "uncompleted")
                self.telemetry.finish_session("uncompleted", current_step, "User interrupted")
            if context:
                self._cleanup_failed_install(context)
        except UserAbortError as e:
            self.printer.warning(f"Installation not completed: {e}")
            if self.telemetry:
                self.telemetry.log_step(current_step, "uncompleted", str(e))
                self.telemetry.finish_session("uncompleted", current_step, str(e))
            if context:
                self._cleanup_failed_install(context)
        except Exception as e:
            self.printer.error(f"Installation failed: {e}")
            failure_url = None
            if self.telemetry:
                self.telemetry.finish_session("failure", current_step, str(e))
                failure_url = self.telemetry.share_log()
            if context:
                self._cleanup_failed_install(context)
            if failure_url:
                self.printer.warning(f"Failure log uploaded: {failure_url}")
                self.printer.step(
                    "Please open an issue at https://github.com/Bali0531-RC/plexinstaller/issues and include the log URL."
                )
            else:
                self.printer.step(
                    "Please open an issue at https://github.com/Bali0531-RC/plexinstaller/issues with the console output above."
                )
        finally:
            pass
        return False

    def _handle_multi_instance(self, product: str) -> str:
        """Handle multi-instance installations"""
        canonical_product = self.config.canonical_product_name(product)
        existing_instances = []
        if self.config.install_dir.exists():
            existing_instances = [
                path
                for path in self.config.install_dir.iterdir()
                if path.is_dir()
                and path.name != "backups"
                and self.config.canonical_product_name(path.name) == canonical_product
            ]

        if existing_instances:
            self.printer.warning(
                f"Found existing installation(s): {', '.join(sorted(p.name for p in existing_instances))}"
            )
            choice = input("Install another instance (multi-instance)? (y/n): ").strip().lower()

            if choice == "y":
                import random
                import string

                suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
                default_name = f"{canonical_product}-{suffix}"

                instance_name = input(f"Enter unique instance name (default: {default_name}): ").strip()
                if not instance_name:
                    instance_name = default_name

                # Validate instance name
                validate_path_component(instance_name, label="instance name")
                if not re.fullmatch(r"[A-Za-z0-9_-]+", instance_name):
                    raise ValueError("Invalid instance name. Use only letters, numbers, dash, underscore")
                if (self.config.install_dir / instance_name).exists():
                    raise UserAbortError(f"Instance '{instance_name}' already exists")

                self.printer.success(f"Installing {product} as instance: {instance_name}")
                return instance_name

            raise UserAbortError("Existing installation preserved; multi-instance install declined")

        return canonical_product

    def _find_archive(self, product: str) -> Path | None:
        """Find product archive file"""
        self.printer.step(f"Searching for {product} archive...")

        trusted_roots = (Path.home(), Path.home() / "Downloads", Path.cwd())
        search_dirs: list[Path] = []
        seen_roots: set[str] = set()
        for candidate in trusted_roots:
            try:
                resolved_root = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            if any(resolved_root == root or root in resolved_root.parents for root in _SYSTEM_TEMP_ROOTS):
                continue
            key = os.path.normcase(str(resolved_root))
            if key not in seen_roots:
                seen_roots.add(key)
                search_dirs.append(resolved_root)

        archives = []
        seen_paths = set()
        product_names = self.config.equivalent_product_names(product)
        patterns = ["*.zip", "*.rar", "*.tar", "*.tar.gz", "*.tgz", "*.tar.bz2", "*.tbz2", "*.tar.xz", "*.txz"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for pattern in patterns:
                for archive in search_dir.rglob(pattern):
                    if any(name in archive.name.lower() for name in product_names):
                        resolved = archive.resolve()
                        if any(resolved == root or root in resolved.parents for root in _SYSTEM_TEMP_ROOTS):
                            continue
                        if str(resolved) in seen_paths:
                            continue
                        seen_paths.add(str(resolved))
                        archives.append(resolved)

        if not archives:
            self.printer.warning("No archives found automatically")
            path = input("Enter full path to archive file: ").strip()
            archive_path = Path(path)
            if archive_path.exists():
                return archive_path
            else:
                self.printer.error(f"File not found: {path}")
                return None

        # Display found archives
        print("\nFound archives:")
        for i, archive in enumerate(archives, 1):
            size = archive.stat().st_size / (1024 * 1024)  # MB
            print(f"{i}) {archive} ({size:.1f} MB)")
        print("0) Enter custom path")

        choice = input("\nSelect archive: ").strip()

        if choice == "0":
            path = input("Enter full path: ").strip()
            return Path(path) if Path(path).exists() else None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(archives):
                return archives[idx]
        except ValueError:
            pass

        self.printer.error("Invalid choice")
        return None

    def _extract_product(self, archive_path: Path, instance_name: str) -> Path | None:
        """Extract product archive"""
        target_dir = self.config.install_dir / instance_name

        validate_path_component(instance_name, label="instance name")
        if target_dir.exists():
            self.printer.error(f"Refusing to overwrite existing install path: {target_dir}")
            return None

        self.printer.step(f"Extracting to {target_dir}")

        try:
            extracted_path = self.extractor.extract(archive_path, target_dir)
            self.printer.success(f"Extracted to {extracted_path}")
            return extracted_path
        except Exception as e:
            self.printer.error(f"Extraction failed: {e}")
            return None

    def _install_npm_dependencies(self, install_path: Path) -> bool:
        """Install NPM dependencies"""
        package_json = install_path / "package.json"

        if not package_json.exists():
            self.printer.error(f"No package.json found in {install_path}")
            return False

        self.printer.step("Installing NPM dependencies...")

        try:
            subprocess.run(
                ["npm.cmd", "install", "--loglevel=error"],
                cwd=install_path,
                check=True,
                capture_output=True,
                timeout=300,
            )
            self.printer.success("NPM dependencies installed")
            return True
        except subprocess.CalledProcessError as e:
            if isinstance(e.stderr, bytes):
                detail = e.stderr.decode(errors="replace").strip()
            elif isinstance(e.stderr, str):
                detail = e.stderr.strip()
            else:
                detail = ""
            self.printer.error(f"NPM install failed: {detail or str(e)}")
            return False

    def _create_502_page(self, install_path: Path, product: str):
        """Create custom 502 error page"""
        error_page = install_path / "502.html"

        html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Service Temporarily Unavailable</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
        }
        .container {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 3rem;
            text-align: center;
            max-width: 500px;
        }
        h1 { font-size: 3rem; margin-bottom: 1rem; }
        .retry-btn {
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: 1px solid rgba(255, 255, 255, 0.3);
            padding: 12px 24px;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>502</h1>
        <h2>Service Temporarily Unavailable</h2>
        <p>The PlexDevelopment service is starting up. Please wait...</p>
        <a href="javascript:window.location.reload()" class="retry-btn">🔄 Retry</a>
    </div>
    <script>setTimeout(function(){ window.location.reload(); }, 30000);</script>
</body>
</html>"""

        error_page.write_text(html_content)
        self.printer.success("Created 502 error page")

    def _setup_web(
        self, instance_name: str, default_port: int, install_path: Path, context: InstallationContext
    ) -> tuple[str, int, str]:
        """Setup web server (nginx, SSL) with validation and context tracking."""

        port = self._select_available_port(default_port)

        # Get domain with format validation
        domain_pattern = re.compile(
            r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        )
        domain = ""
        while not domain:
            domain = input(f"Enter domain (e.g., {instance_name}.example.com): ").strip()
            if not domain:
                self.printer.error("Domain cannot be empty")
            elif not domain_pattern.match(domain):
                self.printer.error("Invalid domain format. Please enter a valid domain.")
                domain = ""

        # Get email with format validation
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        email = ""
        while not email:
            email = input("Enter email for SSL certificates: ").strip()
            if not email:
                self.printer.error("Email cannot be empty")
            elif not email_pattern.match(email):
                self.printer.error("Invalid email format. Please enter a valid email.")
                email = ""

        context.opened_port = port
        context.domain = domain
        context.email = email
        self.config.persist_app_port(install_path, port)
        self.firewall.open_port(port, instance_name)

        # Check DNS
        if not self.dns_checker.check(domain):
            proceed = input("DNS check failed. Proceed anyway? (y/n): ").strip().lower()
            if proceed != "y":
                raise UserAbortError("Installation aborted due to DNS issues")

        # Setup nginx
        nginx_config = self.config.nginx_available / f"{domain}.conf"
        nginx_enabled = self.config.nginx_enabled / f"{domain}.conf"
        if nginx_config.exists() or nginx_enabled.exists():
            raise UserAbortError(f"Nginx configuration already exists for {domain}")

        context.nginx_paths_created = True
        try:
            self.nginx.setup(domain, port, instance_name, install_path)
            context.nginx_configured = True

            # Setup SSL
            self.ssl.setup(domain, email)
            context.ssl_configured = True
        except Exception:
            self._remove_nginx_config(domain)
            context.nginx_configured = False
            raise

        return domain, port, email

    def _select_available_port(self, default_port: int) -> int:
        """Prompt for and verify a port before committing configuration."""
        while True:
            raw = input(f"Enter port (default: {default_port}): ").strip() or str(default_port)
            if raw.isdigit() and 1 <= int(raw) <= 65535:
                port = int(raw)
                if self.config.is_port_available(port):
                    return port
                self.printer.error(f"Port {port} is already in use. Choose another port.")
            else:
                self.printer.error("Port must be a number between 1 and 65535.")

    def _install_dashboard(self, install_path: Path):
        """Install PlexTickets dashboard addon"""
        self.printer.header("Installing Dashboard Addon")

        # Find dashboard archive
        dashboard_archive = self._find_archive("dashboard")
        if not dashboard_archive:
            self.printer.warning("Dashboard archive not found, skipping")
            return

        # Extract to addons directory
        dashboard_path = install_path / "addons" / "Dashboard"
        extracted = self.extractor.extract(dashboard_archive, dashboard_path)

        if extracted:
            self._install_npm_dependencies(extracted)
            self.printer.success("Dashboard addon installed")

    def _setup_systemd(self, instance_name: str, install_path: Path) -> bool:
        """Setup Windows service"""
        choice = input(f"Set up '{instance_name}' to auto-start on boot? (y/n): ").strip().lower()

        if choice == "y":
            if not self.systemd.create_service(instance_name, install_path):
                raise RuntimeError(f"Failed to create Windows service plex-{instance_name}")
            self.printer.success("Windows service configured")
            return True
        else:
            self.printer.warning("Auto-start not configured")
            return False

    def _post_install(self, instance_name: str, install_path: Path, domain: str | None, needs_web: bool):
        """Post-installation tasks"""
        # Find config file
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))

        if config_files:
            config_file = config_files[0]
            self.printer.step(f"Configuration file: {config_file}")

            choice = input("Edit configuration now? (y/n): ").strip().lower()
            if choice == "y":
                editor = os.environ.get("EDITOR", "notepad")
                subprocess.run([*shlex.split(editor), str(config_file)])
                self.printer.step(f"Restart service: nssm restart plex-{instance_name}")

        # Display access information
        if needs_web and domain:
            self.printer.success(f"Access at: https://{domain}")
        elif needs_web and not domain:
            self.printer.warning("No domain configured. The app is accessible on its port directly.")
            self.printer.step(f"Set up a domain later with: plex tool setupdomain {instance_name}")

        print(f"\nManage service: nssm [start|stop|restart] plex-{instance_name}")
        print("View logs: Check Windows Event Viewer or application log files")

    def _cleanup_failed_install(self, context: InstallationContext):
        """Attempt to roll back artifacts from a failed installation."""
        self.printer.warning("Rolling back partial installation...")

        try:
            if context.service_created:
                self.systemd.remove_service(f"plex-{context.instance_name}")
        except Exception as exc:
            self.printer.warning(f"Could not remove systemd service: {exc}")

        if context.nginx_paths_created and context.domain:
            self._remove_nginx_config(context.domain)

        if context.ssl_configured and context.domain:
            self._remove_ssl_certificate(context.domain)

        if context.install_path_created and context.install_path and context.install_path.exists():
            try:
                shutil.rmtree(context.install_path, ignore_errors=True)
                self.printer.step(f"Removed {context.install_path}")
            except Exception as exc:
                self.printer.warning(f"Failed to remove install directory: {exc}")

        if context.opened_port:
            self.firewall.close_port(context.opened_port, context.instance_name)

        if context.mongo_identity and self.mongo_manager is not None:
            database = context.mongo_identity.get("database", "")
            username = context.mongo_identity.get("username", "")
            try:
                if database and username:
                    self.mongo_manager.cleanup_identity(database, username, drop_database=False)
                self.mongo_manager.remove_saved_credentials(context.instance_name)
            except Exception as exc:
                self.printer.warning(f"Could not fully roll back MongoDB resources: {exc}")

    def _remove_nginx_config(self, domain: str):
        try:
            self.nginx.remove(domain)
        except Exception as exc:
            self.printer.warning(f"Failed to remove nginx config: {exc}")

    def _remove_ssl_certificate(self, domain: str):
        try:
            if self.ssl.delete(domain):
                self.printer.step(f"Removed SSL certificate for {domain}")
            else:
                self.printer.warning("Could not remove SSL certificate (may not have been issued)")
        except (OSError, subprocess.SubprocessError):
            self.printer.warning("Could not remove SSL certificate (may not have been issued)")

    def _manage_installations(self):
        """Manage existing installations"""
        self.printer.header("Manage Installations")

        # List installed products
        install_dir = self.config.install_dir
        if not install_dir.exists():
            self.printer.warning(f"No installations found in {install_dir}")
            return

        products = [d for d in install_dir.iterdir() if d.is_dir() and d.name != "backups"]

        if not products:
            self.printer.warning("No installed products found")
            return

        print("\nInstalled products:")
        for i, product in enumerate(products, 1):
            service_name = f"plex-{product.name}"
            status = self.systemd.get_status(service_name)
            print(f"{i}) {product.name} - {status}")
        print("0) Back")

        choice = input("\nSelect product to manage: ").strip()

        if choice == "0":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(products):
                self._manage_product(products[idx].name)
        except ValueError:
            self.printer.error("Invalid choice")

    def _manage_product(self, product: str):
        """Manage a specific product"""
        service_name = f"plex-{product}"

        while True:
            self.printer.header(f"Managing: {product}")
            print(f"\nService: {service_name}")
            print(f"Status: {self.systemd.get_status(service_name)}")
            print("\n1) Start")
            print("2) Stop")
            print("3) Restart")
            print("4) View Logs")
            print("5) Edit Configuration")
            print("6) Uninstall")
            print("0) Back")

            choice = input("\nChoice: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.systemd.start(service_name)
            elif choice == "2":
                self.systemd.stop(service_name)
            elif choice == "3":
                self.systemd.restart(service_name)
            elif choice == "4":
                self.systemd.view_logs(service_name)
            elif choice == "5":
                self._edit_config(product)
            elif choice == "6":
                if self._uninstall_product(product):
                    break

    def _edit_config(self, product: str):
        """Edit product configuration"""
        install_path = self.config.install_dir / product
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))

        if config_files:
            editor = os.environ.get("EDITOR", "notepad")
            subprocess.run([*shlex.split(editor), str(config_files[0])])
            self.printer.step(f"Restart service: nssm restart plex-{product}")
        else:
            self.printer.warning("No configuration file found")

    def _uninstall_product(self, product: str):
        """Uninstall a product"""
        try:
            validate_path_component(product, label="installation name")
        except ValueError:
            self.printer.error("Invalid installation name")
            return False
        if not re.fullmatch(r"[A-Za-z0-9_-]+", product):
            self.printer.error("Invalid installation name")
            return False
        install_path = self.config.install_dir / product
        try:
            install_path.resolve().relative_to(self.config.install_dir.resolve())
        except ValueError:
            self.printer.error("Refusing to uninstall a path outside the installation directory")
            return False

        confirm = input(f"Uninstall {product}? This will remove all files. (y/n): ").strip().lower()

        if confirm != "y":
            return False

        manifest = self._load_resource_manifest(install_path, product)
        service_name = str(manifest.get("service") or f"plex-{product}")

        # Stop and remove service
        try:
            self.systemd.stop(service_name)
            self.systemd.remove_service(service_name)
        except Exception as exc:
            self.printer.warning(f"Could not remove service {service_name}: {exc}")

        port = manifest.get("firewall_port")
        if isinstance(port, int):
            try:
                description = str(manifest.get("firewall_description") or product)
                self.firewall.close_port(port, description)
            except Exception as exc:
                self.printer.warning(f"Could not remove firewall rule for {port}: {exc}")

        domain = manifest.get("domain")
        if isinstance(domain, str) and domain:
            if manifest.get("nginx"):
                self._remove_nginx_config(domain)
            if manifest.get("certificate"):
                self._remove_ssl_certificate(domain)

        mongo = manifest.get("mongodb") or {}
        if self.mongo_manager is not None and isinstance(mongo, dict):
            database = str(mongo.get("database") or "")
            username = str(mongo.get("username") or "")
            removed = True
            if database and username:
                removed = self.mongo_manager.cleanup_identity(database, username, drop_database=False)
            if removed:
                self.mongo_manager.remove_saved_credentials(product)

        # Remove installation directory
        if install_path.exists():
            shutil.rmtree(install_path)
            self.printer.success(f"Removed {install_path}")

        self.printer.success(f"{product} uninstalled")
        return True

    def _write_resource_manifest(self, context: InstallationContext) -> Path:
        """Persist resources owned by one instance for deterministic uninstall."""
        manifest = {
            "schema_version": 1,
            "instance": context.instance_name,
            "product": context.product,
            "install_path": str(context.install_path.resolve()),
            "port": context.port,
            "firewall_port": context.opened_port,
            "firewall_description": context.instance_name if context.opened_port else None,
            "domain": context.domain,
            "nginx": context.nginx_configured,
            "certificate": context.ssl_configured,
            "service": f"plex-{context.instance_name}" if context.service_created else None,
            "mongodb": context.mongo_identity or {},
        }
        path = context.install_path / RESOURCE_MANIFEST
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
        try:
            fd = os.open(str(temporary), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(manifest, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def _load_resource_manifest(self, install_path: Path, instance_name: str) -> dict[str, Any]:
        """Load a validated manifest, using conservative legacy defaults."""
        path = install_path / RESOURCE_MANIFEST
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("instance") != instance_name:
                    raise ValueError("manifest instance mismatch")
                if Path(str(data.get("install_path", install_path))).resolve() != install_path.resolve():
                    raise ValueError("manifest path mismatch")
                service = data.get("service")
                if service not in {None, f"plex-{instance_name}"}:
                    raise ValueError("manifest service mismatch")
                port = data.get("firewall_port")
                if port is not None and (not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535):
                    raise ValueError("manifest firewall port is invalid")
                mongo = data.get("mongodb") or {}
                if not isinstance(mongo, dict):
                    raise ValueError("manifest MongoDB identity is invalid")
                return data
            except (OSError, ValueError, json.JSONDecodeError):
                self.printer.warning(f"Could not read resource manifest {path}; using safe defaults")
        return {
            "schema_version": 0,
            "instance": instance_name,
            "install_path": str(install_path),
            "service": f"plex-{instance_name}",
            "mongodb": {},
        }

    def _ssl_management_menu(self):
        """SSL certificate management menu"""
        while True:
            clear_terminal()
            self.printer.header("SSL Certificate Management")

            print("\n1) View SSL Certificate Status")
            print("2) View SSL Renewal Logs")
            print("3) Setup/Update SSL Auto-Renewal")
            print("4) Force SSL Certificate Renewal")
            print("5) Test SSL Certificate Renewal (Dry Run)")
            print("0) Back to Main Menu")

            choice = input("\nEnter your choice: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self._show_ssl_status()
            elif choice == "2":
                self._view_ssl_logs()
            elif choice == "3":
                self.ssl.setup_auto_renewal()
            elif choice == "4":
                self._force_ssl_renewal()
            elif choice == "5":
                self._test_ssl_renewal()
            else:
                self.printer.error("Invalid choice")

            if choice != "0":
                input("\nPress Enter to continue...")

    def _show_ssl_status(self):
        """Show SSL certificate status"""
        self.printer.step("Checking SSL certificates...")
        try:
            self.ssl.status()
        except OSError as exc:
            self.printer.warning(str(exc))

    def _view_ssl_logs(self):
        """View SSL renewal logs"""
        try:
            self.ssl.view_logs()
        except OSError as exc:
            self.printer.warning(str(exc))

    def _force_ssl_renewal(self):
        """Force SSL certificate renewal"""
        self.printer.warning("This will attempt to renew ALL SSL certificates immediately.")
        confirm = input("Are you sure you want to continue? (y/n): ").strip().lower()

        if confirm == "y":
            self.printer.step("Forcing SSL certificate renewal...")
            try:
                self.ssl.renew(force=True)
                self.printer.success("SSL certificates renewed successfully!")
                self.printer.step("Reloading Nginx...")
                nginx = shutil.which("nginx")
                if nginx:
                    subprocess.run([nginx, "-s", "reload"], check=False, timeout=30)
            except (OSError, subprocess.SubprocessError):
                self.printer.error("SSL certificate renewal failed")
        else:
            self.printer.step("SSL renewal cancelled")

    def _test_ssl_renewal(self):
        """Test SSL certificate renewal (dry run)"""
        self.printer.step("Running SSL renewal test (dry run)...")
        try:
            self.ssl.test_renewal()
            self.printer.success("SSL renewal test successful! All certificates can be renewed.")
        except (OSError, subprocess.SubprocessError):
            self.printer.error("SSL renewal test failed. Check output above for details.")

    # ========== ADDON MANAGEMENT ==========

    def _manage_addons_menu(self):
        """Main addon management menu"""
        # Check if addon manager is available
        if not self.addon_manager:
            self.printer.header("Addon Management")
            self.printer.warning("Addon manager module not available.")
            self.printer.step("This can happen after an update from an older version.")
            self.printer.step("Please restart the installer to complete the update.")
            return

        while True:
            clear_terminal()
            self.printer.header("Addon Management")
            print("Manage addons for PlexTickets and PlexStaff installations\n")

            # Find products that support addons
            addon_products = self._get_addon_supported_products()

            if not addon_products:
                self.printer.warning("No PlexTickets or PlexStaff installations found.")
                self.printer.step("Install PlexTickets or PlexStaff first to manage addons.")
                return

            print("Select a product to manage addons:")
            for i, (name, path) in enumerate(addon_products, 1):
                addons = self.addon_manager.list_addons(path)
                addon_count = len(addons)
                status = self.systemd.get_status(f"plex-{name}")
                print(f"{i}) {name} - {addon_count} addon(s) installed - Service: {status}")
            print("0) Back to Main Menu")

            choice = input("\nEnter your choice: ").strip()

            if choice == "0":
                break

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(addon_products):
                    product_name, product_path = addon_products[idx]
                    self._manage_product_addons(product_name, product_path)
            except ValueError:
                self.printer.error("Invalid choice")

            if choice != "0":
                input("\nPress Enter to continue...")

    def _get_addon_supported_products(self) -> list[tuple[str, Path]]:
        """Get list of installed products that support addons"""
        products: list[tuple[str, Path]] = []

        if not self.config.install_dir.exists():
            return products

        for product_dir in self.config.install_dir.iterdir():
            if product_dir.is_dir() and product_dir.name != "backups":
                # Check if this product type supports addons
                base_product = self.config.instance_product_base(product_dir.name)
                product_config = self.config.get_product(base_product)

                if product_config and getattr(product_config, "supports_addons", False):
                    products.append((product_dir.name, product_dir))

        return sorted(products)

    def _manage_product_addons(self, product_name: str, product_path: Path):
        """Manage addons for a specific product"""
        while True:
            clear_terminal()
            self.printer.header(f"Addons for {product_name}")

            addons = self.addon_manager.list_addons(product_path)

            if addons:
                print("\nInstalled Addons:")
                print(f"{'#':<4} {'Name':<25} {'Config':<15}")
                print("-" * 50)
                for i, addon in enumerate(addons, 1):
                    config_status = addon["config_path"].name if addon["has_config"] else "No config"
                    print(f"{i:<4} {addon['name']:<25} {config_status:<15}")
            else:
                print("\nNo addons installed yet.")

            print("\n" + "-" * 50)
            print("1) Install new addon")
            print("2) Remove addon")
            print("3) Configure addon")
            print("4) View addon backups")
            print("0) Back")

            choice = input("\nEnter your choice: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self._install_addon(product_name, product_path)
            elif choice == "2":
                self._remove_addon(product_name, product_path, addons)
            elif choice == "3":
                self._configure_addon(product_name, product_path, addons)
            elif choice == "4":
                self._view_addon_backups(product_name, product_path)
            else:
                self.printer.error("Invalid choice")

            if choice != "0":
                input("\nPress Enter to continue...")

    def _install_addon(self, product_name: str, product_path: Path):
        """Install an addon for a product"""
        self.printer.header(f"Install Addon for {product_name}")

        # Search for addon archives
        self.printer.step("Searching for addon archives...")
        archives = self.addon_manager.find_addon_archive()

        if not archives:
            self.printer.warning("No addon archives (.zip/.rar) found automatically")
            path = input("Enter full path to addon archive: ").strip()
            if not path:
                return
            archive_path = Path(path)
            if not archive_path.exists():
                self.printer.error(f"File not found: {path}")
                return
        else:
            # Filter to show reasonable number of results
            print("\nFound archives:")
            display_archives = archives[:20]  # Limit display
            for i, archive in enumerate(display_archives, 1):
                size = archive.stat().st_size / (1024 * 1024)
                print(f"{i}) {archive.name} ({size:.1f} MB) - {archive.parent}")

            if len(archives) > 20:
                print(f"... and {len(archives) - 20} more")
            print("0) Enter custom path")

            choice = input("\nSelect archive: ").strip()

            if choice == "0":
                path = input("Enter full path: ").strip()
                if not path:
                    return
                archive_path = Path(path)
                if not archive_path.exists():
                    self.printer.error(f"File not found: {path}")
                    return
            else:
                try:
                    idx = int(choice) - 1
                    if 0 <= idx < len(display_archives):
                        archive_path = display_archives[idx]
                    else:
                        self.printer.error("Invalid choice")
                        return
                except ValueError:
                    self.printer.error("Invalid choice")
                    return

        # Check what the addon name would be (for collision check)
        potential_name = archive_path.stem
        for suffix in ["-main", "-master", "-addon", "-v1", "-v2"]:
            if potential_name.lower().endswith(suffix):
                potential_name = potential_name[: -len(suffix)]

        if self.addon_manager.addon_exists(potential_name, product_path):
            self.printer.error(f"An addon named '{potential_name}' already exists.")
            self.printer.step("Remove the existing addon first if you want to reinstall.")
            return

        # Install the addon
        success, message, addon_name = self.addon_manager.install_addon(archive_path, product_path)

        if success:
            self.printer.success(message)

            # Prompt for service restart
            service_name = f"plex-{product_name}"
            status = self.systemd.get_status(service_name)

            if status.strip().lower() == "active":
                restart = input("\nRestart service now to apply addon? (y/n): ").strip().lower()
                if restart == "y":
                    self.systemd.restart(service_name)
                    self.printer.success(f"Service {service_name} restarted")
                else:
                    self.printer.step(f"Remember to restart the service: nssm restart {service_name}")
        else:
            self.printer.error(message)

    def _remove_addon(self, product_name: str, product_path: Path, addons: list[dict]):
        """Remove an addon from a product"""
        if not addons:
            self.printer.warning("No addons installed to remove")
            return

        self.printer.header(f"Remove Addon from {product_name}")

        print("\nSelect addon to remove:")
        for i, addon in enumerate(addons, 1):
            print(f"{i}) {addon['name']}")
        print("0) Cancel")

        choice = input("\nEnter your choice: ").strip()

        if choice == "0":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(addons):
                addon = addons[idx]
                addon_name = addon["name"]

                self.printer.warning(f"You are about to remove addon: {addon_name}")

                # Ask about backup
                backup_choice = input("Create backup before removal? (Y/n): ").strip().lower()
                backup_first = backup_choice != "n"

                confirm = input(f"Confirm removal of '{addon_name}'? (y/n): ").strip().lower()

                if confirm == "y":
                    success, message = self.addon_manager.remove_addon(
                        addon_name, product_path, backup_first=backup_first
                    )

                    if success:
                        self.printer.success(message)

                        # Prompt for service restart
                        service_name = f"plex-{product_name}"
                        status = self.systemd.get_status(service_name)

                        if status.strip().lower() == "active":
                            restart = input("\nRestart service now? (y/n): ").strip().lower()
                            if restart == "y":
                                self.systemd.restart(service_name)
                                self.printer.success(f"Service {service_name} restarted")
                    else:
                        self.printer.error(message)
                else:
                    self.printer.step("Removal cancelled")
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid input")

    def _configure_addon(self, product_name: str, product_path: Path, addons: list[dict]):
        """Configure an addon's config.yml/yaml file"""
        # Filter to addons with config files
        configurable_addons = [a for a in addons if a["has_config"]]

        if not configurable_addons:
            self.printer.warning("No addons with configuration files found")
            return

        self.printer.header(f"Configure Addon for {product_name}")

        print("\nSelect addon to configure:")
        for i, addon in enumerate(configurable_addons, 1):
            print(f"{i}) {addon['name']} ({addon['config_path'].name})")
        print("0) Cancel")

        choice = input("\nEnter your choice: ").strip()

        if choice == "0":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(configurable_addons):
                addon = configurable_addons[idx]
                config_path = addon["config_path"]

                self.printer.step(f"Opening {config_path.name} for editing...")
                self.printer.warning("Save and exit the editor when done")

                # Open in editor
                editor = os.environ.get("EDITOR", "notepad")
                subprocess.run([*shlex.split(editor), str(config_path)])

                # Validate YAML after editing
                is_valid, error = self.addon_manager.validate_yaml(config_path)

                if is_valid:
                    self.printer.success("Configuration file is valid YAML")
                else:
                    self.printer.error(f"YAML syntax error: {error}")
                    self.printer.warning("The configuration may not work correctly until fixed")

                    fix_choice = input("Open editor again to fix? (y/n): ").strip().lower()
                    if fix_choice == "y":
                        subprocess.run([*shlex.split(editor), str(config_path)])
                        is_valid, error = self.addon_manager.validate_yaml(config_path)
                        if is_valid:
                            self.printer.success("Configuration file is now valid YAML")
                        else:
                            self.printer.error(f"Still invalid: {error}")

                # Prompt for service restart
                service_name = f"plex-{product_name}"
                status = self.systemd.get_status(service_name)

                if status.strip().lower() == "active":
                    restart = input("\nRestart service to apply changes? (y/n): ").strip().lower()
                    if restart == "y":
                        self.systemd.restart(service_name)
                        self.printer.success(f"Service {service_name} restarted")
                    else:
                        self.printer.step(f"Remember to restart: nssm restart {service_name}")
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid input")

    def _view_addon_backups(self, product_name: str, product_path: Path):
        """View and optionally restore addon backups"""
        self.printer.header(f"Addon Backups for {product_name}")

        backups = self.addon_manager.list_addon_backups(product_path)

        if not backups:
            self.printer.warning("No addon backups found")
            return

        print("\nAvailable Addon Backups:")
        print(f"{'#':<4} {'Addon':<20} {'Date':<20} {'Size':<10}")
        print("-" * 60)

        for i, backup in enumerate(backups, 1):
            date_str = backup["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"{i:<4} {backup['addon_name']:<20} {date_str:<20} {backup['size_mb']:>8.2f} MB")

        print("\nOptions:")
        print("Enter backup number to restore, or 0 to go back")

        choice = input("\nEnter your choice: ").strip()

        if choice == "0":
            return

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                backup = backups[idx]

                self.printer.warning(f"This will restore addon '{backup['addon_name']}' from backup")

                # Check if addon currently exists
                if self.addon_manager.addon_exists(backup["addon_name"], product_path):
                    self.printer.warning("Current addon will be replaced!")

                confirm = input("Continue with restore? (y/n): ").strip().lower()

                if confirm == "y":
                    self._restore_addon_backup(product_name, product_path, backup)
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid input")

    def _restore_addon_backup(self, product_name: str, product_path: Path, backup: dict):
        """Restore an addon from backup"""
        try:
            from utils import install_staged_directory, safe_extract_tar

            addon_name = validate_path_component(str(backup["addon_name"]), label="addon name")
            backup_path = Path(backup["path"])
            addons_path = self.addon_manager.get_addons_path(product_path)
            addon_path = addons_path / addon_name
            rollback_path: Path | None = None
            self.printer.step("Restoring from backup...")
            addons_path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f".{addon_name}.restore-", dir=addons_path) as temp_dir:
                extraction_root = Path(temp_dir) / "archive"
                safe_extract_tar(backup_path, extraction_root, expected_top_level=addon_name)
                staged_addon = extraction_root / addon_name
                self.addon_manager._set_permissions(staged_addon)
                if addon_path.exists() or addon_path.is_symlink():
                    rollback_path = Path(temp_dir) / "previous"
                    addon_path.rename(rollback_path)
                try:
                    install_staged_directory(staged_addon, addon_path)
                except Exception:
                    if rollback_path is not None and rollback_path.exists() and not addon_path.exists():
                        rollback_path.rename(addon_path)
                    raise

            self.printer.success(f"Addon '{addon_name}' restored successfully")

            # Prompt for service restart
            service_name = f"plex-{product_name}"
            status = self.systemd.get_status(service_name)

            if status.strip().lower() == "active":
                restart = input("\nRestart service now? (y/n): ").strip().lower()
                if restart == "y":
                    self.systemd.restart(service_name)
                    self.printer.success(f"Service {service_name} restarted")

        except Exception as e:
            self.printer.error(f"Restore failed: {e}")

    # ========== END ADDON MANAGEMENT ==========


def main():
    """Entry point"""
    setup_logging()

    # Determine version from command line or environment
    version = os.environ.get("PLEX_INSTALLER_VERSION", "stable")

    installer = PlexInstaller(version=version)
    installer.run()


if __name__ == "__main__":
    main()
