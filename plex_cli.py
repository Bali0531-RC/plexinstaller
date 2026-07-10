#!/usr/bin/env python3
"""
Plex CLI Management Tool
Command-line interface for managing PlexDevelopment applications
"""

import argparse
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NoReturn

from colorama import Fore, Style
from colorama import init as colorama_init

try:
    from config import Config
except Exception:  # pragma: no cover
    Config = None  # type: ignore[assignment,misc]

try:
    from addon_manager import AddonManager
except Exception:  # pragma: no cover
    AddonManager = None  # type: ignore[assignment,misc]

try:
    import requests  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    from utils import redact_sensitive_yaml
except Exception:  # pragma: no cover
    redact_sensitive_yaml = None  # type: ignore[assignment]

try:
    from shared import (
        INSTALLER_DIR as _SHARED_INSTALLER_DIR,
    )
    from shared import (
        VERSION_CHECK_URL as _SHARED_VERSION_CHECK_URL,
    )
    from shared import (
        ensure_cli_entrypoints,
        is_newer_version,
        perform_update,
        verify_gpg_signature,
    )
except Exception:  # pragma: no cover
    is_newer_version = None  # type: ignore[assignment]
    verify_gpg_signature = None  # type: ignore[assignment]
    perform_update = None  # type: ignore[assignment]
    ensure_cli_entrypoints = None  # type: ignore[assignment]
    _SHARED_INSTALLER_DIR = None  # type: ignore[assignment]
    _SHARED_VERSION_CHECK_URL = None  # type: ignore[assignment]

# Configuration
INSTALL_DIR = Path("/var/www/plex")
INSTALLER_DIR = _SHARED_INSTALLER_DIR or Path("/opt/plexinstaller")
VERSION_CHECK_URL = (
    _SHARED_VERSION_CHECK_URL or "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json"
)

# Initialize colorama
colorama_init(autoreset=False)

# ANSI Colors (via colorama)
RED = Fore.RED
GREEN = Fore.GREEN
YELLOW = Fore.YELLOW
BLUE = Fore.BLUE
CYAN = Fore.CYAN
BOLD = Style.BRIGHT
NC = Style.RESET_ALL

_cli_logger = logging.getLogger("plexinstaller.cli")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 64


def _confirm(prompt: str, *, assume_yes: bool = False, non_interactive: bool = False) -> bool:
    """Return an explicit confirmation, with automation-safe defaults."""
    if assume_yes:
        return True
    if non_interactive or not sys.stdin.isatty():
        return False
    return input(f"{prompt} (y/N): ").strip().lower() in {"y", "yes"}


def _editor_command() -> list[str]:
    """Parse EDITOR safely and choose a usable fallback."""
    configured = os.environ.get("EDITOR", "nano")
    try:
        command = shlex.split(configured)
    except ValueError:
        command = []
    if command and shutil_which(command[0]):
        return command
    for fallback in ("nano", "vi"):
        if shutil_which(fallback):
            return [fallback]
    return command or ["vi"]


def shutil_which(command: str) -> str | None:
    """Small indirection to keep editor selection straightforward to test."""
    from shutil import which

    return which(command)


def _run_editor(path: Path) -> int:
    """Open *path* with EDITOR and propagate a failed editor status."""
    try:
        result = subprocess.run([*_editor_command(), str(path)], check=False)
    except OSError as exc:
        print_error(f"Failed to open editor: {exc}")
        return EXIT_ERROR
    if result.returncode != 0:
        print_error(f"Editor exited with status {result.returncode}")
        return EXIT_ERROR
    return EXIT_OK


