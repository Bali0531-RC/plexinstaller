#!/usr/bin/env python3
"""
Plex CLI Management Tool
Command-line interface for managing PlexDevelopment applications
"""

import sys
import subprocess
import os
import json
import urllib.request
import hashlib
import shutil
import re
from pathlib import Path
from typing import List, Dict, Optional

try:
    from config import Config
except Exception:  # pragma: no cover
    Config = None

try:
    from addon_manager import AddonManager
except Exception:  # pragma: no cover
    AddonManager = None

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

try:
    from utils import redact_sensitive_yaml
except Exception:  # pragma: no cover
    redact_sensitive_yaml = None

# Configuration
INSTALL_DIR = Path("/var/www/plex")
INSTALLER_DIR = Path("/opt/plexinstaller")
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json"

# ANSI Colors
RED = '\033[0;31m'
GREEN = '\033[0;32m'
YELLOW = '\033[0;33m'
BLUE = '\033[0;34m'
CYAN = '\033[0;36m'
BOLD = '\033[1m'
NC = '\033[0m'

def print_error(message: str):
    """Print error message"""
    print(f"{RED}[✗] {message}{NC}", file=sys.stderr)

def print_success(message: str):
    """Print success message"""
    print(f"{GREEN}[✓] {message}{NC}", file=sys.stderr)

def print_info(message: str):
    """Print info message"""
    print(f"{BLUE}[i] {message}{NC}", file=sys.stderr)

def print_warning(message: str):
    """Print warning message"""
    print(f"{YELLOW}[!] {message}{NC}", file=sys.stderr)

def show_help():
    """Display help information"""
    print(f"{BOLD}{CYAN}Plex CLI Management Tool{NC}")
    print()
    print(f"{YELLOW}Usage:{NC}")
    print(f"  {GREEN}plex list{NC}              - Show installed Plex applications and their status")
    print(f"  {GREEN}plex start <app>{NC}       - Start a Plex application")
    print(f"  {GREEN}plex stop <app>{NC}        - Stop a Plex application")
    print(f"  {GREEN}plex restart <app>{NC}     - Restart a Plex application")
    print(f"  {GREEN}plex status <app>{NC}      - Show detailed status of an application")
    print(f"  {GREEN}plex logs <app>{NC}        - View application logs")
    print(f"  {GREEN}plex config <app>{NC}      - Edit application configuration file")
    print(f"  {GREEN}plex enable <app>{NC}      - Enable application to start on boot")
    print(f"  {GREEN}plex disable <app>{NC}     - Disable application from starting on boot")
    print(f"  {GREEN}plex debug <app>{NC}       - Upload redacted config + logs for support")
    print()
    print(f"{YELLOW}Addon Management (PlexTickets/PlexStaff):{NC}")
    print(f"  {GREEN}plex addon list <app>{NC}           - List installed addons")
    print(f"  {GREEN}plex addon install <app> <path>{NC} - Install addon from archive")
    print(f"  {GREEN}plex addon remove <app> <addon>{NC} - Remove an addon (creates backup)")
    print(f"  {GREEN}plex addon config <app> <addon>{NC} - Edit addon configuration")
    print()
    print(f"{YELLOW}Examples:{NC}")
    print("  plex list")
    print("  plex start plextickets")
    print("  plex restart plexstore")
    print("  plex logs plextickets")
    print("  plex config plexstore")
    print("  plex debug plextickets")
    print("  plex addon list plextickets")
    print("  plex addon install plextickets /tmp/MyAddon.zip")
    print("  plex addon remove plextickets MyAddon")
    print("  plex addon config plextickets MyAddon")


def _is_newer_version(remote: str, local: str) -> bool:
    """Compare semantic-ish version strings."""
    try:
        remote_parts = [int(x) for x in remote.split('.')]
        local_parts = [int(x) for x in local.split('.')]

        while len(remote_parts) < len(local_parts):
            remote_parts.append(0)
        while len(local_parts) < len(remote_parts):
            local_parts.append(0)

        return remote_parts > local_parts
    except Exception:
        return False


