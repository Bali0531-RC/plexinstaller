#!/usr/bin/env python3
"""
PlexDevelopment Products Installer - Python Version
Modular, maintainable installer for Plex products
"""

import argparse
import atexit
import fcntl
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
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    install_staged_directory,
    safe_extract_tar,
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
    INSTALLER_DIR = Path("/opt/plexinstaller")
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
INSTALLER_VERSION = "3.3.1"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json"
LOCK_FILE = "/var/run/plexinstaller.lock"
RESOURCE_MANIFEST = ".plexinstaller-resources.json"
_SYSTEM_TEMP_ROOTS = frozenset(path.resolve() for path in (Path(tempfile.gettempdir()), Path("/tmp"), Path("/var/tmp")))


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
    service_isolated: bool = False
    service_user: str | None = None
    service_user_created: bool = False


class PlexInstaller:
    """Main installer class"""

    def __init__(
        self,
        version: str = "stable",
        *,
        assume_yes: bool = False,
        non_interactive: bool = False,
        check_updates: bool = True,
        isolate_services: bool | None = None,
    ):
        self.version = version
        self.assume_yes = assume_yes
        self.non_interactive = non_interactive
        self.check_updates = check_updates
        self.isolate_services = isolate_services
        self.config = Config()
        self.printer = ColorPrinter()
        self._lock_fd: io.TextIOWrapper | None = None

        # Check root FIRST before any file operations
        if os.geteuid() != 0:
            self.printer.error("This installer must be run as root (use sudo)")
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
                mongodb_repo_version_bookworm=self.config.MONGODB_REPO_VERSION_BOOKWORM,
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
            self._lock_fd = open(LOCK_FILE, "w")
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
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
                fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
                self._lock_fd.close()
                self._lock_fd = None
                # Remove lock file
                try:
                    os.unlink(LOCK_FILE)
                except OSError:
                    pass
            except Exception:
                pass

    def run(self) -> int:
        """Main entry point"""
        clear_terminal()
        self._display_banner()

        if not self.telemetry_enabled:
            self.printer.step(f"Telemetry is disabled. Edit {self.config.telemetry_pref_file} to re-enable it.")

        if self.check_updates:
            self._check_for_updates()

        # Root already checked in __init__. Normal launches only perform a
        # preflight; dependency repair is an explicit action.
        self.system.detect()
        missing = self._missing_dependencies()
        if missing:
            self.printer.warning(f"Missing required commands: {', '.join(missing)}")
            if self._confirm("Repair/install system dependencies now?", default=False):
                self.system.install_dependencies()
            else:
                self.printer.warning("Some installer actions may be unavailable until dependencies are repaired.")

        # Main menu
        return self._show_main_menu()

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

    def _confirm(self, prompt: str, *, default: bool = False) -> bool:
        """Prompt consistently while supporting --yes and non-interactive mode."""
        if self.assume_yes:
            return True
        if self.non_interactive or not sys.stdin.isatty():
            return default
        suffix = " (Y/n): " if default else " (y/N): "
        answer = input(prompt + suffix).strip().lower()
        if not answer:
            return default
        return answer in {"y", "yes"}

    @staticmethod
    def _missing_dependencies() -> list[str]:
        """Return command-level preflight failures without changing the system."""
        required = ("node", "npm", "systemctl")
        return [command for command in required if shutil.which(command) is None]

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
            "If enabled, install diagnostics include product/instance identifiers, step details, errors, paths,"
            " domain/port choices, and generated logs. Common secrets are redacted on a best-effort basis."
        )
        enabled = self._confirm("Share installer diagnostics?", default=False)

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

            # Fetch version info
            with urllib.request.urlopen(VERSION_CHECK_URL, timeout=5) as response:
                version_json_bytes = response.read()
            version_data = json.loads(version_json_bytes.decode())

            if not self._verify_gpg_signature(version_json_bytes):
                self.printer.warning("Update manifest could not be authenticated; update check was skipped.")
                return

            remote_version = version_data.get("version", "0.0.0")

            # Compare versions
            if self._is_newer_version(remote_version, INSTALLER_VERSION):
                self.printer.warning(
                    f"New installer version available: {remote_version} (current: {INSTALLER_VERSION})"
                )
                print(f"\n{ColorPrinter.CYAN}Changelog:{ColorPrinter.NC}")
                for item in version_data.get("changelog", []):
                    print(f"  • {item}")

                if self._confirm("Auto-update to the latest version?", default=False):
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

        Uses version_data already fetched during the update check so no extra
        network round-trip is needed.  Falls back to a self-contained
        implementation when shared.py itself is unavailable (first upgrade
        from an older installer that predates shared.py).
        """
        if _shared_download_missing is not None:
            _shared_download_missing(
                print_info=self.printer.step,
                print_success=self.printer.success,
                print_warning=self.printer.warning,
                print_error=self.printer.error,
            )
            return

        del version_data
        self.printer.warning("Secure missing-file repair requires shared.py; re-run the signed bootstrap installer.")

    def _ensure_cli_entrypoints(self):
        """Ensure `plexinstaller` and `plex` commands point at the current installer bundle."""
        if _shared_ensure_cli is not None:
            _shared_ensure_cli()

    def _is_newer_version(self, remote: str, local: str) -> bool:
        """Compare version strings (semantic versioning)"""
        if _shared_is_newer is not None:
            return bool(_shared_is_newer(remote, local))
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
            self.printer.error("shared.py not available — update verification cannot continue")
            return False
        return bool(
            _shared_verify_gpg(
                version_json_bytes,
                print_info=self.printer.step,
                print_success=self.printer.success,
                print_warning=self.printer.warning,
                print_error=self.printer.error,
            )
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

    def _show_main_menu(self) -> int:
        """Display main menu and handle user choice"""
        exit_code = 0
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
            print("----------------------------------------")
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
                result = self._install_plextickets()
                exit_code = max(exit_code, result)
            elif choice == "2":
                exit_code = max(exit_code, self._install_product("plexstaff", 3001))
            elif choice == "3":
                exit_code = max(exit_code, self._install_product("drakostatus", 3002))
            elif choice == "4":
                exit_code = max(exit_code, self._install_product("drakostore", 3003))
            elif choice == "5":
                exit_code = max(exit_code, self._install_product("drakoforms", 3004))
            elif choice == "6":
                exit_code = max(exit_code, self._install_product("drakolinks", 3005))
            elif choice == "7":
                exit_code = max(exit_code, self._install_product("drakopaste", 3006))
            elif choice == "8":
                exit_code = max(exit_code, self._install_product("drakotracker", 3007))
            elif choice == "9":
                self._manage_installations()
            elif choice == "10":
                if self.backup_mgr is None:
                    self.printer.warning("Backup manager module is not available.")
                else:
                    self.backup_mgr.menu()
            elif choice == "11":
                self._manage_addons_menu()
            elif choice == "12":
                self._ssl_management_menu()
            elif choice == "13":
                if self.health is None:
                    self.printer.warning("Health checker module is not available.")
                else:
                    self.health.system_health_check()
            else:
                self.printer.error("Invalid choice")

            if choice != "0":  # pragma: no branch
                input("\nPress Enter to continue...")
        return exit_code

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
            for config_file in product_dir.glob("config.y*ml"):
                try:
                    import re

                    content = config_file.read_text()
                    match = re.search(
                        r"^[ \t]*port[ \t]*:[ \t]*(\d+)(?:[ \t]*(?:#.*)?)?$",
                        content,
                        re.IGNORECASE | re.MULTILINE,
                    )
                    if match:
                        port = match.group(1)
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

    def _install_plextickets(self) -> int:
        """Special handling for PlexTickets with dashboard option"""
        self.printer.header("PlexTickets Installation")
        print("\n1) Install with Web Dashboard (Port 3000)")
        print("2) Install Bot Only (no web interface)")
        print("0) Back")

        choice = input("\nEnter your choice: ").strip()

        if choice == "1":
            return self._install_product("plextickets", 3000, has_dashboard=True)
        elif choice == "2":
            return self._install_product("plextickets", 3000, has_dashboard=False, needs_web=False)
        elif choice == "0":
            return 0
        else:
            self.printer.error("Invalid choice")
            return 1

    def _install_product(
        self,
        product: str,
        default_port: int,
        has_dashboard: bool = False,
        needs_web: bool = True,
    ) -> int:
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
                return 1
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

            # Root remains the compatibility default. In opt-in isolated mode,
            # prepare ownership before npm lifecycle scripts execute.
            if self._isolation_requested():
                try:
                    service_user, user_created = self.systemd.prepare_service_identity(instance_name, extracted_path)
                    context.service_isolated = True
                    context.service_user = service_user
                    context.service_user_created = user_created
                    self.printer.success(f"Extra security enabled with service identity '{service_user}'")
                except Exception as exc:
                    self.printer.warning(f"Could not prepare isolated service identity ({exc}); using root mode")

            # Install NPM dependencies
            current_step = "npm_install"
            self.telemetry.log_step(current_step, "start")
            npm_ready = self._install_npm_dependencies(extracted_path, run_as_user=context.service_user)
            if not npm_ready:
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
                has_domain = self._confirm("Do you have a domain name for this instance?", default=False)
                if has_domain:
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
                self._install_dashboard(extracted_path, run_as_user=context.service_user)
                self.telemetry.log_step(current_step, "success")

            # Systemd service
            current_step = "systemd"
            try:
                context.service_created = self._setup_systemd(
                    instance_name,
                    extracted_path,
                    isolated=context.service_isolated,
                    isolated_user_created=context.service_user_created,
                    isolated_user=context.service_user,
                )
            finally:
                if getattr(self, "_last_service_identity_released", False):
                    context.service_isolated = False
                    context.service_user = None
                    context.service_user_created = False
            context.service_isolated = bool(getattr(self, "_last_service_isolated", False))
            if context.service_created and not context.service_isolated:
                context.service_user = None
                context.service_user_created = False
            if not context.service_created and context.service_user:
                self.systemd.release_service_identity(
                    instance_name,
                    extracted_path,
                    remove_user=context.service_user_created,
                    user_name=context.service_user,
                )
                context.service_user = None
                context.service_user_created = False
                context.service_isolated = False
            self.telemetry.log_step(current_step, "success")

            # Post-install self-tests
            current_step = "self_tests"
            if self.health is None:
                results = []
                self.printer.warning("Post-install health checker is unavailable; installation is not verified.")
            else:
                results = self.health.run_post_install_self_tests(
                    context,
                    mongo_creds=mongo_creds,
                    config=self.config,
                    mongo_manager=self.mongo_manager,
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
                message = f"{product} is installed but unhealthy: {len(failed)} required self-test(s) failed"
                self.printer.error(message)
                self.telemetry.finish_session("failure", "self_tests", message)
                return 2
            if self.health is None:
                message = f"{product} is installed but health is unknown because self-tests were unavailable"
                self.printer.warning(message)
                self.telemetry.finish_session("uncompleted", "self_tests", message)
                return 2

            # Post-installation
            current_step = "post_install"
            self._post_install(instance_name, extracted_path, domain, needs_web)
            self.telemetry.log_step(current_step, "success")

            self.printer.success(f"{product} installed successfully!")
            self.telemetry.finish_session("success")
            return 0
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
            if self.telemetry_enabled:
                self.telemetry.finish_session("failure", current_step, str(e))
                if self._confirm(
                    "Upload the redacted local failure log to the configured paste service for support?",
                    default=False,
                ):
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
        return 1

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
            names = ", ".join(sorted(path.name for path in existing_instances))
            self.printer.warning(f"Found existing installation(s): {names}")
            if self._confirm("Install another instance (multi-instance)?", default=False):
                suffix = secrets.token_hex(3)
                default_name = f"{canonical_product}-{suffix}"

                instance_name = (
                    ""
                    if self.non_interactive
                    else input(f"Enter unique instance name (default: {default_name}): ").strip()
                )
                if not instance_name:
                    instance_name = default_name

                # Validate instance name
                if not re.match(r"^[a-zA-Z0-9_-]+$", instance_name):
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

        home = Path.home()
        trusted_roots = (home, home / "Downloads", Path.cwd())
        search_dirs = []
        seen_roots = set()

        def is_system_temp_path(path: Path) -> bool:
            return any(path == temp_root or temp_root in path.parents for temp_root in _SYSTEM_TEMP_ROOTS)

        for candidate in trusted_roots:
            try:
                resolved_root = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            if is_system_temp_path(resolved_root):
                continue
            root_key = os.path.normcase(str(resolved_root))
            if root_key in seen_roots:
                continue
            seen_roots.add(root_key)
            search_dirs.append(resolved_root)

        archives = []
        seen_paths = set()
        product_names = self.config.equivalent_product_names(product)
        patterns = ["*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.tar.bz2", "*.tbz2", "*.tar.xz", "*.txz"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for pattern in patterns:
                for archive in search_dir.rglob(pattern):
                    if any(product_name in archive.name.lower() for product_name in product_names):
                        resolved = archive.resolve()
                        if is_system_temp_path(resolved):
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

        if target_dir.exists():
            self.printer.error(f"Refusing to overwrite existing install path: {target_dir}")
            return None

        self.printer.step(f"Extracting to {target_dir}")

        try:
            extracted_path = self.extractor.extract(archive_path, target_dir)
            self.printer.success(f"Extracted to {extracted_path}")
            return Path(extracted_path)
        except Exception as e:
            self.printer.error(f"Extraction failed: {e}")
            return None

    def _install_npm_dependencies(self, install_path: Path, *, run_as_user: str | None = None) -> bool:
        """Install NPM dependencies"""
        package_json = install_path / "package.json"

        if not package_json.exists():
            self.printer.error(f"No package.json found in {install_path}")
            return False

        self.printer.step("Installing NPM dependencies...")

        try:
            command = ["npm", "install", "--loglevel=error"]
            if run_as_user:
                command = ["runuser", "--user", run_as_user, "--", *command]
            subprocess.run(command, cwd=install_path, check=True, capture_output=True, timeout=300)
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
        os.chmod(error_page, 0o644)
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

        context.domain = domain
        context.email = email
        self.config.persist_app_port(install_path, port)

        # Check DNS
        if not self.dns_checker.check(domain):
            proceed = input("DNS check failed. Proceed anyway? (y/n): ").strip().lower()
            if proceed != "y":
                raise UserAbortError("Installation aborted due to DNS issues")

        # Setup nginx
        nginx_config = self.config.nginx_available / f"{domain}.conf"
        nginx_enabled = self.config.nginx_enabled / f"{domain}.conf"
        if nginx_config.exists() or nginx_enabled.exists() or nginx_enabled.is_symlink():
            raise UserAbortError(f"Nginx configuration already exists for {domain}")

        context.nginx_paths_created = True
        try:
            self.nginx.setup(domain, port, instance_name, install_path)
            context.nginx_configured = True

            # Setup SSL
            self.ssl.setup(domain, email)
            context.ssl_configured = True
        except Exception:
            # NginxManager can write files before raising from nginx -t.
            self._remove_nginx_config(domain)
            context.nginx_configured = False
            raise

        # The app binds locally behind nginx; only HTTP(S), managed by the
        # system's web-server rules, should be public.
        try:
            self.firewall.close_port(port)
        except Exception as exc:
            self.printer.warning(f"Could not verify removal of public app-port rule: {exc}")
        return domain, port, email

    def _select_available_port(self, default_port: int) -> int:
        """Prompt for and verify a port before any config is committed."""
        while True:
            if self.non_interactive:
                raw = str(default_port)
            else:
                raw = input(f"Enter port (default: {default_port}): ").strip() or str(default_port)
            if raw.isdigit() and 1 <= int(raw) <= 65535:
                port = int(raw)
                if self.config.is_port_available(port):
                    return port
                self.printer.error(f"Port {port} is already in use. Choose another port.")
                if self.non_interactive:
                    raise UserAbortError(f"Port {port} is already in use")
            else:
                self.printer.error("Port must be a number between 1 and 65535.")
                if self.non_interactive:
                    raise UserAbortError("Invalid port")

    def _install_dashboard(self, install_path: Path, *, run_as_user: str | None = None):
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
            if run_as_user:
                subprocess.run(["chown", "-R", f"{run_as_user}:{run_as_user}", str(extracted)], check=True)
            self._install_npm_dependencies(extracted, run_as_user=run_as_user)
            self.printer.success("Dashboard addon installed")

    def _setup_systemd(
        self,
        instance_name: str,
        install_path: Path,
        *,
        isolated: bool | None = None,
        isolated_user_created: bool = False,
        isolated_user: str | None = None,
    ) -> bool:
        """Setup systemd service"""
        self._last_service_isolated = False
        self._last_service_identity_released = False
        choice = self._confirm(f"Set up '{instance_name}' to auto-start on boot?", default=False)

        if choice:
            isolate = self._isolation_requested() if isolated is None else isolated
            if isolate:
                try:
                    self._create_systemd_service(instance_name, install_path, isolated=True)
                    self._last_service_isolated = True
                    self.printer.success("Systemd service configured with isolated service identity")
                    return True
                except Exception as exc:
                    self.printer.warning(f"Service isolation failed ({exc}); falling back to root")
                    try:
                        self.systemd.release_service_identity(
                            instance_name,
                            install_path,
                            remove_user=isolated_user_created,
                            user_name=isolated_user,
                        )
                        self._last_service_identity_released = True
                    except Exception as cleanup_exc:
                        self.printer.warning(f"Could not fully reset isolated identity: {cleanup_exc}")
            self._create_systemd_service(instance_name, install_path, isolated=False)
            self.printer.success("Systemd service configured")
            return True
        else:
            self.printer.warning("Auto-start not configured")
            return False

    def _isolation_requested(self) -> bool:
        explicit = getattr(self, "isolate_services", None)
        if explicit is not None:
            return bool(explicit)
        value = os.environ.get("PLEX_ISOLATE_SERVICES")
        if value is not None:
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return self._confirm("Use an isolated non-root service identity?", default=False)

    def _create_systemd_service(self, instance_name: str, install_path: Path, *, isolated: bool) -> None:
        """Create root-default or opt-in isolated services with legacy fallback."""
        if not isolated:
            self.systemd.create_service(instance_name, install_path)
            return
        attempts = (
            {"isolated": True},
            {"isolate": True},
            {"run_as_root": False},
        )
        unsupported: TypeError | None = None
        for kwargs in attempts:
            try:
                self.systemd.create_service(instance_name, install_path, **kwargs)
                return
            except TypeError as exc:
                unsupported = exc
        raise RuntimeError("installed SystemdManager does not support service isolation") from unsupported

    def _post_install(self, instance_name: str, install_path: Path, domain: str | None, needs_web: bool):
        """Post-installation tasks"""
        # Find config file
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))

        if config_files:
            config_file = config_files[0]
            self.printer.step(f"Configuration file: {config_file}")

            if self._confirm("Edit configuration now?", default=False):
                if not self._run_editor(config_file):
                    self.printer.warning("Configuration editor did not exit successfully")
                self.printer.step(f"Restart service: sudo systemctl restart plex-{instance_name}")

        # Display access information
        if needs_web and domain:
            self.printer.success(f"Access at: https://{domain}")
        elif needs_web and not domain:
            self.printer.warning("No domain configured. The app is accessible on its port directly.")
            self.printer.step(f"Set up a domain later with: plex tool setupdomain {instance_name}")

        print(f"\nManage service: sudo systemctl [start|stop|restart|status] plex-{instance_name}")
        print(f"View logs: sudo journalctl -u plex-{instance_name} -f")

    def _run_editor(self, path: Path) -> bool:
        """Run the configured editor safely and report launch/exit failures."""
        try:
            command = shlex.split(os.environ.get("EDITOR", "nano"))
        except ValueError as exc:
            self.printer.error(f"Invalid EDITOR value: {exc}")
            return False
        if not command:
            self.printer.error("EDITOR cannot be empty")
            return False
        try:
            result = subprocess.run([*command, str(path)], check=False)
        except OSError as exc:
            self.printer.error(f"Could not launch editor: {exc}")
            return False
        return result.returncode == 0

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
            self.firewall.close_port(context.opened_port)

        if context.service_user:
            try:
                self.systemd.release_service_identity(
                    context.instance_name,
                    context.install_path,
                    remove_user=context.service_user_created,
                    user_name=context.service_user,
                )
            except Exception as exc:
                self.printer.warning(f"Could not remove isolated service identity: {exc}")

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
        config_file = self.config.nginx_available / f"{domain}.conf"
        enabled_link = self.config.nginx_enabled / f"{domain}.conf"

        if enabled_link.exists() or enabled_link.is_symlink():
            try:
                enabled_link.unlink()
            except Exception as exc:
                self.printer.warning(f"Failed to remove enabled nginx config: {exc}")

        if config_file.exists():
            try:
                config_file.unlink()
            except Exception as exc:
                self.printer.warning(f"Failed to remove nginx config: {exc}")

        try:
            subprocess.run(["nginx", "-t"], check=False, capture_output=True)
            subprocess.run(["systemctl", "reload", "nginx"], check=False)
        except Exception:
            pass

    def _remove_ssl_certificate(self, domain: str):
        try:
            subprocess.run(
                ["certbot", "delete", "--cert-name", domain, "--non-interactive"],
                check=True,
                capture_output=True,
            )
            self.printer.step(f"Removed SSL certificate for {domain}")
        except subprocess.CalledProcessError:
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
            self._run_editor(config_files[0])
            self.printer.step(f"Restart service: sudo systemctl restart plex-{product}")
        else:
            self.printer.warning("No configuration file found")

    def _uninstall_product(self, product: str):
        """Uninstall a product"""
        if not re.fullmatch(r"[A-Za-z0-9_-]+", product):
            self.printer.error("Invalid installation name")
            return False
        install_path = self.config.install_dir / product
        try:
            install_path.resolve().relative_to(self.config.install_dir.resolve())
        except ValueError:
            self.printer.error("Refusing to uninstall a path outside the installation directory")
            return False
        manifest = self._load_resource_manifest(install_path, product)
        if not self._confirm(f"Uninstall {product}? Application files will be removed.", default=False):
            return False

        drop_data = False
        if manifest.get("mongodb", {}).get("database"):
            drop_data = self._confirm("Permanently delete this instance's MongoDB database data?", default=False)

        service_name = str(manifest.get("service") or f"plex-{product}")
        try:
            self.systemd.stop(service_name)
            self.systemd.remove_service(service_name)
        except Exception as exc:
            self.printer.warning(f"Could not remove service {service_name}: {exc}")

        port = manifest.get("firewall_port")
        if isinstance(port, int):
            try:
                self.firewall.close_port(port)
            except Exception as exc:
                self.printer.warning(f"Could not remove firewall rule for {port}: {exc}")

        domain = manifest.get("domain")
        if isinstance(domain, str) and domain:
            self._remove_nginx_config(domain)
            if manifest.get("certificate"):
                self._remove_ssl_certificate(domain)

        mongo = manifest.get("mongodb") or {}
        if self.mongo_manager is not None:
            database = str(mongo.get("database") or "")
            username = str(mongo.get("username") or "")
            identity_removed = True
            if database and username:
                identity_removed = self.mongo_manager.cleanup_identity(
                    database,
                    username,
                    drop_database=drop_data,
                )
                if not identity_removed:
                    self.printer.warning(
                        "Could not remove the MongoDB user automatically; credentials were retained for manual cleanup"
                    )
            if identity_removed:
                self.mongo_manager.remove_saved_credentials(product)
        elif mongo:
            self.printer.warning("MongoDB manager unavailable; stored database resources were preserved")

        service_user = manifest.get("service_user")
        if isinstance(service_user, str) and service_user and manifest.get("service_user_created"):
            try:
                self.systemd.release_service_identity(
                    product,
                    install_path,
                    remove_user=True,
                    user_name=service_user,
                )
            except Exception as exc:
                self.printer.warning(f"Could not remove isolated service identity: {exc}")

        if install_path.exists():
            shutil.rmtree(install_path)
            self.printer.success(f"Removed {install_path}")

        if not drop_data and manifest.get("mongodb", {}).get("database"):
            self.printer.warning("MongoDB data was preserved by default.")
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
            "domain": context.domain,
            "nginx": context.nginx_configured,
            "certificate": context.ssl_configured,
            "service": f"plex-{context.instance_name}" if context.service_created else None,
            "service_isolated": context.service_isolated,
            "service_user": context.service_user,
            "service_user_created": context.service_user_created,
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
        """Load a manifest, using conservative legacy defaults if it is absent."""
        path = install_path / RESOURCE_MANIFEST
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and data.get("instance") == instance_name
                    and Path(str(data.get("install_path", install_path))).resolve() == install_path.resolve()
                ):
                    service = data.get("service")
                    if service not in {None, f"plex-{instance_name}"}:
                        raise ValueError("manifest service does not match instance")
                    port = data.get("firewall_port")
                    if port is not None and (not isinstance(port, int) or not 1 <= port <= 65535):
                        raise ValueError("manifest firewall port is invalid")
                    domain = data.get("domain")
                    if domain is not None and not re.fullmatch(
                        r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?",
                        str(domain),
                    ):
                        raise ValueError("manifest domain is invalid")
                    mongo = data.get("mongodb") or {}
                    if not isinstance(mongo, dict):
                        raise ValueError("manifest MongoDB identity is invalid")
                    return data
            except (OSError, ValueError):
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

            if choice != "0":  # pragma: no branch
                input("\nPress Enter to continue...")

    def _show_ssl_status(self):
        """Show SSL certificate status"""
        self.printer.step("Checking SSL certificates...")
        subprocess.run(["certbot", "certificates"])

    def _view_ssl_logs(self):
        """View SSL renewal logs"""
        log_file = Path("/var/log/letsencrypt/letsencrypt.log")
        if log_file.exists():
            subprocess.run(["tail", "-n", "50", str(log_file)])
        else:
            self.printer.warning("SSL log file not found")

    def _force_ssl_renewal(self):
        """Force SSL certificate renewal"""
        self.printer.warning("This will attempt to renew ALL SSL certificates immediately.")
        confirm = input("Are you sure you want to continue? (y/n): ").strip().lower()

        if confirm == "y":
            self.printer.step("Forcing SSL certificate renewal...")
            try:
                subprocess.run(["certbot", "renew", "--force-renewal"], check=True)
                self.printer.success("SSL certificates renewed successfully!")
                self.printer.step("Reloading Nginx...")
                subprocess.run(["systemctl", "reload", "nginx"])
            except subprocess.CalledProcessError:
                self.printer.error("SSL certificate renewal failed")
        else:
            self.printer.step("SSL renewal cancelled")

    def _test_ssl_renewal(self):
        """Test SSL certificate renewal (dry run)"""
        self.printer.step("Running SSL renewal test (dry run)...")
        try:
            subprocess.run(["certbot", "renew", "--dry-run"], check=True)
            self.printer.success("SSL renewal test successful! All certificates can be renewed.")
        except subprocess.CalledProcessError:
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

            if choice != "0":  # pragma: no branch
                input("\nPress Enter to continue...")

    def _get_addon_supported_products(self) -> list[tuple[str, Path]]:
        """Get list of installed products that support addons"""
        products: list[tuple[str, Path]] = []

        if not self.config.install_dir.exists():
            return products

        for product_dir in self.config.install_dir.iterdir():
            if product_dir.is_dir() and product_dir.name != "backups":
                # Check if this product type supports addons
                product_config = self.config.get_product(product_dir.name)

                if product_config and getattr(product_config, "supports_addons", False):
                    products.append((product_dir.name, product_dir))

        return sorted(products)

    def _require_addon_manager(self):
        """Return the optional addon manager after a runtime availability guard."""
        if self.addon_manager is None:
            raise RuntimeError("Addon manager module is not available")
        return self.addon_manager

    def _manage_product_addons(self, product_name: str, product_path: Path):
        """Manage addons for a specific product"""
        addon_manager = self._require_addon_manager()
        while True:
            clear_terminal()
            self.printer.header(f"Addons for {product_name}")

            addons = addon_manager.list_addons(product_path)

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

            if choice != "0":  # pragma: no branch
                input("\nPress Enter to continue...")

    def _install_addon(self, product_name: str, product_path: Path):
        """Install an addon for a product"""
        addon_manager = self._require_addon_manager()
        self.printer.header(f"Install Addon for {product_name}")

        # Search for addon archives
        self.printer.step("Searching for addon archives...")
        archives = addon_manager.find_addon_archive()

        if not archives:
            self.printer.warning("No addon archives (ZIP/TAR) found automatically")
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

        if addon_manager.addon_exists(potential_name, product_path):
            self.printer.error(f"An addon named '{potential_name}' already exists.")
            self.printer.step("Remove the existing addon first if you want to reinstall.")
            return

        # Install the addon
        success, message, addon_name = addon_manager.install_addon(archive_path, product_path)

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
                    self.printer.step(f"Remember to restart the service: sudo systemctl restart {service_name}")
        else:
            self.printer.error(message)

    def _remove_addon(self, product_name: str, product_path: Path, addons: list[dict]):
        """Remove an addon from a product"""
        addon_manager = self._require_addon_manager()
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
                    success, message = addon_manager.remove_addon(addon_name, product_path, backup_first=backup_first)

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
        addon_manager = self._require_addon_manager()
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
                editor_ok = self._run_editor(config_path)
                if not editor_ok:
                    return

                # Validate YAML after editing
                is_valid, error = addon_manager.validate_yaml(config_path)

                if is_valid:
                    self.printer.success("Configuration file is valid YAML")
                else:
                    self.printer.error(f"YAML syntax error: {error}")
                    self.printer.warning("The configuration may not work correctly until fixed")

                    fix_choice = input("Open editor again to fix? (y/n): ").strip().lower()
                    if fix_choice == "y":
                        self._run_editor(config_path)
                        is_valid, error = addon_manager.validate_yaml(config_path)
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
                        self.printer.step(f"Remember to restart: sudo systemctl restart {service_name}")
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid input")

    def _view_addon_backups(self, product_name: str, product_path: Path):
        """View and optionally restore addon backups"""
        addon_manager = self._require_addon_manager()
        self.printer.header(f"Addon Backups for {product_name}")

        backups = addon_manager.list_addon_backups(product_path)

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
                if addon_manager.addon_exists(backup["addon_name"], product_path):
                    self.printer.warning("Current addon will be replaced!")

                confirm = input("Continue with restore? (y/n): ").strip().lower()

                if confirm == "y":
                    self._restore_addon_backup(product_name, product_path, backup)
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid input")

    def _restore_addon_backup(self, product_name: str, product_path: Path, backup: dict):
        """Safely stage and transactionally restore an addon backup."""
        try:
            addon_manager = self._require_addon_manager()
            addon_name = validate_path_component(backup["addon_name"], label="addon name")
            backup_path = Path(backup["path"])
            addons_path = addon_manager.get_addons_path(product_path)
            addon_path = addons_path / addon_name
            rollback_path: Path | None = None

            self.printer.step("Restoring from backup...")
            addons_path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=f".{addon_name}.restore-", dir=addons_path) as temp_dir:
                extraction_root = Path(temp_dir) / "archive"
                safe_extract_tar(backup_path, extraction_root, expected_top_level=addon_name)
                staged_addon = extraction_root / addon_name
                addon_manager._set_permissions(staged_addon, product_path=product_path)

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


def main(argv: list[str] | None = None):
    """Entry point"""
    setup_logging()

    parser = argparse.ArgumentParser(prog="plexinstaller")
    parser.add_argument("--yes", "-y", action="store_true", help="accept confirmation prompts")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; use safe defaults")
    parser.add_argument("--no-update-check", action="store_true", help="skip checking for installer updates")
    parser.add_argument("--repair-dependencies", action="store_true", help="explicitly repair/install dependencies")
    parser.add_argument(
        "--isolate-services",
        action="store_true",
        help="opt in to dedicated non-root service users; root remains the default and fallback",
    )
    args = parser.parse_args(argv)

    # Determine version from command line or environment
    version = os.environ.get("PLEX_INSTALLER_VERSION", "stable")

    installer = PlexInstaller(
        version=version,
        assume_yes=args.yes,
        non_interactive=args.non_interactive,
        check_updates=not args.no_update_check,
        isolate_services=True if args.isolate_services else None,
    )
    if args.repair_dependencies:
        installer.system.detect()
        installer.system.install_dependencies()
        return 0
    return installer.run()


if __name__ == "__main__":
    sys.exit(main())