_SENSITIVE_KEY_NAME = (
    r"(?:password(?:[ _-]?hash)?|passwd|passphrase|pwd|secret(?:[ _-]?key)?|"
    r"(?:access|refresh|auth(?:entication|orization)?|id|session|bearer|bot|discord|github|api)"
    r"[ _-]?token|token|api[ _-]?key|x[ _-]?api[ _-]?key|client[ _-]?(?:secret|token)|"
    r"private[ _-]?key|license[ _-]?key|authorization|set[ _-]?cookie|cookie|"
    r"session[ _-]?id|webhook(?:[ _-]?(?:url|secret|token))?|credentials?)"
)
_SENSITIVE_KEY = re.compile(_SENSITIVE_KEY_NAME, re.IGNORECASE)
_SENSITIVE_ASSIGNMENT = re.compile(
    rf"""(?ix)
    (?P<prefix>
        (?<![A-Za-z0-9_-])
        ["']?{_SENSITIVE_KEY_NAME}["']?
        (?![A-Za-z0-9_-])
        \s*(?::|=|\bis\b)\s*
    )
    (?P<value>
        "(?:\\.|[^"\\])*"
        | '(?:\\.|[^'\\])*'
        | [^\r\n,}}\]]+
    )
    """
)
_URI_CREDENTIALS = re.compile(
    r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)(?P<username>[^/\s:@]+):(?P<password>[^/\s@]+)@",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_BASIC_AUTH = re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]+")
_REDACTED_VALUES = {"<REDACTED>", "[REDACTED]"}


def redact_debug_text(text: str) -> str:
    """Redact known secret patterns in YAML-ish config and free-form debug text."""
    if redact_sensitive_yaml is not None:
        text = redact_sensitive_yaml(text)
    text = _URI_CREDENTIALS.sub(
        lambda match: f"{match.group('scheme')}<REDACTED>:<REDACTED>@",
        text,
    )
    text = _BEARER.sub("Bearer <REDACTED>", text)
    text = _BASIC_AUTH.sub("Basic <REDACTED>", text)
    return _SENSITIVE_ASSIGNMENT.sub(
        lambda match: f'{match.group("prefix")}"<REDACTED>"',
        text,
    )


def _redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("<REDACTED>" if _SENSITIVE_KEY.search(str(key)) else _redact_json_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_debug_text(value)
    return value


def redact_config_contents(contents: str, suffix: str) -> str:
    """Recursively redact JSON configs and apply text-pattern redaction as defense in depth."""
    if suffix.lower() == ".json":
        try:
            parsed = json.loads(contents)
            return json.dumps(_redact_json_value(parsed), indent=2) + "\n"
        except (TypeError, ValueError):
            pass
    return redact_debug_text(contents)


def debug_bundle_is_safe(text: str) -> bool:
    """Reject bundles that still contain obvious credential-bearing patterns."""
    for match in _URI_CREDENTIALS.finditer(text):
        if {match.group("username"), match.group("password")} != {"<REDACTED>"}:
            return False
    if _BEARER.search(text) or _BASIC_AUTH.search(text):
        return False
    for match in _SENSITIVE_ASSIGNMENT.finditer(text):
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1].strip()
        if value not in _REDACTED_VALUES:
            return False
    return True


def print_error(message: str):
    """Print error message"""
    print(f"{RED}[✗] {message}{NC}", file=sys.stderr)
    _cli_logger.error(message)


def print_success(message: str):
    """Print success message"""
    print(f"{GREEN}[✓] {message}{NC}", file=sys.stderr)
    _cli_logger.info(message)


def print_info(message: str):
    """Print info message"""
    print(f"{BLUE}[i] {message}{NC}", file=sys.stderr)
    _cli_logger.info(message)


def print_warning(message: str):
    """Print warning message"""
    print(f"{YELLOW}[!] {message}{NC}", file=sys.stderr)
    _cli_logger.warning(message)


