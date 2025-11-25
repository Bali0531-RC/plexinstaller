#!/usr/bin/env python3
"""
PlexDevelopment Products Installer - Python Version
Modular, maintainable installer for Plex products
"""

import os
import sys
import subprocess
import shutil
import tempfile
import zipfile
import re
import json
import urllib.request
import fcntl
import hashlib
import atexit
from pathlib import Path
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

from config import Config, ProductConfig
from utils import (
    ColorPrinter, SystemDetector, DNSChecker, FirewallManager,
    NginxManager, SSLManager, SystemdManager, ArchiveExtractor
)
from telemetry_client import TelemetryClient

# Current installer version
INSTALLER_VERSION = "3.1.9"
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/v3-rewrite/version.json"
LOCK_FILE = "/var/run/plexinstaller.lock"

@dataclass
class InstallationContext:
    """Context for an installation session"""
    product: str
    instance_name: str
    install_path: Path
    port: int
    domain: Optional[str] = None
    email: Optional[str] = None
    needs_web_setup: bool = True
    has_dashboard: bool = False
    install_path_ready: bool = False
    service_created: bool = False
    nginx_configured: bool = False
    ssl_configured: bool = False
    opened_port: Optional[int] = None
    telemetry_session: Optional[str] = None
    log_path: Optional[Path] = None

