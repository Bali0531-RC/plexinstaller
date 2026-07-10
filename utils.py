#!/usr/bin/env python3
"""
Utility functions for PlexDevelopment Installer — Windows version

All Linux-specific code (systemd, apt, ufw, certbot, chown, etc.) has been
replaced with Windows equivalents (NSSM / sc.exe, winget / choco, netsh,
win-acme, etc.).
"""

import ctypes
import errno
import ipaddress
import logging
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from colorama import Fore, Style
from colorama import init as colorama_init

# Initialize colorama for cross-platform support
colorama_init(autoreset=False)

logger = logging.getLogger("plexinstaller")


def clear_terminal() -> None:
    """Clear an interactive terminal without invoking a shell."""
    try:
        if not sys.stdout.isatty():
            return
    except (AttributeError, OSError):
        return

    if os.name != "nt" and not os.environ.get("TERM"):
        return

    command = ["cmd", "/c", "cls"] if os.name == "nt" else ["clear"]
    try:
        subprocess.run(command, check=False)
    except OSError:
        pass


def setup_logging(level: int = logging.INFO, log_file: str | None = None):
    """Configure structured logging for the application.

    Call once at startup from the main entry point.  If *log_file* is
    given, a file handler is added at DEBUG level for richer diagnostics.
    Console output is handled by ColorPrinter — the logger only writes
    to the log file to avoid duplicate/noisy terminal output.
    """
    root = logging.getLogger("plexinstaller")
    root.setLevel(logging.DEBUG)

    if not root.handlers:
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        if log_file:
            fh = logging.FileHandler(log_file)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(fmt)
            root.addHandler(fh)
        else:
            root.addHandler(logging.NullHandler())


class ColorPrinter:
    """Colored output printer"""

    RED = Fore.RED
    GREEN = Fore.GREEN
    YELLOW = Fore.YELLOW
    BLUE = Fore.BLUE
    PURPLE = Fore.MAGENTA
    CYAN = Fore.CYAN
    BOLD = Style.BRIGHT
    NC = Style.RESET_ALL

    def header(self, message: str):
        print(f"\n{self.BOLD}{self.PURPLE}#----- {message} -----#{self.NC}\n", file=sys.stderr)
        logger.info(message)

    def step(self, message: str):
        print(f"{self.BLUE}[+] {self.CYAN}{message}{self.NC}", file=sys.stderr)
        logger.info(message)

    def success(self, message: str):
        print(f"{self.GREEN}[✓] {message}{self.NC}", file=sys.stderr)
        logger.info(message)

    def error(self, message: str):
        print(f"{self.RED}[✗] {message}{self.NC}", file=sys.stderr)
        logger.error(message)

    def warning(self, message: str):
        print(f"{self.YELLOW}[!] {message}{self.NC}", file=sys.stderr)
        logger.warning(message)


class SystemDetector:
    """Windows system detection and package management"""

    def __init__(self):
        self.printer = ColorPrinter()
        self.distribution = "windows"
        self.pkg_manager = None

    def detect(self):
        """Detect Windows version and available package manager"""
        self.printer.header("System Detection")

        import platform as _plat

        self.printer.step(f"Detected OS: Windows {_plat.version()}")

        # Prefer winget, fall back to choco
        if shutil.which("winget"):
            self.pkg_manager = "winget"
        elif shutil.which("choco"):
            self.pkg_manager = "choco"
        else:
            self.printer.warning("No package manager found (winget or chocolatey)")
            self.printer.step("Install winget from the Microsoft Store or chocolatey from https://chocolatey.org")

        if self.pkg_manager:
            self.printer.success(f"Using package manager: {self.pkg_manager}")

    def install_dependencies(self):
        """Install system dependencies via winget or choco"""
        from config import Config

        self.printer.header("Installing Dependencies")

        if self.pkg_manager is None:
            self.printer.error("Package manager not detected. Run detect() first.")
            return

        config = Config()
        packages = config.SYSTEM_PACKAGES.get(self.pkg_manager, [])

        if not packages:
            self.printer.warning(f"No package list for {self.pkg_manager}")
            return

        self.printer.step(f"Installing {len(packages)} packages via {self.pkg_manager}...")

        for pkg in packages:
            try:
                if self.pkg_manager == "winget":
                    subprocess.run(
                        [
                            "winget",
                            "install",
                            "--id",
                            pkg,
                            "--accept-package-agreements",
                            "--accept-source-agreements",
                        ],
                        check=True,
                        capture_output=True,
                    )
                elif self.pkg_manager == "choco":
                    subprocess.run(["choco", "install", pkg, "-y"], check=True, capture_output=True)
                self.printer.success(f"Installed {pkg}")
            except subprocess.CalledProcessError:
                self.printer.warning(f"Failed to install {pkg} (may already be installed)")

        # Verify Node.js
        self._verify_nodejs()

    def _verify_nodejs(self):
        """Verify Node.js is installed and reachable."""
        node_cmd = shutil.which("node") or "node"
        try:
            result = subprocess.run([node_cmd, "-v"], capture_output=True, text=True)
            version = result.stdout.strip()
            self.printer.step(f"Node.js version: {version}")
        except FileNotFoundError:
            self.printer.error("Node.js not found. Install it via winget or from https://nodejs.org")