def show_help():
    """Display help information"""
    print(f"{BOLD}{CYAN}Plex CLI Management Tool{NC}")
    print()
    print(f"{YELLOW}Usage:{NC}")
    print(f"  {GREEN}plex list{NC}              - Show installed Plex/Drako applications and status")
    print(f"  {GREEN}plex start <app>{NC}       - Start an application")
    print(f"  {GREEN}plex stop <app>{NC}        - Stop an application")
    print(f"  {GREEN}plex restart <app>{NC}     - Restart an application")
    print(f"  {GREEN}plex status <app>{NC}      - Show detailed status of an application")
    print(f"  {GREEN}plex logs <app>{NC}        - View application logs")
    print(f"  {GREEN}plex config <app>{NC}      - Edit application configuration file")
    print(f"  {GREEN}plex enable <app>{NC}      - Enable application to start on boot")
    print(f"  {GREEN}plex disable <app>{NC}     - Disable application from starting on boot")
    print(f"  {GREEN}plex debug <app>{NC}       - Upload redacted config + logs for support")
    print()
    print(f"{YELLOW}Tools:{NC}")
    print(f"  {GREEN}plex tool setupdomain <app>{NC} - Set up domain, reverse proxy & SSL for an instance")
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
    print("  plex restart drakostore")
    print("  plex logs plextickets")
    print("  plex config drakostore")
    print("  plex debug plextickets")
    print("  plex addon list plextickets")
    print("  plex addon install plextickets /tmp/MyAddon.zip")
    print("  plex addon remove plextickets MyAddon")
    print("  plex addon config plextickets MyAddon")


def _is_newer_version(remote: str, local: str) -> bool:
    """Compare semantic-ish version strings."""
    if is_newer_version is not None:
        return bool(is_newer_version(remote, local))
    try:
        remote_parts = [int(x) for x in remote.split(".")]
        local_parts = [int(x) for x in local.split(".")]
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
    if ensure_cli_entrypoints is not None:
        return ensure_cli_entrypoints()
    # Fallback if shared module not available
    if os.geteuid() != 0:
        return
    try:
        bin_dir = Path("/usr/local/bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        for name, target in {
            "plexinstaller": INSTALLER_DIR / "installer.py",
            "plex": INSTALLER_DIR / "plex_cli.py",
        }.items():
            link_path = bin_dir / name
            if not target.exists():
                continue
            if link_path.is_symlink() or link_path.exists():
                link_path.unlink(missing_ok=True)
            link_path.symlink_to(target)
    except Exception:
        return


def _verify_gpg_signature(version_json_bytes: bytes) -> bool:
    """Download version.json.sig and verify version.json against it."""
    if verify_gpg_signature is not None:
        return bool(
            verify_gpg_signature(
                version_json_bytes,
                print_info=print_info,
                print_success=print_success,
                print_warning=print_warning,
                print_error=print_error,
            )
        )
    # Fallback: skip verification if shared module unavailable
    print_error("Shared module unavailable — update verification cannot continue")
    return False


def _perform_update(version_data: dict, version_json_bytes: bytes = b""):
    """Download and install new installer version with checksum verification."""
    if perform_update is not None:
        return perform_update(
            version_data,
            version_json_bytes,
            print_info=print_info,
            print_success=print_success,
            print_warning=print_warning,
            print_error=print_error,
        )
    # Fallback if shared module unavailable
    print_warning("Shared module unavailable — cannot perform update.")


def _maybe_auto_update():
    """Check for installer updates and prompt if a newer version is available."""
    if not sys.stdin.isatty():
        return

    try:
        with urllib.request.urlopen(VERSION_CHECK_URL, timeout=5) as response:
            version_json_bytes = response.read()
        version_data = json.loads(version_json_bytes.decode())
        if not _verify_gpg_signature(version_json_bytes):
            return
        remote_version = version_data.get("version", "0.0.0")
        local_version = _read_local_installer_version()

        if _is_newer_version(remote_version, local_version):
            print_warning(f"New installer version available: {remote_version} (current: {local_version})")
            changelog = version_data.get("changelog", [])
            if changelog:
                print(f"\n{CYAN}Changelog:{NC}")
                for item in changelog:
                    print(f"  • {item}")
            choice = input(f"\n{YELLOW}Auto-update to latest version? (y/n): {NC}").strip().lower()
            if choice == "y":
                _perform_update(version_data, version_json_bytes)
    except KeyboardInterrupt:
        return
    except Exception:
        # Never block normal CLI usage if update checks fail.
        return
    finally:
        _ensure_cli_entrypoints()