class PlexInstaller:
    """Main installer class"""
    
    def __init__(self, version: str = "stable"):
        self.version = version
        self.config = Config()
        self.printer = ColorPrinter()
        self._lock_fd = None
        
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
        self.telemetry_enabled = self._initialize_telemetry_preference()
        self.telemetry = TelemetryClient(
            endpoint=self.config.TELEMETRY_ENDPOINT,
            log_dir=self.config.TELEMETRY_LOG_DIR,
            paste_endpoint=self.config.PASTE_ENDPOINT,
            enabled=self.telemetry_enabled
        )
        
        # Register cleanup on exit
        atexit.register(self._release_lock)
    
    def _acquire_lock(self) -> bool:
        """Acquire exclusive lock to prevent concurrent installer runs"""
        try:
            self._lock_fd = open(LOCK_FILE, 'w')
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_fd.write(str(os.getpid()))
            self._lock_fd.flush()
            return True
        except (IOError, OSError):
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
        
    def run(self):
        """Main entry point"""
        os.system('clear' if os.name != 'nt' else 'cls')
        self._display_banner()

        if not self.telemetry_enabled:
            self.printer.step(
                f"Telemetry is disabled. Edit {self.config.telemetry_pref_file} to re-enable it."
            )
        
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
        print("  _____  _           _____                 _                                  _   ")
        print(" |  __ \| |         |  __ \               | |                                | |  ")
        print(" | |__) | | _____  _| |  | | _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ ")
        print(" |  ___/| |/ _ \ \/ / |  | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ \` _ \ / _ \ '_ \| __|")
        print(" | |    | |  __/>  <| |__| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ ")
        print(" |_|    |_|\___/_/\_\_____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|")
        print("                                                  | |                             ")
        print("                                                  |_|                             ")
        print(ColorPrinter.NC)
        print(f"{ColorPrinter.BOLD}{ColorPrinter.PURPLE} UNOFFICIAL Installation Script for PlexDevelopment Products{ColorPrinter.NC}")
        print(f"{ColorPrinter.CYAN}{self.version.upper()} Version - Python-Based Installer{ColorPrinter.NC}\n")
    
    def _check_root(self) -> bool:
        """Check if running as root"""
        if os.geteuid() != 0:
            self.printer.error("This installer must be run as root (use sudo)")
            return False
        return True

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
        print("We collect anonymous install diagnostics (steps completed, errors, log snippets)"
              " to improve PlexInstaller reliability. No API keys or customer data are sent.")
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
            self.printer.warning("Telemetry disabled. You can re-enable it by editing "
                                 f"{pref_file}")

        return enabled
    
    def _check_for_updates(self):
        """Check for installer updates and auto-update if newer version available"""
        try:
            self.printer.step("Checking for installer updates...")
            
            # Fetch version info
            with urllib.request.urlopen(VERSION_CHECK_URL, timeout=5) as response:
                version_data = json.loads(response.read().decode())
            
            remote_version = version_data.get('version', '0.0.0')
            
            # Compare versions
            if self._is_newer_version(remote_version, INSTALLER_VERSION):
                self.printer.warning(f"New installer version available: {remote_version} (current: {INSTALLER_VERSION})")
                print(f"\n{ColorPrinter.CYAN}Changelog:{ColorPrinter.NC}")
                for item in version_data.get('changelog', []):
                    print(f"  • {item}")
                
                choice = input(f"\n{ColorPrinter.YELLOW}Auto-update to latest version? (y/n): {ColorPrinter.NC}").strip().lower()
                
                if choice == 'y':
                    self._perform_update(version_data)
                else:
                    self.printer.step("Continuing with current version...")
            else:
                self.printer.success(f"Installer is up to date (v{INSTALLER_VERSION})")
            
            print()  # Add spacing
            
        except Exception as e:
            self.printer.warning(f"Could not check for updates: {e}")
            self.printer.step("Continuing with current version...")
            print()
    
    def _is_newer_version(self, remote: str, local: str) -> bool:
        """Compare version strings (semantic versioning)"""
        try:
            remote_parts = [int(x) for x in remote.split('.')]
            local_parts = [int(x) for x in local.split('.')]
            
            # Pad to same length
            while len(remote_parts) < len(local_parts):
                remote_parts.append(0)
            while len(local_parts) < len(remote_parts):
                local_parts.append(0)
            
            return remote_parts > local_parts
        except Exception:
            return False
    
    def _perform_update(self, version_data: Dict):
        """Download and install new installer version with checksum verification"""
        try:
            self.printer.step("Downloading updated installer files...")
            
            install_dir = Path("/opt/plexinstaller")
            backup_dir = install_dir / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            
            # Get checksums from version data
            checksums = version_data.get('checksums', {})
            
            # Backup current files
            current_files = ['installer.py', 'config.py', 'utils.py', 'plex_cli.py', 'telemetry_client.py']
            for filename in current_files:
                src = install_dir / filename
                if src.exists():
                    shutil.copy2(src, backup_dir / f"{filename}.bak")
            
            # Download new files
            urls = version_data.get('download_urls', {})
            files_to_update = {
                'installer': 'installer.py',
                'config': 'config.py',
                'utils': 'utils.py',
                'plex_cli': 'plex_cli.py',
                'telemetry_client': 'telemetry_client.py'
            }
            
            for key, filename in files_to_update.items():
                if key in urls:
                    url = urls[key]
                    target = install_dir / filename
                    
                    self.printer.step(f"Downloading {filename}...")
                    with urllib.request.urlopen(url, timeout=30) as response:
                        content = response.read()
                    
                    # Verify checksum if provided
                    if key in checksums:
                        expected_hash = checksums[key]
                        actual_hash = hashlib.sha256(content).hexdigest()
                        if actual_hash != expected_hash:
                            raise ValueError(f"Checksum mismatch for {filename}: expected {expected_hash}, got {actual_hash}")
                        self.printer.success(f"Checksum verified for {filename}")
                    else:
                        self.printer.warning(f"No checksum available for {filename}, skipping verification")
                    
                    target.write_bytes(content)
                    os.chmod(target, 0o755 if filename.endswith('.py') else 0o644)
            
            self.printer.success("Update completed successfully!")
            self.printer.step("Restarting installer with new version...")
            
            # Wait a moment for user to see message
            import time
            time.sleep(2)
            
            # Restart the installer
            os.execv(sys.executable, [sys.executable] + sys.argv)
            
        except Exception as e:
            self.printer.error(f"Update failed: {e}")
            self.printer.warning("Restoring backup files...")
            
            # Restore backups
            try:
                for filename in current_files:
                    backup = backup_dir / f"{filename}.bak"
                    target = install_dir / filename
                    if backup.exists():
                        shutil.copy2(backup, target)
                self.printer.success("Backup restored successfully")
            except Exception:
                self.printer.error("Could not restore backup. Manual intervention may be required.")
            
            self.printer.step("Continuing with current version...")

    
    def _show_main_menu(self):
        """Display main menu and handle user choice"""
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')
            self._display_banner()
            self.printer.header("Main Menu")
            
            # Show quick status overview
            self._show_services_status()
            print()
            
            print("1) Install PlexTickets")
            print("2) Install PlexStaff")
            print("3) Install PlexStatus")
            print("4) Install PlexStore")
            print("5) Install PlexForms")
            print("6) Install PlexLinks")
            print("7) Install PlexPaste")
            print("----------------------------------------")
            print("8) Manage Installations")
            print("9) Manage Backups")
            print("10) SSL Certificate Management")
            print("11) System Health Check")
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
                self._install_product("plexstatus", 3002)
            elif choice == "4":
                self._install_product("plexstore", 3003)
            elif choice == "5":
                self._install_product("plexforms", 3004)
            elif choice == "6":
                self._install_product("plexlinks", 3005)
            elif choice == "7":
                self._install_product("plexpaste", 3006)
            elif choice == "8":
                self._manage_installations()
            elif choice == "9":
                self._manage_backups()
            elif choice == "10":
                self._ssl_management_menu()
            elif choice == "11":
                self._system_health_check()
            else:
                self.printer.error("Invalid choice")
            
            if choice != "0":
                input("\nPress Enter to continue...")
    
    def _show_services_status(self):
        """Show quick status overview of all services"""
        if not self.config.install_dir.exists():
            return
        
        products = [d for d in self.config.install_dir.iterdir() 
                   if d.is_dir() and d.name != "backups"]
        
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
                    match = re.search(r'port[:\s]+(\d+)', content, re.IGNORECASE)
                    if match:
                        port = match.group(1)
                        break
                except:
                    pass
            
            status_display = status
            if "active" in status.lower():
                status_display = f"{ColorPrinter.GREEN}{status}{ColorPrinter.NC}"
            elif "inactive" in status.lower():
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
    
    def _install_product(
        self,
        product: str,
        default_port: int,
        has_dashboard: bool = False,
        needs_web: bool = True
    ):
        """Install a product"""
        instance_name = None
        context: Optional[InstallationContext] = None
        current_step = "initializing"

        try:
            # Check for multi-instance
            instance_name = self._handle_multi_instance(product)
            install_path = self.config.install_dir / instance_name
            context = InstallationContext(
                product=product,
                instance_name=instance_name,
                install_path=install_path,
                port=default_port,
                needs_web_setup=needs_web,
                has_dashboard=has_dashboard
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
                self.telemetry.log_step(current_step, "aborted", "No archive selected")
                self.telemetry.finish_session("aborted", current_step, "Archive not provided")
                return
            self.telemetry.log_step(current_step, "success", str(archive_path))

            # Extract product
            current_step = "extraction"
            self.telemetry.log_step(current_step, "start", f"-> {install_path}")
            extracted_path = self._extract_product(archive_path, instance_name)
            if not extracted_path:
                raise RuntimeError("Archive extraction failed")
            context.install_path = extracted_path
            context.install_path_ready = True
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
            mongo_creds = self._setup_mongodb(instance_name, extracted_path)
            detail = "configured" if mongo_creds else "skipped"
            self.telemetry.log_step(current_step, "success", detail)

            # Web setup (domain, SSL, nginx)
            domain = None
            port = default_port
            if needs_web:
                current_step = "web_setup"
                domain, port, email = self._setup_web(instance_name, default_port, extracted_path, context)
                context.domain = domain
                context.email = email
                context.port = port
                self.telemetry.log_step(current_step, "success", f"{domain}:{port}")

            # Dashboard setup for PlexTickets
            if has_dashboard:
                current_step = "dashboard"
                self._install_dashboard(extracted_path)
                self.telemetry.log_step(current_step, "success")

            # Systemd service
            current_step = "systemd"
            self._setup_systemd(instance_name, extracted_path)
            context.service_created = True
            self.telemetry.log_step(current_step, "success")

            # Post-installation
            current_step = "post_install"
            self._post_install(instance_name, extracted_path, domain, needs_web)
            self.telemetry.log_step(current_step, "success")

            self.printer.success(f"{product} installed successfully!")
            self.telemetry.finish_session("success")
        except KeyboardInterrupt:
            self.printer.warning("\nInstallation cancelled by user")
            if self.telemetry:
                self.telemetry.log_step(current_step, "cancelled")
                self.telemetry.finish_session("cancelled", current_step, "User interrupted")
            if context:
                self._cleanup_failed_install(context)
        except Exception as e:
            self.printer.error(f"Installation failed: {e}")
            failure_url = None
            if self.telemetry:
                summary = self.telemetry.finish_session("failure", current_step, str(e))
                failure_url = self.telemetry.share_log()
            if context:
                self._cleanup_failed_install(context)
            if failure_url:
                self.printer.warning(f"Failure log uploaded: {failure_url}")
                self.printer.step("Please open an issue at https://github.com/Bali0531-RC/plexinstaller/issues and include the log URL.")
            else:
                self.printer.step("Please open an issue at https://github.com/Bali0531-RC/plexinstaller/issues with the console output above.")
        finally:
            pass
    
    def _handle_multi_instance(self, product: str) -> str:
        """Handle multi-instance installations"""
        install_dir = self.config.install_dir / product
        
        if install_dir.exists():
            self.printer.warning(f"Found existing installation of {product}")
            choice = input("Install another instance (multi-instance)? (y/n): ").strip().lower()
            
            if choice == 'y':
                import random
                import string
                suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=4))
                default_name = f"{product}-{suffix}"
                
                instance_name = input(f"Enter unique instance name (default: {default_name}): ").strip()
                if not instance_name:
                    instance_name = default_name
                
                # Validate instance name
                if not re.match(r'^[a-zA-Z0-9_-]+$', instance_name):
                    raise ValueError("Invalid instance name. Use only letters, numbers, dash, underscore")
                
                self.printer.success(f"Installing {product} as instance: {instance_name}")
                return instance_name
        
        return product
    
    def _find_archive(self, product: str) -> Optional[Path]:
        """Find product archive file"""
        self.printer.step(f"Searching for {product} archive...")
        
        search_dirs = [
            Path.home(),
            Path("/root"),
            Path("/tmp"),
            Path("/var/tmp"),
            Path.cwd()
        ]
        
        archives = []
        seen_paths = set()
        product_lower = product.lower()
        patterns = ["*.zip", "*.rar"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for pattern in patterns:
                for archive in search_dir.rglob(pattern):
                    if product_lower in archive.name.lower():
                        resolved = archive.resolve()
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
    
    def _extract_product(self, archive_path: Path, instance_name: str) -> Optional[Path]:
        """Extract product archive"""
        target_dir = self.config.install_dir / instance_name
        
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
                ["npm", "install", "--loglevel=error"],
                cwd=install_path,
                check=True,
                capture_output=True,
                timeout=300
            )
            self.printer.success("NPM dependencies installed")
            return True
        except subprocess.CalledProcessError as e:
            self.printer.error(f"NPM install failed: {e.stderr.decode()}")
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
    
    def _setup_mongodb(self, instance_name: str, install_path: Path) -> Optional[Dict]:
        """Setup MongoDB for product"""
        choice = input("Install and configure MongoDB locally? (y/n): ").strip().lower()
        
        if choice != 'y':
            return None
        
        try:
            # Check if MongoDB is already installed
            if not self._check_mongodb_installed():
                self.printer.step("MongoDB not found. Installing...")
                if not self._install_mongodb():
                    self.printer.error("MongoDB installation failed")
                    return None
            else:
                self.printer.success("MongoDB already installed")
            
            # Ensure MongoDB service is running
            self._ensure_mongodb_running()
            
            # Create database and user for this instance
            mongo_creds = self._create_mongodb_user(instance_name)
            
            if mongo_creds:
                # Save credentials for reuse
                self._save_mongodb_credentials(instance_name, mongo_creds)
                
                # Update config file with MongoDB connection string
                self._update_config_mongodb(install_path, mongo_creds)
                
                return mongo_creds
            
        except Exception as e:
            self.printer.error(f"MongoDB setup failed: {e}")
            return None
    
    def _check_mongodb_installed(self) -> bool:
        """Check if MongoDB is installed"""
        try:
            result = subprocess.run(['mongosh', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True
            
            # Try old mongo shell
            result = subprocess.run(['mongo', '--version'], 
                                  capture_output=True, text=True, timeout=10)
            return result.returncode == 0
        except FileNotFoundError:
            return False
        except subprocess.TimeoutExpired:
            return False
    
    def _install_mongodb(self) -> bool:
        """Install MongoDB"""
        self.printer.step("Installing MongoDB...")
        
        distro = self.system.distribution.lower()
        
        try:
            if 'ubuntu' in distro or 'debian' in distro:
                return self._install_mongodb_debian()
            elif 'centos' in distro or 'rhel' in distro or 'fedora' in distro:
                return self._install_mongodb_rhel()
            elif 'arch' in distro:
                return self._install_mongodb_arch()
            else:
                self.printer.error(f"Unsupported distribution for automatic MongoDB install: {distro}")
                self.printer.step("Please install MongoDB manually: https://docs.mongodb.com/manual/installation/")
                return False
        except Exception as e:
            self.printer.error(f"MongoDB installation failed: {e}")
            return False
    
    def _install_mongodb_debian(self) -> bool:
        """Install MongoDB on Debian/Ubuntu"""
        try:
            # Clean up old MongoDB repository files
            self.printer.step("Cleaning up old MongoDB repositories...")
            old_repo_files = [
                '/etc/apt/sources.list.d/mongodb-org-7.0.list',
                '/etc/apt/sources.list.d/mongodb-org-6.0.list',
                '/etc/apt/sources.list.d/mongodb-org-5.0.list',
                '/etc/apt/sources.list.d/mongodb-org-4.4.list',
            ]
            old_gpg_keys = [
                '/usr/share/keyrings/mongodb-server-7.0.gpg',
                '/usr/share/keyrings/mongodb-server-6.0.gpg',
                '/usr/share/keyrings/mongodb-server-5.0.gpg',
                '/usr/share/keyrings/mongodb-server-4.4.gpg',
            ]
            
            for repo_file in old_repo_files:
                if Path(repo_file).exists():
                    Path(repo_file).unlink()
            
            for gpg_key in old_gpg_keys:
                if Path(gpg_key).exists():
                    Path(gpg_key).unlink()
            
            # Ensure prerequisites are installed
            self.printer.step("Installing prerequisites (gnupg, curl)...")
            subprocess.run(['apt-get', 'install', '-y', 'gnupg', 'curl'], 
                         check=True, capture_output=True, timeout=120)
            
            # Import MongoDB GPG key (using pipe method as per MongoDB docs)
            self.printer.step("Adding MongoDB repository...")
            curl_process = subprocess.Popen(
                ['curl', '-fsSL', 'https://www.mongodb.org/static/pgp/server-8.0.asc'],
                stdout=subprocess.PIPE
            )
            subprocess.run(
                ['gpg', '-o', '/usr/share/keyrings/mongodb-server-8.0.gpg', '--dearmor'],
                stdin=curl_process.stdout,
                check=True,
                timeout=30
            )
            curl_process.wait()
            
            # Detect distro and codename
            distro = self.system.distribution.lower()
            distro_codename = subprocess.run(
                ['lsb_release', '-cs'],
                capture_output=True, text=True, check=True, timeout=10
            ).stdout.strip()
            
            # Determine correct repository URL
            if 'ubuntu' in distro:
                # MongoDB 8.0 Ubuntu repository
                repo_line = f"deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/ubuntu {distro_codename}/mongodb-org/8.0 multiverse\n"
            elif 'debian' in distro:
                # MongoDB 8.0 Debian repository (using 8.2 as per official docs)
                if distro_codename == 'bookworm':
                    repo_line = "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/debian bookworm/mongodb-org/8.2 main\n"
                elif distro_codename == 'bullseye':
                    repo_line = "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/debian bullseye/mongodb-org/8.0 main\n"
                else:
                    # Fallback to bullseye for older versions
                    repo_line = "deb [ signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/debian bullseye/mongodb-org/8.0 main\n"
            else:
                # Fallback to Ubuntu focal
                repo_line = "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] http://repo.mongodb.org/apt/ubuntu focal/mongodb-org/8.0 multiverse\n"
            
            with open('/etc/apt/sources.list.d/mongodb-org-8.0.list', 'w') as f:
                f.write(repo_line)
            
            # Update and install
            self.printer.step("Updating package database...")
            subprocess.run(['apt-get', 'update'], check=True, timeout=120)
            
            self.printer.step("Installing MongoDB packages...")
            subprocess.run(['apt-get', 'install', '-y', 'mongodb-org'], check=True, timeout=300)
            
            # Start and enable service
            self.printer.step("Starting MongoDB service...")
            subprocess.run(['systemctl', 'start', 'mongod'], check=True, timeout=60)
            subprocess.run(['systemctl', 'enable', 'mongod'], check=True, timeout=30)
            
            self.printer.success("MongoDB installed successfully")
            return True
            
        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False
    
    def _install_mongodb_rhel(self) -> bool:
        """Install MongoDB on RHEL/CentOS/Fedora"""
        try:
            # Create repo file
            repo_content = """[mongodb-org-7.0]
name=MongoDB Repository
baseurl=https://repo.mongodb.org/yum/redhat/$releasever/mongodb-org/7.0/x86_64/
gpgcheck=1
enabled=1
gpgkey=https://www.mongodb.org/static/pgp/server-7.0.asc
"""
            with open('/etc/yum.repos.d/mongodb-org-7.0.repo', 'w') as f:
                f.write(repo_content)
            
            # Install
            if 'fedora' in self.system.distribution.lower():
                subprocess.run(['dnf', 'install', '-y', 'mongodb-org'], check=True, timeout=300)
            else:
                subprocess.run(['yum', 'install', '-y', 'mongodb-org'], check=True, timeout=300)
            
            # Start and enable
            subprocess.run(['systemctl', 'start', 'mongod'], check=True, timeout=60)
            subprocess.run(['systemctl', 'enable', 'mongod'], check=True, timeout=30)
            
            self.printer.success("MongoDB installed successfully")
            return True
            
        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False
    
    def _install_mongodb_arch(self) -> bool:
        """Install MongoDB on Arch Linux"""
        try:
            subprocess.run(['pacman', '-S', '--noconfirm', 'mongodb-bin'], check=True, timeout=300)
            subprocess.run(['systemctl', 'start', 'mongodb'], check=True, timeout=60)
            subprocess.run(['systemctl', 'enable', 'mongodb'], check=True, timeout=30)
            
            self.printer.success("MongoDB installed successfully")
            return True
            
        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False
    
    def _ensure_mongodb_running(self):
        """Ensure MongoDB service is running"""
        try:
            # Try mongod service name
            result = subprocess.run(['systemctl', 'is-active', 'mongod'],
                                  capture_output=True, text=True, timeout=10)
            if result.stdout.strip() != 'active':
                subprocess.run(['systemctl', 'start', 'mongod'], check=True, timeout=60)
            
        except Exception:
            # Try mongodb service name (Arch)
            try:
                result = subprocess.run(['systemctl', 'is-active', 'mongodb'],
                                      capture_output=True, text=True, timeout=10)
                if result.stdout.strip() != 'active':
                    subprocess.run(['systemctl', 'start', 'mongodb'], check=True, timeout=60)
            except Exception:
                pass
    
    def _create_mongodb_user(self, instance_name: str) -> Optional[Dict]:
        """Create MongoDB database and user for instance"""
        import random
        import string
        
        # Generate random database name and password
        random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))
        db_name = f"{instance_name}_{random_suffix}"
        username = f"{instance_name}_user"
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        self.printer.step(f"Creating MongoDB database: {db_name}")
        
        try:
            # Create user using mongosh (MongoDB Shell)
            create_user_script = f"""
use {db_name}
db.createUser({{
  user: "{username}",
  pwd: "{password}",
  roles: [{{ role: "readWrite", db: "{db_name}" }}]
}})
"""
            
            # Try mongosh first
            result = subprocess.run(
                ['mongosh', '--eval', create_user_script],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode != 0:
                # Try old mongo shell (without check=True to handle missing binary gracefully)
                try:
                    result = subprocess.run(
                        ['mongo', '--eval', create_user_script],
                        capture_output=True, text=True, timeout=30
                    )
                    if result.returncode != 0:
                        raise RuntimeError(f"MongoDB shell failed: {result.stderr}")
                except FileNotFoundError:
                    raise RuntimeError("Neither mongosh nor mongo shell found. Is MongoDB installed?")
            
            self.printer.success(f"Database '{db_name}' created with user '{username}'")
            
            return {
                'database': db_name,
                'username': username,
                'password': password,
                'host': 'localhost',
                'port': 27017,
                'uri': f"mongodb://{username}:{password}@localhost:27017/{db_name}?authSource={db_name}"
            }
            
        except Exception as e:
            self.printer.error(f"Failed to create MongoDB user: {e}")
            return None
    
    def _save_mongodb_credentials(self, instance_name: str, creds: Dict):
        """Save MongoDB credentials to file for reuse"""
        creds_dir = Path("/etc/plex")
        creds_dir.mkdir(parents=True, exist_ok=True)
        
        creds_file = creds_dir / "mongodb_credentials"
        
        # Append credentials
        with open(creds_file, 'a') as f:
            f.write(f"\n# {instance_name}\n")
            f.write(f"DATABASE={creds['database']}\n")
            f.write(f"USERNAME={creds['username']}\n")
            f.write(f"PASSWORD={creds['password']}\n")
            f.write(f"URI={creds['uri']}\n")
        
        # Set secure permissions
        os.chmod(creds_file, 0o600)
        
        self.printer.success(f"Credentials saved to {creds_file}")
    
    def _update_config_mongodb(self, install_path: Path, creds: Dict):
        """Update product config file with MongoDB connection string"""
        # Look for config files
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))
        
        if not config_files:
            self.printer.warning("No config file found to update with MongoDB settings")
            self.printer.step(f"MongoDB URI: {creds['uri']}")
            return
        
        config_file = config_files[0]
        
        try:
            content = config_file.read_text()
            
            # Try to find and replace MongoDB URI placeholder
            # Common patterns: mongoURI, mongodb_uri, database_url, etc.
            patterns = [
                (r'mongoURI:\s*["\'].*?["\']', f'mongoURI: "{creds["uri"]}"'),
                (r'mongodb_uri:\s*["\'].*?["\']', f'mongodb_uri: "{creds["uri"]}"'),
                (r'database_url:\s*["\'].*?["\']', f'database_url: "{creds["uri"]}"'),
                (r'MongoURI:\s*["\'].*?["\']', f'MongoURI: "{creds["uri"]}"'),
            ]
            
            updated = False
            for pattern, replacement in patterns:
                if re.search(pattern, content):
                    content = re.sub(pattern, replacement, content)
                    updated = True
                    break
            
            if updated:
                config_file.write_text(content)
                self.printer.success(f"Updated MongoDB URI in {config_file.name}")
            else:
                self.printer.warning(f"Could not find MongoDB URI field in {config_file.name}")
                self.printer.step(f"Please manually add MongoDB URI: {creds['uri']}")
                
        except Exception as e:
            self.printer.warning(f"Could not auto-update config: {e}")
            self.printer.step(f"MongoDB URI: {creds['uri']}")

    
    def _setup_web(
        self,
        instance_name: str,
        default_port: int,
        install_path: Path,
        context: InstallationContext
    ) -> Tuple[str, int, str]:
        """Setup web server (nginx, SSL) with validation and context tracking."""

        # Get port with validation (including range check)
        while True:
            port_input = input(f"Enter port (default: {default_port}): ").strip()
            if not port_input:
                port = default_port
                break
            if port_input.isdigit():
                port = int(port_input)
                if 1 <= port <= 65535:
                    break
                else:
                    self.printer.error("Port must be between 1 and 65535. Please try again.")
            else:
                self.printer.error("Port must be a number. Please try again.")

        # Get domain with format validation
        domain_pattern = re.compile(r'^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$')
        domain = ""
        while not domain:
            domain = input(f"Enter domain (e.g., {instance_name}.example.com): ").strip()
            if not domain:
                self.printer.error("Domain cannot be empty")
            elif not domain_pattern.match(domain):
                self.printer.error("Invalid domain format. Please enter a valid domain.")
                domain = ""

        # Get email with format validation
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
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

        # Open firewall port
        self.firewall.open_port(port, instance_name)
        
        # Check DNS
        if not self.dns_checker.check(domain):
            proceed = input("DNS check failed. Proceed anyway? (y/n): ").strip().lower()
            if proceed != 'y':
                raise ValueError("Installation aborted due to DNS issues")
        
        # Setup nginx
        self.nginx.setup(domain, port, instance_name, install_path)
        context.nginx_configured = True
        
        # Setup SSL
        self.ssl.setup(domain, email)
        context.ssl_configured = True
        
        return domain, port, email
    
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
    
    def _setup_systemd(self, instance_name: str, install_path: Path):
        """Setup systemd service"""
        choice = input(f"Set up '{instance_name}' to auto-start on boot? (y/n): ").strip().lower()
        
        if choice == 'y':
            self.systemd.create_service(instance_name, install_path)
            self.printer.success("Systemd service configured")
        else:
            self.printer.warning("Auto-start not configured")
    
    def _post_install(self, instance_name: str, install_path: Path, domain: Optional[str], needs_web: bool):
        """Post-installation tasks"""
        # Find config file
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))
        
        if config_files:
            config_file = config_files[0]
            self.printer.step(f"Configuration file: {config_file}")
            
            choice = input("Edit configuration now? (y/n): ").strip().lower()
            if choice == 'y':
                subprocess.run(["nano", str(config_file)])
                self.printer.step(f"Restart service: sudo systemctl restart plex-{instance_name}")
        
        # Display access information
        if needs_web and domain:
            self.printer.success(f"Access at: https://{domain}")
        
        print(f"\nManage service: sudo systemctl [start|stop|restart|status] plex-{instance_name}")
        print(f"View logs: sudo journalctl -u plex-{instance_name} -f")

    def _cleanup_failed_install(self, context: InstallationContext):
        """Attempt to roll back artifacts from a failed installation."""
        self.printer.warning("Rolling back partial installation...")

        try:
            if context.service_created:
                self.systemd.remove_service(f"plex-{context.instance_name}")
        except Exception as exc:
            self.printer.warning(f"Could not remove systemd service: {exc}")

        if context.nginx_configured and context.domain:
            self._remove_nginx_config(context.domain)

        if context.ssl_configured and context.domain:
            self._remove_ssl_certificate(context.domain)

        if context.install_path and context.install_path.exists():
            try:
                shutil.rmtree(context.install_path, ignore_errors=True)
                self.printer.step(f"Removed {context.install_path}")
            except Exception as exc:
                self.printer.warning(f"Failed to remove install directory: {exc}")

        if context.opened_port:
            self.firewall.close_port(context.opened_port)

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
            subprocess.run(['sudo', 'nginx', '-t'], check=False, capture_output=True)
            subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=False)
        except Exception:
            pass

    def _remove_ssl_certificate(self, domain: str):
        try:
            subprocess.run(
                ['sudo', 'certbot', 'delete', '--cert-name', domain, '--non-interactive'],
                check=True,
                capture_output=True
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
                self._uninstall_product(product)
                break
    
    def _edit_config(self, product: str):
        """Edit product configuration"""
        install_path = self.config.install_dir / product
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))
        
        if config_files:
            subprocess.run(["nano", str(config_files[0])])
            self.printer.step(f"Restart service: sudo systemctl restart plex-{product}")
        else:
            self.printer.warning("No configuration file found")
    
    def _uninstall_product(self, product: str):
        """Uninstall a product"""
        confirm = input(f"Uninstall {product}? This will remove all files. (y/n): ").strip().lower()
        
        if confirm != 'y':
            return
        
        service_name = f"plex-{product}"
        install_path = self.config.install_dir / product
        
        # Stop and remove service
        self.systemd.stop(service_name)
        self.systemd.remove_service(service_name)
        
        # Remove installation directory
        if install_path.exists():
            shutil.rmtree(install_path)
            self.printer.success(f"Removed {install_path}")
        
        self.printer.success(f"{product} uninstalled")
    
    def _system_health_check(self):
        """Perform comprehensive system health check"""
        os.system('clear' if os.name != 'nt' else 'cls')
        self.printer.header("System Health Check")
        
        # Check disk space
        stat = os.statvfs(self.config.install_dir)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
        used_percent = ((total_gb - free_gb) / total_gb) * 100
        
        print("\n=== Disk Space ===")
        print(f"Location: {self.config.install_dir}")
        print(f"Total: {total_gb:.1f} GB")
        print(f"Free: {free_gb:.1f} GB")
        print(f"Used: {used_percent:.1f}%")
        
        if used_percent > 90:
            self.printer.error("⚠ WARNING: Disk usage above 90%!")
        elif used_percent > 80:
            self.printer.warning("⚠ Disk usage above 80%")
        else:
            self.printer.success("✓ Disk space healthy")
        
        # Check services status
        print("\n=== Services Status ===")
        install_dir = self.config.install_dir
        if install_dir.exists():
            all_running = True
            for product_dir in install_dir.iterdir():
                if product_dir.is_dir() and product_dir.name != "backups":
                    service_name = f"plex-{product_dir.name}"
                    status = self.systemd.get_status(service_name)
                    
                    if "active" in status.lower():
                        print(f"  ✓ {product_dir.name}: {ColorPrinter.GREEN}Running{ColorPrinter.NC}")
                    elif "inactive" in status.lower():
                        print(f"  ○ {product_dir.name}: {ColorPrinter.YELLOW}Stopped{ColorPrinter.NC}")
                        all_running = False
                    else:
                        print(f"  ✗ {product_dir.name}: {ColorPrinter.RED}Not Found{ColorPrinter.NC}")
                        all_running = False
            
            if all_running:
                self.printer.success("\n✓ All services are running")
            else:
                self.printer.warning("\n⚠ Some services are not running")
        else:
            self.printer.warning("No installations found")
        
        # Check Nginx status
        print("\n=== Web Server Status ===")
        try:
            result = subprocess.run(['systemctl', 'is-active', 'nginx'], 
                                  capture_output=True, text=True)
            if result.stdout.strip() == 'active':
                self.printer.success("✓ Nginx is running")
            else:
                self.printer.error("✗ Nginx is not running")
        except:
            self.printer.warning("⚠ Could not check Nginx status")
        
        # Check MongoDB status (if installed)
        print("\n=== Database Status ===")
        try:
            result = subprocess.run(['systemctl', 'is-active', 'mongod'], 
                                  capture_output=True, text=True)
            if result.stdout.strip() == 'active':
                self.printer.success("✓ MongoDB is running")
            else:
                self.printer.warning("○ MongoDB is not running")
        except:
            self.printer.step("ℹ MongoDB not installed or not using systemd")
        
        # Check SSL certificates
        print("\n=== SSL Certificates ===")
        certbot_installed = subprocess.run(['which', 'certbot'], 
                                          capture_output=True).returncode == 0
        if certbot_installed:
            try:
                result = subprocess.run(['certbot', 'certificates'], 
                                      capture_output=True, text=True)
                if 'No certificates found' in result.stdout:
                    self.printer.step("ℹ No SSL certificates found")
                else:
                    # Count certificates
                    cert_count = result.stdout.count('Certificate Name:')
                    self.printer.success(f"✓ Found {cert_count} SSL certificate(s)")
            except:
                self.printer.warning("⚠ Could not check SSL certificates")
        else:
            self.printer.step("ℹ Certbot not installed")
        
        # Check memory usage
        print("\n=== Memory Usage ===")
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
                mem_total = int([l for l in lines if 'MemTotal' in l][0].split()[1]) / 1024
                mem_available = int([l for l in lines if 'MemAvailable' in l][0].split()[1]) / 1024
                mem_used = mem_total - mem_available
                mem_percent = (mem_used / mem_total) * 100
                
                print(f"Total: {mem_total:.0f} MB")
                print(f"Used: {mem_used:.0f} MB ({mem_percent:.1f}%)")
                print(f"Available: {mem_available:.0f} MB")
                
                if mem_percent > 90:
                    self.printer.error("⚠ WARNING: Memory usage above 90%!")
                elif mem_percent > 80:
                    self.printer.warning("⚠ Memory usage above 80%")
                else:
                    self.printer.success("✓ Memory usage healthy")
        except:
            self.printer.warning("⚠ Could not check memory usage")
        
        # Check system load
        print("\n=== System Load ===")
        try:
            load1, load5, load15 = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            print(f"1 min: {load1:.2f}")
            print(f"5 min: {load5:.2f}")
            print(f"15 min: {load15:.2f}")
            print(f"CPU cores: {cpu_count}")
            
            if load5 > cpu_count * 2:
                self.printer.error("⚠ WARNING: High system load!")
            elif load5 > cpu_count:
                self.printer.warning("⚠ System load is elevated")
            else:
                self.printer.success("✓ System load normal")
        except:
            self.printer.warning("⚠ Could not check system load")
    
    def _ssl_management_menu(self):
        """SSL certificate management menu"""
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')
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
        subprocess.run(['certbot', 'certificates'])
    
    def _view_ssl_logs(self):
        """View SSL renewal logs"""
        log_file = Path("/var/log/letsencrypt/letsencrypt.log")
        if log_file.exists():
            subprocess.run(['tail', '-n', '50', str(log_file)])
        else:
            self.printer.warning("SSL log file not found")
    
    def _force_ssl_renewal(self):
        """Force SSL certificate renewal"""
        self.printer.warning("This will attempt to renew ALL SSL certificates immediately.")
        confirm = input("Are you sure you want to continue? (y/n): ").strip().lower()
        
        if confirm == 'y':
            self.printer.step("Forcing SSL certificate renewal...")
            try:
                subprocess.run(['certbot', 'renew', '--force-renewal'], check=True)
                self.printer.success("SSL certificates renewed successfully!")
                self.printer.step("Reloading Nginx...")
                subprocess.run(['systemctl', 'reload', 'nginx'])
            except subprocess.CalledProcessError:
                self.printer.error("SSL certificate renewal failed")
        else:
            self.printer.step("SSL renewal cancelled")
    
    def _test_ssl_renewal(self):
        """Test SSL certificate renewal (dry run)"""
        self.printer.step("Running SSL renewal test (dry run)...")
        try:
            subprocess.run(['certbot', 'renew', '--dry-run'], check=True)
            self.printer.success("SSL renewal test successful! All certificates can be renewed.")
        except subprocess.CalledProcessError:
            self.printer.error("SSL renewal test failed. Check output above for details.")
    
    def _manage_backups(self):
        """Manage backups menu"""
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')
            self.printer.header("Backup Management")
            print(f"Backup Location: {self.config.install_dir / 'backups'}")
            print("---")
            
            print("\n1) Create backup of a product")
            print("2) List available backups")
            print("3) Restore product from backup")
            print("4) Delete backup")
            print("0) Return to Main Menu")
            
            choice = input("\nEnter your choice: ").strip()
            
            if choice == "0":
                break
            elif choice == "1":
                self._create_backup()
            elif choice == "2":
                self._list_backups()
            elif choice == "3":
                self._restore_backup()
            elif choice == "4":
                self._delete_backup()
            else:
                self.printer.error("Invalid choice")
            
            if choice != "0":
                input("\nPress Enter to continue...")
    
    def _create_backup(self):
        """Create backup of a product"""
        products = [d for d in self.config.install_dir.iterdir() 
                   if d.is_dir() and d.name != "backups"]
        
        if not products:
            self.printer.warning("No installed products found to back up")
            return
        
        print("\nSelect product to backup:")
        for i, product_dir in enumerate(products, 1):
            print(f"{i}) {product_dir.name}")
        
        choice = input(f"\nEnter choice (1-{len(products)}): ").strip()
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(products):
                product = products[idx].name
                self._backup_product(product)
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid choice")
    
    def _backup_product(self, product: str):
        """Backup a specific product"""
        from datetime import datetime
        import tarfile
        
        install_path = self.config.install_dir / product
        backup_dir = self.config.install_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"{product}_backup_{timestamp}.tar.gz"
        
        self.printer.step(f"Creating backup of {product}...")
        
        # Stop service before backup
        service_name = f"plex-{product}"
        was_running = "active" in self.systemd.get_status(service_name).lower()
        
        if was_running:
            self.printer.step("Stopping service...")
            self.systemd.stop(service_name)
        
        try:
            # Create tar.gz archive
            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(install_path, arcname=product)
            
            # Get file size
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            
            self.printer.success(f"Backup created: {backup_file.name}")
            self.printer.step(f"Size: {size_mb:.2f} MB")
            
        except Exception as e:
            self.printer.error(f"Backup failed: {e}")
        
        # Restart service if it was running
        if was_running:
            self.printer.step("Restarting service...")
            self.systemd.start(service_name)
    
    def _list_backups(self):
        """List available backups"""
        backup_dir = self.config.install_dir / "backups"
        
        if not backup_dir.exists():
            self.printer.warning("No backups directory found")
            return
        
        backups = sorted(backup_dir.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not backups:
            self.printer.warning("No backups found")
            return
        
        print("\nAvailable Backups:")
        print(f"{'ID':<4} {'Product':<15} {'Date':<20} {'Size':<10}")
        print("-" * 60)
        
        from datetime import datetime
        for i, backup_file in enumerate(backups, 1):
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            date_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
            
            # Extract product name from filename
            product = backup_file.stem.replace("_backup_", " ").split()[0]
            
            print(f"{i:<4} {product:<15} {date_str:<20} {size_mb:>8.2f} MB")
    
    def _restore_backup(self):
        """Restore product from backup"""
        import tarfile
        
        backup_dir = self.config.install_dir / "backups"
        
        if not backup_dir.exists():
            self.printer.warning("No backups directory found")
            return
        
        backups = sorted(backup_dir.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not backups:
            self.printer.warning("No backups found")
            return
        
        self._list_backups()
        
        choice = input(f"\nSelect backup ID to restore (1-{len(backups)}): ").strip()
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                selected_backup = backups[idx]
                
                # Extract product name
                product = selected_backup.stem.replace("_backup_", " ").split()[0]
                
                self.printer.warning(f"This will restore {product} from backup.")
                self.printer.warning("Current installation will be replaced!")
                
                confirm = input("Continue? (y/n): ").strip().lower()
                
                if confirm == 'y':
                    self._restore_from_backup(selected_backup, product)
                else:
                    self.printer.step("Restore cancelled")
            else:
                self.printer.error("Invalid backup ID")
        except ValueError:
            self.printer.error("Invalid input")
    
    def _restore_from_backup(self, backup_file: Path, product: str):
        """Restore from a specific backup file"""
        import tarfile
        import shutil
        
        install_path = self.config.install_dir / product
        service_name = f"plex-{product}"
        
        # Stop service
        self.printer.step("Stopping service...")
        self.systemd.stop(service_name)
        
        # Backup current installation (just in case)
        if install_path.exists():
            self.printer.step("Backing up current installation...")
            temp_backup = install_path.parent / f"{product}.backup.tmp"
            if temp_backup.exists():
                shutil.rmtree(temp_backup)
            shutil.move(str(install_path), str(temp_backup))
        
        try:
            # Extract backup
            self.printer.step(f"Restoring from {backup_file.name}...")
            
            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(self.config.install_dir)
            
            # Set permissions
            self.printer.step("Setting permissions...")
            subprocess.run(['chown', '-R', 'root:root', str(install_path)])
            subprocess.run(['find', str(install_path), '-type', 'd', '-exec', 'chmod', '755', '{}', ';'])
            subprocess.run(['find', str(install_path), '-type', 'f', '-exec', 'chmod', '644', '{}', ';'])
            
            # Remove temp backup
            temp_backup = install_path.parent / f"{product}.backup.tmp"
            if temp_backup.exists():
                shutil.rmtree(temp_backup)
            
            self.printer.success(f"Restore of {product} complete")
            
            # Restart service
            self.printer.step("Starting service...")
            self.systemd.start(service_name)
            
        except Exception as e:
            self.printer.error(f"Restore failed: {e}")
            
            # Restore from temp backup
            temp_backup = install_path.parent / f"{product}.backup.tmp"
            if temp_backup.exists():
                self.printer.warning("Attempting to restore previous installation...")
                if install_path.exists():
                    shutil.rmtree(install_path)
                shutil.move(str(temp_backup), str(install_path))
    
    def _delete_backup(self):
        """Delete a backup file"""
        backup_dir = self.config.install_dir / "backups"
        
        if not backup_dir.exists():
            self.printer.warning("No backups directory found")
            return
        
        backups = sorted(backup_dir.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        if not backups:
            self.printer.warning("No backups found")
            return
        
        self._list_backups()
        
        choice = input(f"\nSelect backup ID to DELETE (1-{len(backups)}): ").strip()
        
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                selected_backup = backups[idx]
                
                self.printer.warning(f"You are about to permanently delete: {selected_backup.name}")
                confirm = input("Are you absolutely sure? (y/n): ").strip().lower()
                
                if confirm == 'y':
                    selected_backup.unlink()
                    self.printer.success("Backup deleted successfully")
                else:
                    self.printer.step("Deletion cancelled")
            else:
                self.printer.error("Invalid backup ID")
        except ValueError:
            self.printer.error("Invalid input")
    
    def _ssl_management(self):
        """SSL certificate management"""
        self.printer.header("SSL Management")
        
        print("\n1) View Certificate Status")
        print("2) Renew Certificates")
        print("3) Setup Auto-Renewal")
        print("0) Back")
        
        choice = input("\nChoice: ").strip()
        
        if choice == "1":
            subprocess.run(["certbot", "certificates"])
        elif choice == "2":
            subprocess.run(["certbot", "renew"])
        elif choice == "3":
            self.ssl.setup_auto_renewal()
        
        if choice != "0":
            input("\nPress Enter to continue...")

def main():
    """Entry point"""
    # Determine version from command line or environment
    version = os.environ.get("PLEX_INSTALLER_VERSION", "stable")
    
    installer = PlexInstaller(version=version)
    installer.run()

if __name__ == "__main__":
    main()