class DNSChecker:
    """DNS verification utilities"""

    def __init__(self):
        self.printer = ColorPrinter()

    def check(self, domain: str) -> bool:
        """Check if domain points to this server"""
        self.printer.step(f"Checking DNS for: {domain}")

        server_ip = self._get_public_ip()
        if not server_ip:
            self.printer.error("Cannot determine server IP")
            return False

        self.printer.step(f"Server IP: {server_ip}")

        try:
            domain_ip = socket.gethostbyname(domain)
            self.printer.step(f"Domain resolves to: {domain_ip}")

            if domain_ip == server_ip:
                self.printer.success("DNS is correctly configured")
                return True
            else:
                self.printer.warning(f"DNS mismatch: {domain_ip} != {server_ip}")
                return False
        except socket.gaierror:
            self.printer.error(f"Cannot resolve domain: {domain}")
            return False

    def _get_public_ip(self) -> str | None:
        """Get server's public IP address via HTTP"""
        services = ["https://api.ipify.org", "https://ifconfig.me", "https://icanhazip.com"]

        for service in services:
            try:
                req = urllib.request.Request(service, headers={"User-Agent": "curl/7.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    candidate = resp.read().decode().strip()
                    try:
                        address = ipaddress.ip_address(candidate)
                    except ValueError:
                        continue
                    if isinstance(address, ipaddress.IPv4Address):
                        return str(address)
            except Exception:
                continue

        return None


# ===== Sensitive-value redaction (unchanged from Linux) =====

SENSITIVE_YAML_KEYS = {
    "token",
    "mongouri",
    "licensekey",
    "secretkey",
}


def redact_mongo_uri_credentials(value: str) -> str:
    """Redact username/password in mongodb:// and mongodb+srv:// URIs."""

    def _repl(match: re.Match) -> str:
        scheme = match.group("scheme")
        host_part = match.group("host")
        return f"{scheme}://<REDACTED>:<REDACTED>@{host_part}"

    return re.sub(
        r"(?P<scheme>mongodb(?:\+srv)?)://(?P<user>[^:@/\s]+):(?P<pw>[^@/\s]+)@(?P<host>[^/\s]+)",
        _repl,
        value,
        flags=re.IGNORECASE,
    )


def redact_sensitive_yaml(text: str) -> str:
    """Redact known sensitive values in YAML-ish files without parsing YAML."""
    lines: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            lines.append(line)
            continue

        match = re.match(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_\-]+)\s*:\s*(?P<value>.*)$", line)
        if match:
            key = match.group("key")
            if key.lower() in SENSITIVE_YAML_KEYS:
                value_part = match.group("value")
                comment = ""
                if "#" in value_part:
                    before, after = value_part.split("#", 1)
                    comment = "#" + after
                redacted = f'{match.group("indent")}{key}: "<REDACTED>"'
                if comment:
                    redacted = f"{redacted} {comment.strip()}"
                lines.append(redacted)
                continue

            value_part = match.group("value")
            redacted_value = redact_mongo_uri_credentials(value_part)
            if redacted_value != value_part:
                lines.append(f"{match.group('indent')}{key}: {redacted_value}")
                continue

        lines.append(redact_mongo_uri_credentials(line))

    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


# ===== Windows Firewall =====


class FirewallManager:
    """Windows Firewall management via netsh advfirewall"""

    def __init__(self):
        self.printer = ColorPrinter()

    @staticmethod
    def rule_name(port: int, description: str) -> str:
        """Return the exact deterministic rule name owned by this installer."""
        safe_description = validate_path_component(description, label="firewall rule description")
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return f"PlexInstaller-{safe_description}-{port}"

    def open_port(self, port: int, description: str):
        """Open one installer-owned firewall rule and report success."""
        self.printer.step(f"Opening port {port} for {description}")

        rule_name = self.rule_name(port, description)
        try:
            subprocess.run(
                [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "add",
                    "rule",
                    f"name={rule_name}",
                    "dir=in",
                    "action=allow",
                    "protocol=tcp",
                    f"localport={port}",
                    f"description=PlexInstaller managed rule for {description}",
                ],
                check=True,
                capture_output=True,
            )
            self.printer.success(f"Port {port} opened in Windows Firewall")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.printer.warning("Failed to open port in Windows Firewall (run as Administrator)")
            return False

    def close_port(self, port: int, description: str | None = None):
        """Remove only the exact installer-created firewall rule."""
        self.printer.step(f"Reverting firewall rule on port {port}")

        if not description:
            self.printer.warning("Firewall rule description is required for safe removal")
            return False

        rule_name = self.rule_name(port, description)

        try:
            subprocess.run(
                [
                    "netsh",
                    "advfirewall",
                    "firewall",
                    "delete",
                    "rule",
                    f"name={rule_name}",
                ],
                check=True,
                capture_output=True,
            )
            self.printer.success(f"Port {port} rule removed from Windows Firewall")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.printer.warning("Failed to remove Windows Firewall rule")
            return False


# ===== Nginx (Windows portable build) =====


class NginxManager:
    """Nginx configuration management — Windows portable nginx"""

    def __init__(self):
        self.printer = ColorPrinter()
        from config import Config

        self.config = Config()

    def setup(self, domain: str, port: int, service_name: str, install_path: Path):
        """Setup nginx reverse proxy"""
        self.printer.step(f"Configuring Nginx for {service_name}")

        config_file = self.config.nginx_available / f"{domain}.conf"

        # Use forward slashes for nginx config compatibility
        install_path_str = str(install_path).replace("\\", "/")

        nginx_config = f"""server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://localhost:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_connect_timeout 120s;
    }}

    # Custom 502 error page
    error_page 502 /502.html;
    location = /502.html {{
        root {install_path_str};
        internal;
    }}
}}
"""

        # Ensure dirs exist
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(nginx_config)

        # Copy to enabled dir (no symlinks on Windows)
        enabled_file = self.config.nginx_enabled / f"{domain}.conf"
        enabled_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(config_file), str(enabled_file))

        # Reload nginx if running
        nginx_exe = shutil.which("nginx")
        if nginx_exe:
            try:
                subprocess.run([nginx_exe, "-t"], check=True, capture_output=True)
                subprocess.run([nginx_exe, "-s", "reload"], check=True, capture_output=True)
                self.printer.success("Nginx configured and reloaded")
            except subprocess.CalledProcessError as e:
                stderr = e.stderr.decode(errors="replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
                stdout = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
                self.printer.error(f"Nginx configuration failed: {(stderr or stdout or str(e)).strip()}")
                raise
        else:
            self.printer.warning("Nginx not found in PATH — config written but not reloaded")
            self.printer.step("Download nginx for Windows: https://nginx.org/en/docs/windows.html")

    def remove(self, domain: str) -> bool:
        """Remove one managed site and reload nginx when available."""
        removed = False
        for path in (
            self.config.nginx_enabled / f"{domain}.conf",
            self.config.nginx_available / f"{domain}.conf",
        ):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                pass
        nginx_exe = shutil.which("nginx")
        if nginx_exe:
            test = subprocess.run([nginx_exe, "-t"], capture_output=True, text=True, timeout=30)
            if test.returncode != 0:
                detail = (test.stderr or test.stdout or "nginx -t failed").strip()
                raise RuntimeError(detail)
            subprocess.run([nginx_exe, "-s", "reload"], check=True, capture_output=True, timeout=30)
        return removed


# ===== SSL (win-acme / certbot) =====


class SSLManager:
    """SSL certificate management — Windows"""

    def __init__(self):
        self.printer = ColorPrinter()

    @staticmethod
    def _backend() -> tuple[str, str]:
        wacs = shutil.which("wacs") or shutil.which("wacs.exe")
        if wacs:
            return "wacs", wacs
        certbot = shutil.which("certbot") or shutil.which("certbot.exe")
        if certbot:
            return "certbot", certbot
        raise FileNotFoundError("No SSL tool available; install win-acme or certbot")

    def setup(self, domain: str, email: str):
        """Setup SSL certificate using win-acme or certbot"""
        self.printer.step(f"Setting up SSL for {domain}")

        try:
            backend, executable = self._backend()
        except FileNotFoundError:
            self.printer.error("No SSL tool found.")
            self.printer.step("Install win-acme: https://www.win-acme.com/")
            self.printer.step("Or certbot: https://certbot.eff.org/")
            raise

        if backend == "wacs":
            try:
                subprocess.run(
                    [
                        executable,
                        "--target",
                        "manual",
                        "--host",
                        domain,
                        "--emailaddress",
                        email,
                        "--accepttos",
                    ],
                    check=True,
                    timeout=600,
                )
                self.printer.success("SSL certificate obtained via win-acme")
            except subprocess.CalledProcessError:
                self.printer.error("SSL setup via win-acme failed")
                raise
        else:
            try:
                subprocess.run(
                    [
                        executable,
                        "certonly",
                        "--standalone",
                        "-d",
                        domain,
                        "--non-interactive",
                        "--agree-tos",
                        "--email",
                        email,
                    ],
                    check=True,
                    timeout=600,
                )
                self.printer.success("SSL certificate obtained via certbot")
            except subprocess.CalledProcessError:
                self.printer.error("SSL setup via certbot failed")
                raise

    def setup_auto_renewal(self) -> bool:
        """On Windows, win-acme handles auto-renewal via a scheduled task."""
        backend, executable = self._backend()
        if backend == "wacs":
            self.printer.step("win-acme manages renewal through its scheduled task.")
            return True
        subprocess.run([executable, "renew"], check=True, timeout=600)
        return True

    def status(self) -> bool:
        """Display certificate status using the active backend."""
        backend, executable = self._backend()
        command = [executable, "--list"] if backend == "wacs" else [executable, "certificates"]
        return subprocess.run(command, check=False, timeout=120).returncode == 0

    def renew(self, *, force: bool = False) -> bool:
        """Renew certificates using the active backend."""
        backend, executable = self._backend()
        command = [executable, "--renew", "--force"] if backend == "wacs" else [executable, "renew"]
        if backend == "certbot" and force:
            command.append("--force-renewal")
        subprocess.run(command, check=True, timeout=600)
        return True

    def test_renewal(self) -> bool:
        """Test renewal using backend-supported dry-run semantics."""
        backend, executable = self._backend()
        command = [executable, "--renew", "--test"] if backend == "wacs" else [executable, "renew", "--dry-run"]
        subprocess.run(command, check=True, timeout=600)
        return True

    def delete(self, domain: str) -> bool:
        """Delete a domain certificate/renewal using the active backend."""
        backend, executable = self._backend()
        command = (
            [executable, "--cancel", "--host", domain]
            if backend == "wacs"
            else [executable, "delete", "--cert-name", domain, "--non-interactive"]
        )
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
        return result.returncode == 0

    def view_logs(self, lines: int = 50) -> bool:
        """Print recent backend logs without shell interpolation."""
        backend, _ = self._backend()
        if backend == "wacs":
            log_dir = (
                Path(os.environ.get("ProgramData", r"C:\ProgramData"))
                / "win-acme"
                / "acme-v02.api.letsencrypt.org"
                / "Log"
            )
        else:
            log_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "certbot" / "log"
        files = sorted(log_dir.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not files:
            self.printer.warning(f"SSL log file not found under {log_dir}")
            return False
        for line in files[0].read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]:
            print(line)
        return True

    def certificate_present(self, domain: str) -> bool:
        """Return whether the active backend reports a certificate for *domain*."""
        try:
            backend, executable = self._backend()
            command = [executable, "--list"] if backend == "wacs" else [executable, "certificates"]
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            return result.returncode == 0 and domain.casefold() in (result.stdout or "").casefold()
        except (OSError, subprocess.SubprocessError):
            return False


# ===== Service Management (NSSM / sc.exe) =====


class ServiceManager:
    """Windows service management using NSSM (preferred) or sc.exe"""

    def __init__(self):
        self.printer = ColorPrinter()

    @staticmethod
    def _normalize_service_name(service_name: str) -> str:
        return service_name if service_name.startswith("plex-") else f"plex-{service_name}"

    def create_service(self, service_name: str, install_path: Path) -> bool:
        """Create and start a Windows service for the application."""
        win_svc = self._normalize_service_name(service_name)
        node_exe = shutil.which("node") or shutil.which("node.exe")
        nssm = shutil.which("nssm") or shutil.which("nssm.exe")
        if not nssm:
            raise FileNotFoundError("NSSM is required to run Node.js as a Windows service. Install NSSM and retry.")
        if not node_exe:
            raise FileNotFoundError("Node.js executable was not found in PATH")

        log_dir = install_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        commands = (
            [nssm, "install", win_svc, node_exe, "."],
            [nssm, "set", win_svc, "AppDirectory", str(install_path)],
            [nssm, "set", win_svc, "AppStdout", str(log_dir / "service-out.log")],
            [nssm, "set", win_svc, "AppStderr", str(log_dir / "service-error.log")],
            [nssm, "set", win_svc, "AppRotateFiles", "1"],
            [nssm, "set", win_svc, "Description", f"PlexDevelopment - {service_name}"],
            [nssm, "set", win_svc, "Start", "SERVICE_AUTO_START"],
            [nssm, "start", win_svc],
        )
        try:
            for command in commands:
                subprocess.run(command, check=True, capture_output=True, timeout=60)
        except (OSError, subprocess.CalledProcessError) as exc:
            subprocess.run([nssm, "remove", win_svc, "confirm"], check=False, capture_output=True, timeout=60)
            raise RuntimeError(f"NSSM service creation failed for {win_svc}: {exc}") from exc
        self.printer.success(f"Service {win_svc} created and started (via NSSM)")
        return True

    def start(self, service_name: str) -> bool:
        """Start service"""
        return self._svc_action("start", service_name)

    def stop(self, service_name: str) -> bool:
        """Stop service"""
        return self._svc_action("stop", service_name)

    def restart(self, service_name: str) -> bool:
        """Restart service."""
        return self._svc_action("restart", service_name)

    start_service = start
    stop_service = stop

    def get_status(self, service_name: str) -> str:
        """Get service status via sc query"""
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if "RUNNING" in result.stdout:
                return "active"
            elif "STOPPED" in result.stdout:
                return "inactive"
            return "unknown"
        except Exception:
            return "unknown"

    def view_logs(self, service_name: str):
        """View service logs from Windows Event Log"""
        self.printer.step(f"Querying Windows Event Log for {service_name}...")
        try:
            script = (
                "param([string]$Source) "
                "Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName=$Source} "
                "-MaxEvents 50 | Format-List"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script, service_name],
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.printer.warning("Could not query Event Log. Check Windows Event Viewer manually.")

    def remove_service(self, service_name: str) -> bool:
        """Remove (delete) a Windows service"""
        service_name = self._normalize_service_name(service_name)
        nssm = shutil.which("nssm") or shutil.which("nssm.exe")
        self.stop(service_name)
        try:
            if nssm:
                subprocess.run(
                    [nssm, "remove", service_name, "confirm"],
                    check=True,
                    capture_output=True,
                )
            else:
                subprocess.run(
                    ["sc", "delete", service_name],
                    check=True,
                    capture_output=True,
                )
            self.printer.success(f"Service {service_name} removed")
            return True
        except subprocess.CalledProcessError as e:
            self.printer.error(f"Failed to remove service: {e}")
            return False

    def _svc_action(self, action: str, service_name: str) -> bool:
        """Execute a start/stop action on a Windows service."""
        service_name = self._normalize_service_name(service_name)
        nssm = shutil.which("nssm") or shutil.which("nssm.exe")
        try:
            if nssm:
                subprocess.run([nssm, action, service_name], check=True, capture_output=True, timeout=60)
            else:
                subprocess.run(["sc", action, service_name], check=True, capture_output=True, timeout=60)
            self.printer.success(f"{service_name} {action}ed")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            self.printer.error(f"Failed to {action} {service_name}")
            return False


# Alias so existing code that imports SystemdManager still works
SystemdManager = ServiceManager


# ===== Archive Extraction =====


DEFAULT_MAX_ARCHIVE_FILES = 100_000
DEFAULT_MAX_ARCHIVE_BYTES = 10 * 1024 * 1024 * 1024
_ARCHIVE_COPY_CHUNK_SIZE = 1024 * 1024
_TAR_SUFFIXES = (
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".gz",
    ".bz2",
    ".xz",
)
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')


class UnsafeArchiveError(ValueError):
    """Raised when an archive violates extraction safety rules."""


class ArchiveLimitError(UnsafeArchiveError):
    """Raised when an archive exceeds configured expansion limits."""


@dataclass(frozen=True)
class _ArchiveEntry:
    member: object
    parts: tuple[str, ...]
    is_dir: bool
    size: int
    mode: int = 0


def _validate_windows_component(value: str, *, label: str) -> str:
    """Validate one Windows path component on every host OS."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        raise ValueError(f"Invalid {label}: {value!r}")
    if len(value) > 255 or "\x00" in value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid {label}: {value!r}")
    if value[-1] in {" ", "."}:
        raise ValueError(f"Invalid {label}: {value!r}")
    if any(character in _WINDOWS_INVALID_CHARS or ord(character) < 32 for character in value):
        raise ValueError(f"Invalid {label}: {value!r}")
    if value.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def validate_path_component(value: str, *, label: str = "path component") -> str:
    """Validate an untrusted value used as one Windows directory name."""
    return _validate_windows_component(value, label=label)


def _path_exists(path: Path) -> bool:
    """Return True for existing paths, including broken symbolic links."""
    return os.path.lexists(path)


def make_path_private(path: Path, *, directory: bool) -> None:
    """Apply private permissions and a best-effort Windows ACL."""
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError:
        pass

    if os.name != "nt":
        return
    try:
        username = os.environ.get("USERNAME")
        if not username:
            return
        rights = "(OI)(CI)F" if directory else "F"
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{username}:{rights}",
                "/grant:r",
                f"*S-1-5-18:{rights}",
                "/grant:r",
                f"*S-1-5-32-544:{rights}",
            ],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def install_staged_directory(source: Path, target: Path) -> None:
    """Atomically publish a staged directory without replacing a target."""
    source = Path(source)
    target = Path(target)
    if _path_exists(target):
        raise FileExistsError(f"Installation target already exists: {target}")

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise OSError(errno.ENOTSUP, "Atomic no-replace directory installation is unavailable")

        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) == 0:
            return

        error_number = ctypes.get_errno()
        if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
            raise FileExistsError(f"Installation target already exists: {target}")
        raise OSError(error_number, os.strerror(error_number), target)

    try:
        # Windows MoveFile semantics fail when the destination already exists.
        os.rename(source, target)
    except FileExistsError:
        raise FileExistsError(f"Installation target already exists: {target}") from None
    except OSError as exc:
        if _path_exists(target):
            raise FileExistsError(f"Installation target already exists: {target}") from exc
        raise


def _archive_member_parts(name: str) -> tuple[str, ...]:
    """Return a safe archive path using Windows lexical rules on every OS."""
    if not isinstance(name, str) or "\x00" in name:
        raise UnsafeArchiveError(f"Invalid archive member path: {name!r}")

    normalized = name.replace("\\", "/")
    windows_path = PureWindowsPath(name)
    if (
        normalized.startswith("/")
        or normalized.startswith("//")
        or windows_path.drive
        or windows_path.root
        or windows_path.is_absolute()
    ):
        raise UnsafeArchiveError(f"Absolute or drive-qualified archive member path is not allowed: {name}")

    raw_parts = normalized.split("/")
    if any(part == ".." for part in raw_parts):
        raise UnsafeArchiveError(f"Path traversal attempt detected: {name}")

    parts = tuple(part for part in raw_parts if part not in {"", "."})
    try:
        for part in parts:
            _validate_windows_component(part, label="archive path component")
    except ValueError as exc:
        raise UnsafeArchiveError(f"Invalid archive member path: {name}") from exc
    return parts


def _windows_path_key(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Return a case-insensitive key matching Windows path identity."""
    return tuple(part.casefold() for part in parts)


def _member_destination(root: Path, parts: tuple[str, ...]) -> Path:
    """Build a member destination and verify containment without prefixes."""
    root_resolved = root.resolve()
    destination = root.joinpath(*parts)
    try:
        destination.resolve(strict=False).relative_to(root_resolved)
    except ValueError as exc:
        raise UnsafeArchiveError(f"Archive member escapes extraction directory: {'/'.join(parts)}") from exc
    return destination


def _validate_entry_layout(entries: list[_ArchiveEntry], expected_top_level: str | None) -> None:
    """Reject duplicate, case-colliding, and file/directory-conflicting paths."""
    if not entries:
        raise UnsafeArchiveError("Archive is empty")

    kinds: dict[tuple[str, ...], tuple[str, tuple[str, ...]]] = {}
    for entry in entries:
        if not entry.parts:
            if not entry.is_dir:
                raise UnsafeArchiveError("Archive contains a file with an empty path")
            continue

        key = _windows_path_key(entry.parts)
        if key in kinds:
            raise UnsafeArchiveError(f"Duplicate or case-conflicting archive member path: {'/'.join(entry.parts)}")
        kinds[key] = ("directory" if entry.is_dir else "file", entry.parts)

    if not kinds:
        raise UnsafeArchiveError("Archive is empty")

    for key, (_kind, original_parts) in kinds.items():
        for index in range(1, len(key)):
            parent = kinds.get(key[:index])
            if parent is not None and parent[0] == "file":
                raise UnsafeArchiveError(f"Archive path conflicts with a file: {'/'.join(original_parts)}")

    if expected_top_level is not None:
        expected = validate_path_component(expected_top_level, label="expected top-level directory")
        unexpected = [parts for _kind, parts in kinds.values() if parts[0] != expected]
        if unexpected:
            raise UnsafeArchiveError(
                f"Archive must contain only the top-level directory '{expected}'; found '{unexpected[0][0]}'"
            )


def _validate_limits(entries: list[_ArchiveEntry], max_files: int, max_bytes: int) -> None:
    if max_files <= 0 or max_bytes < 0:
        raise ValueError("Archive limits must be positive")
    if len(entries) > max_files:
        raise ArchiveLimitError(f"Archive contains too many files ({len(entries)} > {max_files})")

    expanded_bytes = sum(entry.size for entry in entries if not entry.is_dir)
    if expanded_bytes > max_bytes:
        raise ArchiveLimitError(f"Archive expands to too many bytes ({expanded_bytes} > {max_bytes})")


def _validated_zip_entries(
    archive: zipfile.ZipFile,
    max_files: int,
    max_bytes: int,
    expected_top_level: str | None,
) -> list[_ArchiveEntry]:
    infos = archive.infolist()
    if len(infos) > max_files:
        raise ArchiveLimitError(f"Archive contains too many files ({len(infos)} > {max_files})")

    entries: list[_ArchiveEntry] = []
    for info in infos:
        parts = _archive_member_parts(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0
        file_type = stat.S_IFMT(mode)
        is_dir = info.is_dir()
        allowed_type = stat.S_IFDIR if is_dir else stat.S_IFREG
        if file_type not in {0, allowed_type}:
            raise UnsafeArchiveError(f"Archive links and special files are not allowed: {info.filename}")
        if info.file_size < 0:
            raise UnsafeArchiveError(f"Invalid archive member size: {info.filename}")
        entries.append(_ArchiveEntry(info, parts, is_dir, 0 if is_dir else info.file_size, mode))

    _validate_limits(entries, max_files, max_bytes)
    _validate_entry_layout(entries, expected_top_level)
    return entries


def _validated_tar_entries(
    archive: tarfile.TarFile,
    max_files: int,
    max_bytes: int,
    expected_top_level: str | None,
) -> list[_ArchiveEntry]:
    entries: list[_ArchiveEntry] = []
    for member in archive:
        if len(entries) >= max_files:
            raise ArchiveLimitError(f"Archive contains too many files (more than {max_files})")
        parts = _archive_member_parts(member.name)
        if member.isdir():
            entries.append(_ArchiveEntry(member, parts, True, 0, member.mode))
        elif member.isreg():
            if member.size < 0:
                raise UnsafeArchiveError(f"Invalid archive member size: {member.name}")
            entries.append(_ArchiveEntry(member, parts, False, member.size, member.mode))
        else:
            raise UnsafeArchiveError(f"Archive links and special files are not allowed: {member.name}")

    _validate_limits(entries, max_files, max_bytes)
    _validate_entry_layout(entries, expected_top_level)
    return entries


def _write_archive_file(source, destination: Path, entry: _ArchiveEntry, total: int, max_bytes: int) -> int:
    member_total = 0
    try:
        with source, destination.open("xb") as output:
            while True:
                remaining_member = entry.size - member_total
                remaining_total = max_bytes - total
                read_size = min(_ARCHIVE_COPY_CHUNK_SIZE, remaining_member + 1, remaining_total + 1)
                chunk = source.read(max(1, read_size))
                if not chunk:
                    break
                member_total += len(chunk)
                total += len(chunk)
                if member_total > entry.size:
                    raise UnsafeArchiveError(f"Archive member exceeds its declared size: {'/'.join(entry.parts)}")
                if total > max_bytes:
                    raise ArchiveLimitError(f"Archive expands to more than {max_bytes} bytes")
                output.write(chunk)
    except FileExistsError as exc:
        raise UnsafeArchiveError(f"Archive member destination already exists: {'/'.join(entry.parts)}") from exc

    if member_total != entry.size:
        raise UnsafeArchiveError(f"Archive member size mismatch: {'/'.join(entry.parts)}")
    return total


def _ensure_safe_directory(path: Path, root: Path) -> None:
    """Create a directory chain while rejecting links and non-directories."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current /= part
        if _path_exists(current):
            if current.is_symlink() or not current.is_dir():
                raise UnsafeArchiveError(f"Unsafe archive directory: {current}")
        else:
            current.mkdir(mode=0o700)


def _extract_validated_entries(
    archive: zipfile.ZipFile | tarfile.TarFile,
    entries: list[_ArchiveEntry],
    target_dir: Path,
    max_bytes: int,
) -> None:
    total = 0
    for entry in entries:
        if not entry.parts:
            continue
        destination = _member_destination(target_dir, entry.parts)
        if entry.is_dir:
            _ensure_safe_directory(destination, target_dir)
            continue

        _ensure_safe_directory(destination.parent, target_dir)
        if isinstance(archive, zipfile.ZipFile):
            if not isinstance(entry.member, zipfile.ZipInfo):
                raise UnsafeArchiveError(f"Invalid ZIP member metadata: {'/'.join(entry.parts)}")
            source = archive.open(entry.member, "r")
        else:
            if not isinstance(entry.member, tarfile.TarInfo):
                raise UnsafeArchiveError(f"Invalid TAR member metadata: {'/'.join(entry.parts)}")
            tar_source = archive.extractfile(entry.member)
            if tar_source is None:
                raise UnsafeArchiveError(f"Cannot read archive member: {'/'.join(entry.parts)}")
            source = tar_source

        total = _write_archive_file(source, destination, entry, total, max_bytes)
        try:
            os.chmod(destination, 0o700 if entry.mode & 0o111 else 0o600)
        except OSError:
            pass


def _safe_extract(
    archive_path: Path,
    target_dir: Path,
    archive_type: str,
    *,
    max_files: int,
    max_bytes: int,
    expected_top_level: str | None,
) -> Path:
    archive_path = Path(archive_path)
    target_dir = Path(target_dir)
    if max_files <= 0 or max_bytes < 0:
        raise ValueError("Archive limits must be positive")
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if _path_exists(target_dir):
        raise FileExistsError(f"Extraction target already exists: {target_dir}")

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.parent.is_symlink():
        raise UnsafeArchiveError(f"Extraction parent must not be a symbolic link: {target_dir.parent}")
    created = False
    try:
        target_dir.mkdir(mode=0o700)
        created = True
        make_path_private(target_dir, directory=True)
        if archive_type == "zip":
            with zipfile.ZipFile(archive_path, "r") as archive:
                entries = _validated_zip_entries(archive, max_files, max_bytes, expected_top_level)
                _extract_validated_entries(archive, entries, target_dir, max_bytes)
        else:
            with tarfile.open(archive_path, "r:*") as archive:
                entries = _validated_tar_entries(archive, max_files, max_bytes, expected_top_level)
                _extract_validated_entries(archive, entries, target_dir, max_bytes)

        if expected_top_level is not None and not (target_dir / expected_top_level).is_dir():
            raise UnsafeArchiveError(f"Archive is missing top-level directory '{expected_top_level}'")
        return target_dir
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Corrupted or invalid ZIP archive: {archive_path.name}") from exc
    except tarfile.TarError as exc:
        raise ValueError(f"Corrupted or invalid TAR archive: {archive_path.name} ({exc})") from exc
    except BaseException:
        if created:
            shutil.rmtree(target_dir, ignore_errors=True)
        raise


def safe_extract_zip(
    archive_path: Path,
    target_dir: Path,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    expected_top_level: str | None = None,
) -> Path:
    """Safely and manually extract a ZIP archive into a new directory."""
    return _safe_extract(
        archive_path,
        target_dir,
        "zip",
        max_files=max_files,
        max_bytes=max_bytes,
        expected_top_level=expected_top_level,
    )


def safe_extract_tar(
    archive_path: Path,
    target_dir: Path,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    expected_top_level: str | None = None,
) -> Path:
    """Safely and manually extract a TAR archive into a new directory."""
    return _safe_extract(
        archive_path,
        target_dir,
        "tar",
        max_files=max_files,
        max_bytes=max_bytes,
        expected_top_level=expected_top_level,
    )


def _parse_7z_listing(output: str, max_files: int, max_bytes: int) -> list[_ArchiveEntry]:
    """Parse a technical 7-Zip listing, rejecting entries of uncertain type."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key == "Path" and "Path" in current:
            blocks.append(current)
            current = {}
        current[key] = value
    if current:
        blocks.append(current)

    entries: list[_ArchiveEntry] = []
    for block in blocks:
        name = block.get("Path")
        if not name:
            continue
        if "Type" in block and "Size" not in block and "Folder" not in block:
            continue
        if block.get("Encrypted", "-") not in {"", "-"}:
            raise UnsafeArchiveError(f"Encrypted RAR members are not supported: {name}")
        for key, value in block.items():
            normalized_key = key.casefold()
            normalized_value = value.casefold()
            if (
                (("link" in normalized_key or normalized_key in {"redir", "target"}) and value not in {"", "-"})
                or "symbolic link" in normalized_value
                or "hard link" in normalized_value
            ):
                raise UnsafeArchiveError(f"RAR links are not allowed: {name}")

        folder = block.get("Folder")
        attributes = block.get("Attributes", "").strip()
        unix_mode = attributes.split()[-1] if attributes else ""
        if unix_mode and len(unix_mode) >= 10 and unix_mode[0] in "lcbps":
            raise UnsafeArchiveError(f"RAR links and special files are not allowed: {name}")
        if folder == "+" or (folder is None and (attributes.startswith("D") or unix_mode.startswith("d"))):
            is_dir = True
        elif folder == "-" or (folder is None and attributes and not attributes.startswith("D")):
            is_dir = False
        else:
            raise UnsafeArchiveError(f"Cannot safely determine RAR member type: {name}")

        try:
            size = 0 if is_dir else int(block["Size"])
        except (KeyError, ValueError) as exc:
            raise UnsafeArchiveError(f"Cannot safely determine RAR member size: {name}") from exc
        if size < 0:
            raise UnsafeArchiveError(f"Invalid archive member size: {name}")
        entries.append(_ArchiveEntry(name, _archive_member_parts(name), is_dir, size))

    _validate_limits(entries, max_files, max_bytes)
    _validate_entry_layout(entries, None)
    return entries


def _parse_unrar_listing(output: str, max_files: int, max_bytes: int) -> list[_ArchiveEntry]:
    """Parse an unrar technical listing, failing closed on unknown metadata."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in output.splitlines():
        match = re.match(r"^\s*(Name|Type|Size|Redir|Target)\s*:\s*(.*)$", raw_line)
        if not match:
            continue
        key, value = match.groups()
        if key == "Name" and "Name" in current:
            blocks.append(current)
            current = {}
        current[key] = value.strip()
    if current:
        blocks.append(current)

    entries: list[_ArchiveEntry] = []
    for block in blocks:
        name = block.get("Name")
        if not name:
            continue
        if block.get("Redir") or block.get("Target"):
            raise UnsafeArchiveError(f"RAR links are not allowed: {name}")
        member_type = block.get("Type", "").casefold()
        if member_type == "directory":
            is_dir = True
        elif member_type == "file":
            is_dir = False
        else:
            raise UnsafeArchiveError(f"Cannot safely determine RAR member type: {name}")
        try:
            size = 0 if is_dir else int(block["Size"])
        except (KeyError, ValueError) as exc:
            raise UnsafeArchiveError(f"Cannot safely determine RAR member size: {name}") from exc
        if size < 0:
            raise UnsafeArchiveError(f"Invalid archive member size: {name}")
        entries.append(_ArchiveEntry(name, _archive_member_parts(name), is_dir, size))

    _validate_limits(entries, max_files, max_bytes)
    _validate_entry_layout(entries, None)
    return entries


def _postvalidate_extracted_tree(target_dir: Path, max_files: int, max_bytes: int) -> None:
    """Reject links, special files, escapes, collisions, and actual limit excess."""
    entries: list[_ArchiveEntry] = []
    root = target_dir.resolve()
    for current_root, dir_names, file_names in os.walk(target_dir, topdown=True, followlinks=False):
        current = Path(current_root)
        for name in [*dir_names, *file_names]:
            path = current / name
            info = path.lstat()
            relative = path.relative_to(target_dir)
            parts = _archive_member_parts(relative.as_posix())
            try:
                path.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise UnsafeArchiveError(f"Extracted archive path escapes staging: {relative}") from exc
            is_reparse_point = bool(
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if stat.S_ISLNK(info.st_mode) or is_reparse_point:
                raise UnsafeArchiveError(f"Extracted archive links are not allowed: {relative}")
            if stat.S_ISDIR(info.st_mode):
                entries.append(_ArchiveEntry(path, parts, True, 0))
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                entries.append(_ArchiveEntry(path, parts, False, info.st_size))
            else:
                raise UnsafeArchiveError(f"Extracted archive special files or hardlinks are not allowed: {relative}")

    _validate_limits(entries, max_files, max_bytes)
    _validate_entry_layout(entries, None)


def safe_extract_rar(
    archive_path: Path,
    target_dir: Path,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    expected_top_level: str | None = None,
) -> Path:
    """List-validate, privately extract, and postvalidate a RAR archive."""
    archive_path = Path(archive_path)
    target_dir = Path(target_dir)
    if max_files <= 0 or max_bytes < 0:
        raise ValueError("Archive limits must be positive")
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if _path_exists(target_dir):
        raise FileExistsError(f"Extraction target already exists: {target_dir}")

    seven_zip = shutil.which("7z") or shutil.which("7zz")
    unrar = shutil.which("unrar")
    if seven_zip:
        listing = subprocess.run(
            [seven_zip, "l", "-slt", "-ba", str(archive_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        entries = _parse_7z_listing(listing.stdout, max_files, max_bytes)
        extract_command = [seven_zip, "x", str(archive_path), f"-o{target_dir}", "-y", "-aoa"]
    elif unrar:
        listing = subprocess.run(
            [unrar, "lt", "-c-", "-idq", str(archive_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
        )
        entries = _parse_unrar_listing(listing.stdout, max_files, max_bytes)
        extract_command = [unrar, "x", "-o-", "-idq", str(archive_path), str(target_dir) + os.sep]
    else:
        raise FileNotFoundError("No safe RAR extractor found. Install 7-Zip or unrar and ensure it is in PATH.")

    if expected_top_level is not None:
        _validate_entry_layout(entries, expected_top_level)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.parent.is_symlink():
        raise UnsafeArchiveError(f"Extraction parent must not be a symbolic link: {target_dir.parent}")
    created = False
    try:
        target_dir.mkdir(mode=0o700)
        created = True
        make_path_private(target_dir, directory=True)
        subprocess.run(extract_command, check=True, capture_output=True, timeout=300)
        _postvalidate_extracted_tree(target_dir, max_files, max_bytes)
        if expected_top_level is not None and not (target_dir / expected_top_level).is_dir():
            raise UnsafeArchiveError(f"Archive is missing top-level directory '{expected_top_level}'")
        return target_dir
    except BaseException:
        if created:
            shutil.rmtree(target_dir, ignore_errors=True)
        raise


def safe_extract_archive(
    archive_path: Path,
    target_dir: Path,
    *,
    max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    expected_top_level: str | None = None,
) -> Path:
    """Safely extract a supported ZIP, TAR, or validated RAR archive."""
    archive_name = Path(archive_path).name.casefold()
    if archive_name.endswith(".zip"):
        extractor = safe_extract_zip
    elif archive_name.endswith(".rar"):
        extractor = safe_extract_rar
    elif archive_name.endswith(_TAR_SUFFIXES):
        extractor = safe_extract_tar
    else:
        raise ValueError(f"Unsupported archive format: {Path(archive_path).suffix}")
    return extractor(
        archive_path,
        target_dir,
        max_files=max_files,
        max_bytes=max_bytes,
        expected_top_level=expected_top_level,
    )


class ArchiveExtractor:
    """Stage and atomically publish safely extracted product archives."""

    def __init__(
        self,
        *,
        max_files: int = DEFAULT_MAX_ARCHIVE_FILES,
        max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    ):
        self.printer = ColorPrinter()
        self.max_files = max_files
        self.max_bytes = max_bytes

    def extract(self, archive_path: Path, target_dir: Path) -> Path:
        """Extract privately, then atomically install without replacement."""
        archive_path = Path(archive_path)
        target_dir = Path(target_dir)
        self.printer.step(f"Extracting {archive_path.name}")

        if not archive_path.is_file():
            raise FileNotFoundError(f"Archive not found: {archive_path}")
        validate_path_component(target_dir.name, label="installation directory name")
        if _path_exists(target_dir):
            raise FileExistsError(f"Extraction target already exists: {target_dir}")

        target_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{target_dir.name}.staging-", dir=target_dir.parent) as temp_dir:
            stage_root = Path(temp_dir)
            make_path_private(stage_root, directory=True)
            payload = stage_root / "payload"
            safe_extract_archive(
                archive_path,
                payload,
                max_files=self.max_files,
                max_bytes=self.max_bytes,
            )
            source_dir = self._find_product_dir(payload, target_dir.name)
            self._set_permissions(source_dir)
            if _path_exists(target_dir):
                raise FileExistsError(f"Extraction target already exists: {target_dir}")
            install_staged_directory(source_dir, target_dir)

        self.printer.success(f"Extracted to {target_dir}")
        return target_dir

    def _extract_zip(self, archive_path: Path, target_path: Path) -> Path:
        """Compatibility wrapper around the shared ZIP extractor."""
        return safe_extract_zip(archive_path, target_path, max_files=self.max_files, max_bytes=self.max_bytes)

    def _extract_tar(self, archive_path: Path, target_path: Path) -> Path:
        """Compatibility wrapper around the shared TAR extractor."""
        return safe_extract_tar(archive_path, target_path, max_files=self.max_files, max_bytes=self.max_bytes)

    def _extract_rar(self, archive_path: Path, target_path: Path) -> Path:
        """Compatibility wrapper around the validated RAR extractor."""
        return safe_extract_rar(archive_path, target_path, max_files=self.max_files, max_bytes=self.max_bytes)

    @staticmethod
    def _set_permissions(target_dir: Path) -> None:
        """Verify staged contents; Windows ACLs are inherited at publish time."""
        _postvalidate_extracted_tree(target_dir, DEFAULT_MAX_ARCHIVE_FILES, DEFAULT_MAX_ARCHIVE_BYTES)

    def _find_product_dir(self, temp_path: Path, product_name: str) -> Path:
        """Find actual product directory within extracted archive"""
        subdirs = [d for d in temp_path.iterdir() if d.is_dir()]

        root_files = [path for path in temp_path.iterdir() if path.is_file()]
        if len(subdirs) == 1 and not root_files:
            return subdirs[0]

        for subdir in subdirs:
            if subdir.name.lower() == product_name.lower():
                return subdir

        package_json = list(temp_path.rglob("package.json"))
        if len(package_json) == 1:
            return package_json[0].parent
        if len(package_json) > 1:
            raise UnsafeArchiveError("Archive contains multiple possible product directories")

        return temp_path


def is_admin() -> bool:
    """Check if the current process is running as Administrator."""
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        from ctypes import windll  # type: ignore[attr-defined]

        return bool(windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