def get_installed_apps() -> list[str]:
    """Get list of installed Plex and Drako applications."""
    apps: list[str] = []
    if not INSTALL_DIR.exists():
        return apps

    for app_dir in INSTALL_DIR.iterdir():
        if app_dir.is_dir() and (app_dir / "package.json").exists():
            # Skip backups directory
            if app_dir.name != "backups":
                apps.append(app_dir.name)

    return sorted(apps)


def resolve_app_instance(name: str) -> str | None:
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

    if normalized in by_lower:
        return by_lower[normalized]

    aliases = Config.equivalent_instance_names(normalized) if Config is not None else (normalized,)

    # Exact match, followed by exact current/legacy brand aliases.
    exact_candidates = {by_lower[candidate] for candidate in aliases if candidate in by_lower}
    if len(exact_candidates) == 1:
        return next(iter(exact_candidates))
    if len(exact_candidates) > 1:  # pragma: no cover - exact-match check above prevents this
        print_error(f"Both current and legacy installations match '{name}'. Specify the exact directory name:")
        for app in sorted(exact_candidates):
            print(f"  - {app}")
        return None

    # Unambiguous family-prefix match for multi-instance installs.
    base_aliases = Config.equivalent_product_names(normalized) if Config is not None else (normalized,)
    candidates = [app for app in installed if any(app.lower().startswith(f"{base}-") for base in base_aliases)]
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


def get_service_status(service_name: str) -> dict[str, object]:
    """Get detailed service status"""
    try:
        result = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
        is_active = result.stdout.strip() == "active"

        result = subprocess.run(["systemctl", "is-enabled", service_name], capture_output=True, text=True)
        is_enabled = result.stdout.strip() == "enabled"

        if is_active:
            status = "Running"
            color = GREEN
        elif is_enabled:
            status = "Stopped"
            color = YELLOW
        else:
            status = "Disabled"
            color = RED

        return {"status": status, "color": color, "active": is_active, "enabled": is_enabled}
    except Exception:
        return {"status": "Unknown", "color": RED, "active": False, "enabled": False}


def list_apps(json_output: bool = False):
    """List all installed Plex and Drako applications."""
    print_info("Scanning for installed Plex/Drako applications...")
    apps = get_installed_apps()

    if not apps:
        print_error(f"No Plex/Drako applications found in {INSTALL_DIR}")
        return 1

    if json_output:
        payload = []
        for app in apps:
            status_info = get_service_status(get_service_name(app))
            payload.append(
                {
                    "name": app,
                    "path": str(INSTALL_DIR / app),
                    "status": status_info["status"],
                    "active": status_info["active"],
                    "enabled": status_info["enabled"],
                }
            )
        print(json.dumps(payload, indent=2))
        return EXIT_OK

    print()
    print(f"{BOLD}{CYAN}Installed Plex/Drako Applications:{NC}")
    print()

    for app in apps:
        service_name = get_service_name(app)
        app_dir = INSTALL_DIR / app
        status_info = get_service_status(service_name)

        print(f"{BOLD}{app}{NC}")
        print(f"  Status: {status_info['color']}{status_info['status']}{NC}")
        print(f"  Path: {app_dir}")

        # Show config file if exists
        for config_name in ["config.yml", "config.yaml", "config.json"]:
            config_file = app_dir / config_name
            if config_file.exists():
                print(f"  Config: {config_file}")
                break

        # Show if enabled on boot
        if status_info["enabled"]:
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
        subprocess.run(["systemctl", "start", service_name], check=True)
        print_success(f"{instance} started successfully")

        # Wait a moment and check if it's actually running
        import time

        time.sleep(2)

        status_info = get_service_status(service_name)
        if status_info["active"]:
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
        subprocess.run(["systemctl", "stop", service_name], check=True)
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
        subprocess.run(["systemctl", "restart", service_name], check=True)
        print_success(f"{instance} restarted successfully")

        # Wait a moment and check if it's running
        import time

        time.sleep(2)

        status_info = get_service_status(service_name)
        if status_info["active"]:
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
        subprocess.run(["systemctl", "status", service_name, "--no-pager", "-l"])
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
        subprocess.run(["journalctl", "-u", service_name, "-f", "--no-pager"])
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
    for config_name in ["config.yml", "config.yaml", "config.json"]:
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

    if _run_editor(config_file) != EXIT_OK:
        return EXIT_ERROR
    print()
    print(f"{YELLOW}Configuration file updated. Restart the application to apply changes:{NC}")
    print(f"  {GREEN}plex restart {instance}{NC}")
    return EXIT_OK