def _read_local_installer_version() -> str:
    """Read INSTALLER_VERSION from the installed installer.py without importing it."""
    try:
        installer_py = INSTALLER_DIR / "installer.py"
        if not installer_py.exists():
            return "0.0.0"
        text = installer_py.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^\s*INSTALLER_VERSION\s*=\s*\"(?P<v>[^\"]+)\"\s*$", text, re.MULTILINE)
        return match.group("v") if match else "0.0.0"
    except Exception:
        return "0.0.0"


def _ensure_cli_entrypoints():
    """Ensure `/usr/local/bin/plex` and `/usr/local/bin/plexinstaller` point at the bundle."""
    if os.geteuid() != 0:
        return

    try:
        bin_dir = Path("/usr/local/bin")
        bin_dir.mkdir(parents=True, exist_ok=True)

        def _ensure_symlink(link_path: Path, target: Path):
            if not target.exists():
                return
            if link_path.is_symlink():
                if link_path.resolve() == target.resolve():
                    return
                link_path.unlink(missing_ok=True)
            elif link_path.exists():
                link_path.unlink(missing_ok=True)
            link_path.symlink_to(target)

        _ensure_symlink(bin_dir / "plexinstaller", INSTALLER_DIR / "installer.py")
        _ensure_symlink(bin_dir / "plex", INSTALLER_DIR / "plex_cli.py")
    except TypeError:
        # Python < 3.8 missing_ok fallback
        try:
            bin_dir = Path("/usr/local/bin")
            for name, target in {
                "plexinstaller": INSTALLER_DIR / "installer.py",
                "plex": INSTALLER_DIR / "plex_cli.py",
            }.items():
                link_path = bin_dir / name
                if link_path.is_symlink() or link_path.exists():
                    link_path.unlink()
                if target.exists():
                    link_path.symlink_to(target)
        except Exception:
            return
    except Exception:
        return


def _verify_gpg_signature(version_data: dict) -> bool:
    """Verify GPG signature of checksums if present."""
    signature = version_data.get('gpg_signature', '')
    if not signature:
        print_warning("No GPG signature found in version data — skipping signature verification")
        return True

    checksums = version_data.get('checksums', {})
    checksums_text = json.dumps(checksums, sort_keys=True, separators=(',', ':'))

    try:
        import tempfile
        import base64

        sig_file = Path(tempfile.mktemp(suffix='.sig'))
        data_file = Path(tempfile.mktemp(suffix='.dat'))

        sig_file.write_bytes(base64.b64decode(signature))
        data_file.write_text(checksums_text)

        result = subprocess.run(
            ['gpg', '--verify', str(sig_file), str(data_file)],
            capture_output=True,
            text=True,
            timeout=30
        )

        sig_file.unlink(missing_ok=True)
        data_file.unlink(missing_ok=True)

        if result.returncode == 0:
            print_success("GPG signature verified successfully")
            return True
        else:
            print_error(f"GPG signature verification failed: {result.stderr.strip()}")
            return False
    except FileNotFoundError:
        print_warning("gpg not installed — skipping signature verification")
        return True
    except Exception as e:
        print_warning(f"GPG verification error: {e} — skipping")
        return True