def enable_app(app: str):
    """Enable application to start on boot"""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1

    service_name = get_service_name(instance)
    print_info(f"Enabling {instance} to start on boot...")

    try:
        subprocess.run(["systemctl", "enable", service_name], check=True)
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
        subprocess.run(["systemctl", "disable", service_name], check=True)
        print_success(f"{instance} will no longer start automatically on boot")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to disable {instance}")
        return 1


def debug_app(app: str, *, assume_yes: bool = False, non_interactive: bool = False) -> int:
    """Upload redacted config + recent logs for support."""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1

    app_dir = INSTALL_DIR / instance
    config_path = None
    for config_name in ["config.yml", "config.yaml", "config.json"]:
        candidate = app_dir / config_name
        if candidate.exists():
            config_path = candidate
            break

    if config_path:
        try:
            config_contents = config_path.read_text(encoding="utf-8", errors="replace")
            config_contents = redact_config_contents(config_contents, config_path.suffix)
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

    bundle = redact_debug_text(bundle)

    if not debug_bundle_is_safe(bundle):
        print_error("Debug upload blocked because redaction could not safely mask every detected secret")
        return EXIT_ERROR

    paste_endpoint = "https://paste.plexdev.xyz/documents"
    if Config is not None:
        try:
            paste_endpoint = Config.PASTE_ENDPOINT
        except Exception:
            pass

    if requests is None:
        print_error("Python package 'requests' is required for plex debug uploads")
        return 1

    print_warning(
        "Review the redacted bundle before sharing; automated redaction cannot guarantee removal of every secret."
    )
    if not _confirm(
        "Upload this redacted debug bundle to the configured paste service?",
        assume_yes=assume_yes,
        non_interactive=non_interactive,
    ):
        print_info("Debug upload cancelled")
        return EXIT_OK

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
    base_product = app.split("-")[0]
    return base_product.lower() in ["plextickets", "plexstaff"]


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
        config_status = addon["config_path"].name if addon["has_config"] else "No config"
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

    supported_suffixes = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz")
    if not archive.name.lower().endswith(supported_suffixes):
        print_error(f"Unsupported archive format: {archive.name}")
        print_info("Supported formats: ZIP and TAR archives")
        return 1

    app_dir = INSTALL_DIR / instance

    # Check for collision
    potential_name = archive.stem
    for suffix in ["-main", "-master", "-addon", "-v1", "-v2"]:
        if potential_name.lower().endswith(suffix):
            potential_name = potential_name[: -len(suffix)]

    if addon_mgr.addon_exists(potential_name, app_dir):
        print_error(f"Addon '{potential_name}' already exists.")
        print_info(f"Remove the existing addon first: plex addon remove {instance} {potential_name}")
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

    if _run_editor(config_path) != EXIT_OK:
        return EXIT_ERROR

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
    return EXIT_OK


def handle_addon_command(args: list[str]) -> int:
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

    if subcommand == "list":
        if len(args) < 2:  # pragma: no cover - rejected earlier in handle_addon_command
            print_error("Usage: plex addon list <app>")
            return 1
        return addon_list(args[1])

    elif subcommand == "install":
        if len(args) < 3:
            print_error("Usage: plex addon install <app> <archive_path>")
            return 1
        return addon_install(args[1], args[2])

    elif subcommand == "remove":
        if len(args) < 3:
            print_error("Usage: plex addon remove <app> <addon_name>")
            return 1
        return addon_remove(args[1], args[2])

    elif subcommand in ["config", "configure"]:
        if len(args) < 3:
            print_error("Usage: plex addon config <app> <addon_name>")
            return 1
        return addon_config(args[1], args[2])

    else:
        print_error(f"Unknown addon subcommand: {subcommand}")
        print_info("Use 'plex addon' for usage information")
        return 1


# ========== END ADDON MANAGEMENT CLI ==========


# ========== TOOL COMMANDS ==========


def tool_setupdomain(app: str) -> int:
    """Set up domain, nginx reverse proxy, and SSL for an existing instance."""
    instance = resolve_app_instance(app)
    if not instance:
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1

    if os.geteuid() != 0:
        print_error("This command must be run as root (use sudo).")
        return 1

    app_dir = INSTALL_DIR / instance

    # Detect current port from config
    port = None
    for config_name in ["config.yml", "config.yaml", "config.json"]:
        config_file = app_dir / config_name
        if config_file.exists():
            try:
                content = config_file.read_text()
                if config_file.suffix.lower() == ".json":
                    data = json.loads(content)
                    value = next((data[key] for key in ("Port", "port", "PORT") if key in data), None)
                    if isinstance(value, int) and 1 <= value <= 65535:
                        port = value
                        break
                else:
                    match = re.search(r"^\s*port\s*:\s*(\d+)", content, re.IGNORECASE | re.MULTILINE)
                    if match:
                        port = int(match.group(1))
                        break
            except Exception:
                pass

    def prompt_for_port(prompt: str) -> int:
        while True:
            port_input = input(prompt).strip()
            if port_input.isdigit():
                selected_port = int(port_input)
                if 1 <= selected_port <= 65535:
                    return selected_port
                print_error("Port must be between 1 and 65535.")
            else:
                print_error("Port must be a number.")

    if port is None:
        port = prompt_for_port("Could not detect port from config. Enter port: ")
    else:
        print_info(f"Detected port: {port}")
        while True:
            port_input = input("Use this port? (Y/n, or enter a different port): ").strip().lower()
            if port_input in {"", "y", "yes"}:
                break
            if port_input in {"n", "no"}:
                port = prompt_for_port("Enter a new port: ")
                break
            if port_input.isdigit():
                selected_port = int(port_input)
                if 1 <= selected_port <= 65535:
                    port = selected_port
                    break
                print_error("Port must be between 1 and 65535.")
            else:
                print_error("Port must be a number, or enter y/yes/n/no.")

    if Config is None:
        print_error("Configuration module unavailable; cannot persist the selected port safely")
        return EXIT_ERROR

    # Get domain
    domain_pattern = re.compile(
        r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
        r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
    )
    domain = ""
    while not domain:
        domain = input(f"Enter domain (e.g., {instance}.example.com): ").strip()
        if not domain:
            print_error("Domain cannot be empty")
        elif not domain_pattern.match(domain):
            print_error("Invalid domain format. Please enter a valid domain.")
            domain = ""

    # Get email for SSL
    email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    email = ""
    while not email:
        email = input("Enter email for SSL certificates: ").strip()
        if not email:
            print_error("Email cannot be empty")
        elif not email_pattern.match(email):
            print_error("Invalid email format. Please enter a valid email.")
            email = ""

    # Import utility classes
    try:
        from utils import DNSChecker, FirewallManager, NginxManager, SSLManager
    except ImportError:
        # Try from the installer directory
        import importlib.util

        utils_path = INSTALLER_DIR / "utils.py"
        if utils_path.exists():
            spec = importlib.util.spec_from_file_location("utils", utils_path)
            assert spec is not None and spec.loader is not None
            utils_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(utils_mod)  # type: ignore[union-attr]
            DNSChecker = utils_mod.DNSChecker  # type: ignore[misc]
            NginxManager = utils_mod.NginxManager  # type: ignore[misc]
            SSLManager = utils_mod.SSLManager  # type: ignore[misc]
            FirewallManager = utils_mod.FirewallManager  # type: ignore[misc]
        else:
            print_error("Cannot import utility modules. Is the installer properly installed?")
            return 1

    dns_checker = DNSChecker()
    firewall = FirewallManager()
    nginx = NginxManager()
    ssl_mgr = SSLManager()
    nginx_config = nginx.config.nginx_available / f"{domain}.conf"
    nginx_enabled = nginx.config.nginx_enabled / f"{domain}.conf"
    if nginx_config.exists() or nginx_enabled.exists() or nginx_enabled.is_symlink():
        print_error(f"Nginx configuration already exists for {domain}; refusing to overwrite it")
        return EXIT_ERROR

    # Check DNS
    if not dns_checker.check(domain):
        proceed = input("DNS check failed. Proceed anyway? (y/n): ").strip().lower()
        if proceed != "y":
            print_error("Setup aborted due to DNS issues.")
            return 1

    # Setup nginx
    print_info(f"Configuring Nginx reverse proxy for {domain} -> localhost:{port}...")
    try:
        nginx.setup(domain, port, instance, app_dir)
        print_success("Nginx configured successfully")
    except Exception as e:
        print_error(f"Nginx setup failed: {e}")
        _rollback_setupdomain(domain, nginx=nginx, remove_nginx=True)
        return 1

    # Setup SSL
    print_info(f"Setting up SSL certificate for {domain}...")
    try:
        ssl_mgr.setup(domain, email)
        print_success("SSL certificate obtained successfully")
    except Exception as e:
        print_error(f"SSL setup failed: {e}")
        _rollback_setupdomain(domain, nginx=nginx, ssl_manager=ssl_mgr, remove_nginx=True)
        return 1

    try:
        Config().persist_app_port(app_dir, port)
    except Exception as exc:
        print_error(f"Could not persist selected application port: {exc}")
        _rollback_setupdomain(domain, nginx=nginx, ssl_manager=ssl_mgr, remove_nginx=True)
        return EXIT_ERROR

    # A reverse-proxied app port must not remain public.
    try:
        firewall.close_port(port)
    except Exception as exc:
        print_warning(f"Could not verify app-port firewall cleanup: {exc}")

    _record_domain_resources(app_dir, instance, domain, port)

    print()
    print_success(f"Domain setup complete! Access your instance at: https://{domain}")
    print_info(f"Restart the service to apply any changes: plex restart {instance}")
    return 0