def _perform_update(version_data: Dict):
    """Download and install new installer version with checksum verification."""
    if os.geteuid() != 0:
        print_warning("Auto-update requires root. Re-run the command with sudo.")
        return

    # Verify GPG signature before proceeding
    if not _verify_gpg_signature(version_data):
        print_error("Update aborted: GPG signature verification failed")
        return

    install_dir = INSTALLER_DIR
    backup_dir = install_dir / "backup"
    current_files = ['installer.py', 'config.py', 'utils.py', 'plex_cli.py', 'telemetry_client.py', 'addon_manager.py']

    backup_dir.mkdir(parents=True, exist_ok=True)

    checksums = version_data.get('checksums', {})
    urls = version_data.get('download_urls', {})
    files_to_update = {
        'installer': 'installer.py',
        'config': 'config.py',
        'utils': 'utils.py',
        'plex_cli': 'plex_cli.py',
        'telemetry_client': 'telemetry_client.py',
        'addon_manager': 'addon_manager.py'
    }

    for filename in current_files:
        src = install_dir / filename
        if src.exists():
            shutil.copy2(src, backup_dir / f"{filename}.bak")

    for key, filename in files_to_update.items():
        if key not in urls:
            continue
        url = urls[key]
        target = install_dir / filename

        print_info(f"Downloading {filename}...")
        with urllib.request.urlopen(url, timeout=30) as response:
            content = response.read()

        if key in checksums:
            expected_hash = checksums[key]
            actual_hash = hashlib.sha256(content).hexdigest()
            if actual_hash != expected_hash:
                raise ValueError(
                    f"Checksum mismatch for {filename}: expected {expected_hash}, got {actual_hash}"
                )
        else:
            raise ValueError(
                f"No checksum provided for {filename}. Aborting update for security."
            )

        target.write_bytes(content)
        os.chmod(target, 0o755 if filename.endswith('.py') else 0o644)

    _ensure_cli_entrypoints()

    print_success("Update completed successfully. Restarting...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _maybe_auto_update():
    """Check for installer updates and prompt if a newer version is available."""
    if not sys.stdin.isatty():
        return

    try:
        with urllib.request.urlopen(VERSION_CHECK_URL, timeout=5) as response:
            version_data = json.loads(response.read().decode())
        remote_version = version_data.get('version', '0.0.0')
        local_version = _read_local_installer_version()

        if _is_newer_version(remote_version, local_version):
            print_warning(f"New installer version available: {remote_version} (current: {local_version})")
            changelog = version_data.get('changelog', [])
            if changelog:
                print(f"\n{CYAN}Changelog:{NC}")
                for item in changelog:
                    print(f"  • {item}")
            choice = input(f"\n{YELLOW}Auto-update to latest version? (y/n): {NC}").strip().lower()
            if choice == 'y':
                _perform_update(version_data)
    except KeyboardInterrupt:
        return
    except Exception:
        # Never block normal CLI usage if update checks fail.
        return
    finally:
        _ensure_cli_entrypoints()

def get_installed_apps() -> List[str]:
    """Get list of installed Plex applications"""
    apps = []
    if not INSTALL_DIR.exists():
        return apps
    
    for app_dir in INSTALL_DIR.iterdir():
        if app_dir.is_dir() and (app_dir / "package.json").exists():
            # Skip backups directory
            if app_dir.name != "backups":
                apps.append(app_dir.name)
    
    return sorted(apps)


def resolve_app_instance(name: str) -> Optional[str]:
    """Resolve a user-provided name to an installed instance folder.

    Supports:
    - Exact instance folder name (recommended)
    - Base product name only if it resolves unambiguously to a single installed instance
    """
    if not name:
        return None

    installed = get_installed_apps()
    if not installed:
        return None

    by_lower = {app.lower(): app for app in installed}
    normalized = name.strip().lower()

    # Exact match
    if normalized in by_lower:
        return by_lower[normalized]

    # Unambiguous prefix match for multi-instance installs (e.g. plextickets -> plextickets-ab12)
    candidates = [app for app in installed if app.lower().startswith(f"{normalized}-")]
    if len(candidates) == 1:
        return candidates[0]

    if len(candidates) > 1:
        print_error(f"Multiple instances match '{name}'. Please specify the exact instance name:")
        for app in candidates:
            print(f"  - {app}")
        return None

    return None

def is_valid_app(app: str) -> bool:
    """Check if app is a valid installed application"""
    return resolve_app_instance(app) is not None

def get_service_name(app: str) -> str:
    """Get systemd service name for app"""
    instance = resolve_app_instance(app) or app
    return f"plex-{instance}"

def get_service_status(service_name: str) -> Dict[str, object]:
    """Get detailed service status"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service_name],
            capture_output=True,
            text=True
        )
        is_active = result.stdout.strip() == 'active'
        
        result = subprocess.run(
            ['systemctl', 'is-enabled', service_name],
            capture_output=True,
            text=True
        )
        is_enabled = result.stdout.strip() == 'enabled'
        
        if is_active:
            status = "Running"
            color = GREEN
        elif is_enabled:
            status = "Stopped"
            color = YELLOW
        else:
            status = "Disabled"
            color = RED
        
        return {
            'status': status,
            'color': color,
            'active': is_active,
            'enabled': is_enabled
        }
    except Exception:
        return {
            'status': 'Unknown',
            'color': RED,
            'active': False,
            'enabled': False
        }

def list_apps():
    """List all installed Plex applications"""
    print_info("Scanning for installed Plex applications...")
    apps = get_installed_apps()
    
    if not apps:
        print_error(f"No Plex applications found in {INSTALL_DIR}")
        return 1
    
    print()
    print(f"{BOLD}{CYAN}Installed Plex Applications:{NC}")
    print()
    
    for app in apps:
        service_name = get_service_name(app)
        app_dir = INSTALL_DIR / app
        status_info = get_service_status(service_name)
        
        print(f"{BOLD}{app}{NC}")
        print(f"  Status: {status_info['color']}{status_info['status']}{NC}")
        print(f"  Path: {app_dir}")
        
        # Show config file if exists
        for config_name in ['config.yml', 'config.yaml', 'config.json']:
            config_file = app_dir / config_name
            if config_file.exists():
                print(f"  Config: {config_file}")
                break
        
        # Show if enabled on boot
        if status_info['enabled']:
            print(f"  {GREEN}✓ Enabled on boot{NC}")
        else:
            print(f"  {YELLOW}○ Not enabled on boot{NC}")
        
        print()
    
    return 0

def start_app(app: str):
    """Start an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Starting {instance}...")
    
    try:
        subprocess.run(['systemctl', 'start', service_name], check=True)
        print_success(f"{instance} started successfully")
        
        # Wait a moment and check if it's actually running
        import time
        time.sleep(2)
        
        status_info = get_service_status(service_name)
        if status_info['active']:
            print_success(f"{instance} is now running")
        else:
            print_error(f"{instance} failed to start properly")
            print(f"Check logs with: plex logs {instance}")
            return 1
        
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to start {instance}")
        return 1

def stop_app(app: str):
    """Stop an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Stopping {instance}...")
    
    try:
        subprocess.run(['systemctl', 'stop', service_name], check=True)
        print_success(f"{instance} stopped successfully")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to stop {instance}")
        return 1

def restart_app(app: str):
    """Restart an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Restarting {instance}...")
    
    try:
        subprocess.run(['systemctl', 'restart', service_name], check=True)
        print_success(f"{instance} restarted successfully")
        
        # Wait a moment and check if it's running
        import time
        time.sleep(2)
        
        status_info = get_service_status(service_name)
        if status_info['active']:
            print_success(f"{instance} is now running")
        else:
            print_error(f"{instance} failed to start after restart")
            print(f"Check logs with: plex logs {instance}")
            return 1
        
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to restart {instance}")
        return 1

def show_status(app: str):
    """Show detailed status of an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print(f"{BOLD}{CYAN}Status for {instance}:{NC}")
    print()
    
    try:
        subprocess.run(['systemctl', 'status', service_name, '--no-pager', '-l'])
        return 0
    except subprocess.CalledProcessError:
        return 1

def view_logs(app: str):
    """View application logs"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Showing logs for {instance} (Press Ctrl+C to exit)...")
    print()
    
    try:
        subprocess.run(['journalctl', '-u', service_name, '-f', '--no-pager'])
        return 0
    except KeyboardInterrupt:
        print()
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to view logs for {instance}")
        return 1

def edit_config(app: str):
    """Edit application configuration"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    app_dir = INSTALL_DIR / instance
    config_file = None
    
    # Look for config files
    for config_name in ['config.yml', 'config.yaml', 'config.json']:
        potential_config = app_dir / config_name
        if potential_config.exists():
            config_file = potential_config
            break
    
    if not config_file:
        print_error(f"No configuration file found for {app}")
        print(f"Looked for: config.yml, config.yaml, config.json in {app_dir}")
        return 1
    
    print_info(f"Opening configuration file: {config_file}")
    print_info("Remember to restart the application after making changes!")
    print()
    
    # Use nano as default editor, fall back to vi
    editor = os.environ.get('EDITOR', 'nano')
    if not subprocess.run(['which', editor], capture_output=True).returncode == 0:
        editor = 'nano' if subprocess.run(['which', 'nano'], capture_output=True).returncode == 0 else 'vi'
    
    try:
        subprocess.run([editor, str(config_file)])
        print()
        print(f"{YELLOW}Configuration file updated. Restart the application to apply changes:{NC}")
        print(f"  {GREEN}plex restart {instance}{NC}")
        return 0
    except subprocess.CalledProcessError:
        print_error("Failed to open editor")
        return 1

def enable_app(app: str):
    """Enable application to start on boot"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Enabling {instance} to start on boot...")
    
    try:
        subprocess.run(['systemctl', 'enable', service_name], check=True)
        print_success(f"{instance} will now start automatically on boot")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to enable {instance}")
        return 1