def _rollback_setupdomain(domain: str, *, nginx, ssl_manager=None, remove_nginx: bool = True) -> None:
    """Best-effort rollback for nginx files and partial certificate state."""
    if ssl_manager is not None:
        try:
            subprocess.run(
                ["certbot", "delete", "--cert-name", domain, "--non-interactive"],
                check=False,
                capture_output=True,
            )
        except OSError:
            pass
    if remove_nginx:
        config = getattr(nginx, "config", None)
        for directory_name in ("nginx_enabled", "nginx_available"):
            directory = getattr(config, directory_name, None)
            if directory is None:
                continue
            path = Path(directory) / f"{domain}.conf"
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    try:
        subprocess.run(["nginx", "-t"], check=False, capture_output=True)
        subprocess.run(["systemctl", "reload", "nginx"], check=False, capture_output=True)
    except OSError:
        pass


def _record_domain_resources(app_dir: Path, instance: str, domain: str, port: int) -> None:
    """Update an installer resource manifest after successful CLI domain setup."""
    manifest = app_dir / ".plexinstaller-resources.json"
    data: dict[str, Any] = {}
    try:
        parsed = json.loads(manifest.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            data = parsed
    except (OSError, ValueError, TypeError):
        pass
    data.update(
        {
            "schema_version": 1,
            "instance": instance,
            "install_path": str(app_dir.resolve()),
            "port": port,
            "firewall_port": None,
            "domain": domain,
            "nginx": True,
            "certificate": True,
            "service": data.get("service", f"plex-{instance}"),
            "mongodb": data.get("mongodb", {}),
        }
    )
    temporary = manifest.with_name(f".{manifest.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, manifest)
    finally:
        temporary.unlink(missing_ok=True)


def handle_tool_command(args: list) -> int:
    """Handle tool subcommands."""
    if len(args) < 1:
        print_error("Usage: plex tool <subcommand> [options]")
        print()
        print(f"{YELLOW}Available tools:{NC}")
        print(f"  {GREEN}setupdomain <app>{NC}  - Set up domain, reverse proxy & SSL for an instance")
        return 1

    subcommand = args[0].lower()

    if subcommand == "setupdomain":
        if len(args) < 2:
            print_error("Usage: plex tool setupdomain <app>")
            print("Use 'plex list' to see installed applications")
            return 1
        return tool_setupdomain(args[1])
    else:
        print_error(f"Unknown tool subcommand: {subcommand}")
        print_info("Use 'plex tool' for usage information")
        return 1


# ========== END TOOL COMMANDS ==========


class _Parser(argparse.ArgumentParser):
    """Argument parser with a stable EX_USAGE-compatible error code."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI grammar without executing a command."""
    parser = _Parser(prog="plex", description="Manage PlexDevelopment applications")
    parser.add_argument("--yes", "-y", action="store_true", help="accept destructive/upload confirmations")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; fail or use safe defaults")
    parser.add_argument("--no-update-check", action="store_true", help="skip the installer update check")
    parser.add_argument("--json", action="store_true", dest="json_output", help="emit JSON where supported")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("list", aliases=["ls"], help="list installed applications")
    for command in ("start", "stop", "restart", "status", "logs", "enable", "disable"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("app")
    config_parser = subparsers.add_parser("config", aliases=["configure"])
    config_parser.add_argument("app")
    debug_parser = subparsers.add_parser("debug")
    debug_parser.add_argument("app")

    addon_parser = subparsers.add_parser("addon")
    addon_parser.add_argument("addon_args", nargs=argparse.REMAINDER)
    tool_parser = subparsers.add_parser("tool")
    tool_parser.add_argument("tool_args", nargs=argparse.REMAINDER)
    subparsers.add_parser("help")
    return parser


def main(argv: Sequence[str] | None = None):
    """Main entry point."""
    try:
        from utils import setup_logging

        setup_logging()
    except Exception:  # pragma: no cover
        pass

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.command:
        show_help()
        return EXIT_USAGE

    if not args.no_update_check:
        _maybe_auto_update()

    command = args.command.lower()
    if command in {"list", "ls"}:
        return list_apps(json_output=args.json_output)
    if command == "start":
        return start_app(args.app)
    if command == "stop":
        return stop_app(args.app)
    if command == "restart":
        return restart_app(args.app)
    if command == "status":
        return show_status(args.app)
    if command == "logs":
        return view_logs(args.app)
    if command in {"config", "configure"}:
        if args.non_interactive:
            print_error("config cannot run in non-interactive mode")
            return EXIT_USAGE
        return edit_config(args.app)
    if command == "enable":
        return enable_app(args.app)
    if command == "disable":
        return disable_app(args.app)
    if command == "debug":
        return debug_app(args.app, assume_yes=args.yes, non_interactive=args.non_interactive)
    if command == "addon":
        return handle_addon_command(args.addon_args)
    if command == "tool":
        if args.non_interactive:
            print_error("interactive tools cannot run with --non-interactive")
            return EXIT_USAGE
        return handle_tool_command(args.tool_args)
    if command == "help":
        show_help()
        return EXIT_OK
    return EXIT_USAGE  # pragma: no cover - argparse restricts commands


if __name__ == "__main__":
    sys.exit(main())