def disable_app(app: str):
    """Disable application from starting on boot"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(instance)
    print_info(f"Disabling {instance} from starting on boot...")
    
    try:
        subprocess.run(['systemctl', 'disable', service_name], check=True)
        print_success(f"{instance} will no longer start automatically on boot")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to disable {instance}")
        return 1


def debug_app(app: str) -> int:
    """Upload redacted config + recent logs for support."""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1

    app_dir = INSTALL_DIR / instance
    config_path = None
    for config_name in ["config.yml", "config.yaml"]:
        candidate = app_dir / config_name
        if candidate.exists():
            config_path = candidate
            break

    if config_path:
        try:
            config_contents = config_path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            config_contents = f"<Could not read config file: {exc}>\n"
    else:
        config_contents = "<No config.yml/config.yaml found>\n"

    service_name = get_service_name(instance)
    try:
        result = subprocess.run(
            ["journalctl", "-u", service_name, "-n", "500", "--no-pager"],
            capture_output=True,
            text=True,
        )
        logs_contents = result.stdout if result.stdout else result.stderr
    except Exception as exc:
        logs_contents = f"<Could not run journalctl: {exc}>\n"

    bundle = (
        f"===== instance =====\n{instance}\n\n"
        f"===== config.yml =====\n{config_contents}\n\n"
        f"===== journalctl (last 500 lines) =====\n{logs_contents}\n"
    )

    if redact_sensitive_yaml:
        bundle = redact_sensitive_yaml(bundle)

    paste_endpoint = "https://paste.plexdev.xyz/documents"
    if Config is not None:
        try:
            paste_endpoint = Config.PASTE_ENDPOINT
        except Exception:
            pass

    if requests is None:
        print_error("Python package 'requests' is required for plex debug uploads")
        return 1

    print_info("Uploading debug bundle to paste service...")
    try:
        response = requests.post(
            paste_endpoint,
            data=bundle.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        url = data.get("url")
        key = data.get("key")
        if not url and key:
            base = paste_endpoint
            if base.endswith("/documents"):
                base = base[: -len("/documents")]
            url = f"{base}/{key}"
        if not url:
            print_error("Paste upload succeeded but no URL was returned")
            return 1

        print_success(f"Debug bundle uploaded: {url}")
        print_warning("Only share this link in official plexdevelopment tickets.")
        return 0
    except Exception as exc:
        print_error(f"Failed to upload debug bundle: {exc}")
        return 1


# ========== ADDON MANAGEMENT CLI ==========

def _get_addon_manager():
    """Get AddonManager instance if available"""
    if AddonManager is None:
        print_error("Addon manager module not available")
        return None
    return AddonManager()


def _supports_addons(app: str) -> bool:
    """Check if an app supports addons"""
    base_product = app.split('-')[0]
    return base_product.lower() in ['plextickets', 'plexstaff']


def addon_list(app: str) -> int:
    """List installed addons for an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    if not _supports_addons(instance):
        print_error(f"Application '{instance}' does not support addons.")
        print_info("Addons are only supported for PlexTickets and PlexStaff.")
        return 1
    
    addon_mgr = _get_addon_manager()
    if not addon_mgr:
        return 1
    
    app_dir = INSTALL_DIR / instance
    addons = addon_mgr.list_addons(app_dir)
    
    if not addons:
        print_info(f"No addons installed for {instance}")
        print(f"Install addons with: plex addon install {instance} /path/to/addon.zip")
        return 0
    
    print(f"{BOLD}{CYAN}Installed Addons for {instance}:{NC}")
    print()
    print(f"{'Name':<25} {'Config File':<20}")
    print("-" * 50)
    
    for addon in addons:
        config_status = addon['config_path'].name if addon['has_config'] else "No config"
        print(f"{addon['name']:<25} {config_status:<20}")
    
    print()
    print(f"Total: {len(addons)} addon(s)")
    return 0


def addon_install(app: str, archive_path: str) -> int:
    """Install an addon from an archive file"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    if not _supports_addons(instance):
        print_error(f"Application '{instance}' does not support addons.")
        print_info("Addons are only supported for PlexTickets and PlexStaff.")
        return 1
    
    addon_mgr = _get_addon_manager()
    if not addon_mgr:
        return 1
    
    archive = Path(archive_path)
    if not archive.exists():
        print_error(f"Archive not found: {archive_path}")
        return 1
    
    if archive.suffix.lower() not in ['.zip', '.rar']:
        print_error(f"Unsupported archive format: {archive.suffix}")
        print_info("Supported formats: .zip, .rar")
        return 1
    
    app_dir = INSTALL_DIR / instance
    
    # Check for collision
    potential_name = archive.stem
    for suffix in ['-main', '-master', '-addon', '-v1', '-v2']:
        if potential_name.lower().endswith(suffix):
            potential_name = potential_name[:-len(suffix)]
    
    if addon_mgr.addon_exists(potential_name, app_dir):
        print_error(f"Addon '{potential_name}' already exists.")
        print_info("Remove the existing addon first: plex addon remove {instance} {potential_name}")
        return 1
    
    print_info(f"Installing addon from {archive.name}...")
    
    success, message, addon_name = addon_mgr.install_addon(archive, app_dir)
    
    if success:
        print_success(message)
        print()
        print(f"{YELLOW}Remember to restart the service to apply changes:{NC}")
        print(f"  plex restart {instance}")
        return 0
    else:
        print_error(message)
        return 1


def addon_remove(app: str, addon_name: str) -> int:
    """Remove an addon from an application"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    if not _supports_addons(instance):
        print_error(f"Application '{instance}' does not support addons.")
        return 1
    
    addon_mgr = _get_addon_manager()
    if not addon_mgr:
        return 1
    
    app_dir = INSTALL_DIR / instance
    
    if not addon_mgr.addon_exists(addon_name, app_dir):
        print_error(f"Addon '{addon_name}' not found in {instance}")
        print_info(f"Use 'plex addon list {instance}' to see installed addons")
        return 1
    
    print_info(f"Removing addon '{addon_name}' from {instance}...")
    print_info("Creating backup before removal...")
    
    success, message = addon_mgr.remove_addon(addon_name, app_dir, backup_first=True)
    
    if success:
        print_success(message)
        print()
        print(f"{YELLOW}Remember to restart the service to apply changes:{NC}")
        print(f"  plex restart {instance}")
        return 0
    else:
        print_error(message)
        return 1


def addon_config(app: str, addon_name: str) -> int:
    """Edit an addon's configuration file"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    if not _supports_addons(instance):
        print_error(f"Application '{instance}' does not support addons.")
        return 1
    
    addon_mgr = _get_addon_manager()
    if not addon_mgr:
        return 1
    
    app_dir = INSTALL_DIR / instance
    
    config_path = addon_mgr.get_addon_config_path(addon_name, app_dir)
    
    if not config_path:
        print_error(f"No configuration file found for addon '{addon_name}'")
        
        # Check if addon exists at all
        if not addon_mgr.addon_exists(addon_name, app_dir):
            print_info(f"Addon '{addon_name}' is not installed")
            print_info(f"Use 'plex addon list {instance}' to see installed addons")
        else:
            print_info("This addon does not have a config.yml or config.yaml file")
        return 1
    
    print_info(f"Opening {config_path.name} for editing...")
    print_info("Remember to restart the application after making changes!")
    print()
    
    # Use nano as default editor
    editor = os.environ.get('EDITOR', 'nano')
    if not subprocess.run(['which', editor], capture_output=True).returncode == 0:
        editor = 'nano' if subprocess.run(['which', 'nano'], capture_output=True).returncode == 0 else 'vi'
    
    try:
        subprocess.run([editor, str(config_path)])
        
        # Validate YAML after editing
        is_valid, error = addon_mgr.validate_yaml(config_path)
        
        if is_valid:
            print_success("Configuration file is valid YAML")
        else:
            print_error(f"YAML syntax error: {error}")
            print_warning("The configuration may not work correctly until fixed")
        
        print()
        print(f"{YELLOW}Restart the application to apply changes:{NC}")
        print(f"  plex restart {instance}")
        return 0
    except subprocess.CalledProcessError:
        print_error("Failed to open editor")
        return 1


def handle_addon_command(args: List[str]) -> int:
    """Handle addon subcommands"""
    if len(args) < 2:
        print_error("Usage: plex addon <subcommand> <app> [options]")
        print()
        print(f"{YELLOW}Subcommands:{NC}")
        print(f"  {GREEN}list <app>{NC}             - List installed addons")
        print(f"  {GREEN}install <app> <path>{NC}  - Install addon from archive")
        print(f"  {GREEN}remove <app> <addon>{NC}  - Remove an addon")
        print(f"  {GREEN}config <app> <addon>{NC}  - Edit addon configuration")
        return 1
    
    subcommand = args[0].lower()
    
    if subcommand == 'list':
        if len(args) < 2:
            print_error("Usage: plex addon list <app>")
            return 1
        return addon_list(args[1])
    
    elif subcommand == 'install':
        if len(args) < 3:
            print_error("Usage: plex addon install <app> <archive_path>")
            return 1
        return addon_install(args[1], args[2])
    
    elif subcommand == 'remove':
        if len(args) < 3:
            print_error("Usage: plex addon remove <app> <addon_name>")
            return 1
        return addon_remove(args[1], args[2])
    
    elif subcommand in ['config', 'configure']:
        if len(args) < 3:
            print_error("Usage: plex addon config <app> <addon_name>")
            return 1
        return addon_config(args[1], args[2])
    
    else:
        print_error(f"Unknown addon subcommand: {subcommand}")
        print_info("Use 'plex addon' for usage information")
        return 1


# ========== END ADDON MANAGEMENT CLI ==========

def main():
    """Main entry point"""
    _maybe_auto_update()

    if len(sys.argv) < 2:
        show_help()
        return 1
    
    command = sys.argv[1].lower()
    
    if command in ['list', 'ls']:
        return list_apps()
    
    elif command == 'start':
        if len(sys.argv) < 3:
            print_error("Usage: plex start <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return start_app(sys.argv[2])
    
    elif command == 'stop':
        if len(sys.argv) < 3:
            print_error("Usage: plex stop <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return stop_app(sys.argv[2])
    
    elif command == 'restart':
        if len(sys.argv) < 3:
            print_error("Usage: plex restart <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return restart_app(sys.argv[2])
    
    elif command == 'status':
        if len(sys.argv) < 3:
            print_error("Usage: plex status <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return show_status(sys.argv[2])
    
    elif command == 'logs':
        if len(sys.argv) < 3:
            print_error("Usage: plex logs <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return view_logs(sys.argv[2])
    
    elif command in ['config', 'configure']:
        if len(sys.argv) < 3:
            print_error("Usage: plex config <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return edit_config(sys.argv[2])
    
    elif command == 'enable':
        if len(sys.argv) < 3:
            print_error("Usage: plex enable <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return enable_app(sys.argv[2])
    
    elif command == 'disable':
        if len(sys.argv) < 3:
            print_error("Usage: plex disable <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return disable_app(sys.argv[2])

    elif command == 'debug':
        if len(sys.argv) < 3:
            print_error("Usage: plex debug <app_name>")
            print("Use 'plex list' to see available applications")
            return 1
        return debug_app(sys.argv[2])
    
    elif command == 'addon':
        return handle_addon_command(sys.argv[2:])
    
    elif command in ['help', '-h', '--help']:
        show_help()
        return 0
    
    else:
        print_error(f"Unknown command: {command}")
        print()
        show_help()
        return 1

if __name__ == "__main__":
    sys.exit(main())
