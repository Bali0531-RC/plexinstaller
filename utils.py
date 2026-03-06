#!/usr/bin/env python3
"""
Utility functions for PlexDevelopment Installer — Windows version

All Linux-specific code (systemd, apt, ufw, certbot, chown, etc.) has been
replaced with Windows equivalents (NSSM / sc.exe, winget / choco, netsh,
win-acme, etc.).
"""

import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from colorama import Fore, Style
from colorama import init as colorama_init

# Initialize colorama for cross-platform support
colorama_init(autoreset=False)

logger = logging.getLogger("plexinstaller")


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
                            "winget", "install", "--id", pkg,
                            "--accept-package-agreements", "--accept-source-agreements",
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
                    ip = resp.read().decode().strip()
                    if ip:
                        return ip
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

    def open_port(self, port: int, description: str):
        """Open firewall port"""
        self.printer.step(f"Opening port {port} for {description}")

        rule_name = f"Plex-{description}-{port}"
        try:
            subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "add", "rule",
                    f"name={rule_name}", "dir=in", "action=allow",
                    "protocol=tcp", f"localport={port}",
                ],
                check=True,
                capture_output=True,
            )
            self.printer.success(f"Port {port} opened in Windows Firewall")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to open port in Windows Firewall (run as Administrator)")

    def close_port(self, port: int):
        """Remove firewall rule for port"""
        self.printer.step(f"Reverting firewall rule on port {port}")

        try:
            subprocess.run(
                [
                    "netsh", "advfirewall", "firewall", "delete", "rule",
                    "protocol=tcp", f"localport={port}",
                ],
                check=True,
                capture_output=True,
            )
            self.printer.success(f"Port {port} rule removed from Windows Firewall")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to remove Windows Firewall rule")


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
                self.printer.error(f"Nginx configuration failed: {e}")
                raise
        else:
            self.printer.warning("Nginx not found in PATH — config written but not reloaded")
            self.printer.step("Download nginx for Windows: https://nginx.org/en/docs/windows.html")


# ===== SSL (win-acme / certbot) =====


class SSLManager:
    """SSL certificate management — Windows"""

    def __init__(self):
        self.printer = ColorPrinter()

    def setup(self, domain: str, email: str):
        """Setup SSL certificate using win-acme or certbot"""
        self.printer.step(f"Setting up SSL for {domain}")

        wacs = shutil.which("wacs") or shutil.which("wacs.exe")
        certbot = shutil.which("certbot") or shutil.which("certbot.exe")

        if wacs:
            try:
                subprocess.run(
                    [
                        wacs, "--target", "manual", "--host", domain,
                        "--emailaddress", email, "--accepttos",
                    ],
                    check=True,
                )
                self.printer.success("SSL certificate obtained via win-acme")
            except subprocess.CalledProcessError:
                self.printer.error("SSL setup via win-acme failed")
                raise
        elif certbot:
            try:
                subprocess.run(
                    [
                        certbot, "certonly", "--standalone",
                        "-d", domain,
                        "--non-interactive", "--agree-tos",
                        "--email", email,
                    ],
                    check=True,
                )
                self.printer.success("SSL certificate obtained via certbot")
            except subprocess.CalledProcessError:
                self.printer.error("SSL setup via certbot failed")
                raise
        else:
            self.printer.error("No SSL tool found.")
            self.printer.step("Install win-acme: https://www.win-acme.com/")
            self.printer.step("Or certbot: https://certbot.eff.org/")
            raise FileNotFoundError("No SSL tool available")

    def setup_auto_renewal(self):
        """On Windows, win-acme handles auto-renewal via a scheduled task."""
        self.printer.step("On Windows, win-acme handles auto-renewal via a scheduled task.")
        self.printer.step("If using certbot, create a scheduled task to run 'certbot renew'.")


# ===== Service Management (NSSM / sc.exe) =====


class ServiceManager:
    """Windows service management using NSSM (preferred) or sc.exe"""

    def __init__(self):
        self.printer = ColorPrinter()

    def create_service(self, service_name: str, install_path: Path):
        """Create and start a Windows service for the application."""
        win_svc = f"plex-{service_name}"
        node_exe = shutil.which("node") or "node.exe"
        nssm = shutil.which("nssm")

        if nssm:
            try:
                subprocess.run(
                    [nssm, "install", win_svc, node_exe, "."],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    [nssm, "set", win_svc, "AppDirectory", str(install_path)],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    [nssm, "set", win_svc, "Description", f"PlexDevelopment - {service_name}"],
                    check=True, capture_output=True,
                )
                subprocess.run(
                    [nssm, "set", win_svc, "Start", "SERVICE_AUTO_START"],
                    check=True, capture_output=True,
                )
                subprocess.run([nssm, "start", win_svc], check=True, capture_output=True)
                self.printer.success(f"Service {win_svc} created and started (via NSSM)")
            except subprocess.CalledProcessError as e:
                self.printer.error(f"NSSM service creation failed: {e}")
                self.printer.step("Ensure NSSM is installed and you're running as Administrator")
        else:
            bin_path = f'"{node_exe}" "{install_path}"'
            try:
                subprocess.run(
                    [
                        "sc", "create", win_svc,
                        f"binPath={bin_path}", "start=auto",
                        f"DisplayName=PlexDevelopment - {service_name}",
                    ],
                    check=True, capture_output=True,
                )
                subprocess.run(["sc", "start", win_svc], check=True, capture_output=True)
                self.printer.success(f"Service {win_svc} created and started (via sc.exe)")
                self.printer.warning("sc.exe services have limited features. Install NSSM for better management.")
                self.printer.step("Download NSSM: https://nssm.cc/")
            except subprocess.CalledProcessError as e:
                self.printer.error(f"Service creation failed: {e}")
                self.printer.step("Run as Administrator to create Windows services")

    def start(self, service_name: str):
        """Start service"""
        self._svc_action("start", service_name)

    def stop(self, service_name: str):
        """Stop service"""
        self._svc_action("stop", service_name)

    def restart(self, service_name: str):
        """Restart service (stop + start)"""
        self.stop(service_name)
        import time
        time.sleep(2)
        self.start(service_name)

    def get_status(self, service_name: str) -> str:
        """Get service status via sc query"""
        try:
            result = subprocess.run(
                ["sc", "query", service_name],
                capture_output=True, text=True, timeout=10,
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
            subprocess.run(
                [
                    "powershell", "-Command",
                    f"Get-EventLog -LogName Application -Source '{service_name}' -Newest 50 "
                    f"| Format-List",
                ],
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.printer.warning("Could not query Event Log. Check Windows Event Viewer manually.")

    def remove_service(self, service_name: str):
        """Remove (delete) a Windows service"""
        nssm = shutil.which("nssm")
        try:
            self.stop(service_name)
        except Exception:
            pass
        try:
            if nssm:
                subprocess.run(
                    [nssm, "remove", service_name, "confirm"],
                    check=True, capture_output=True,
                )
            else:
                subprocess.run(
                    ["sc", "delete", service_name],
                    check=True, capture_output=True,
                )
            self.printer.success(f"Service {service_name} removed")
        except subprocess.CalledProcessError as e:
            self.printer.error(f"Failed to remove service: {e}")

    def _svc_action(self, action: str, service_name: str):
        """Execute a start/stop action on a Windows service."""
        nssm = shutil.which("nssm")
        try:
            if nssm:
                subprocess.run([nssm, action, service_name], check=True, capture_output=True, timeout=60)
            else:
                subprocess.run(["sc", action, service_name], check=True, capture_output=True, timeout=60)
            self.printer.success(f"{service_name} {action}ed")
        except subprocess.CalledProcessError:
            self.printer.error(f"Failed to {action} {service_name}")


# Alias so existing code that imports SystemdManager still works
SystemdManager = ServiceManager


# ===== Archive Extraction =====


class ArchiveExtractor:
    """Archive extraction utilities"""

    def __init__(self):
        self.printer = ColorPrinter()

    def extract(self, archive_path: Path, target_dir: Path) -> Path:
        """Extract archive to target directory"""
        self.printer.step(f"Extracting {archive_path.name}")

        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise PermissionError(f"Cannot create directory {target_dir}: permission denied") from exc

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            try:
                if archive_path.suffix == ".zip":
                    self._extract_zip(archive_path, temp_path)
                elif archive_path.suffix in [".tar", ".gz", ".bz2", ".xz"]:
                    self._extract_tar(archive_path, temp_path)
                elif archive_path.suffix == ".rar":
                    self._extract_rar(archive_path, temp_path)
                else:
                    raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
            except zipfile.BadZipFile as exc:
                raise ValueError(f"Corrupted or invalid ZIP archive: {archive_path.name}") from exc
            except tarfile.TarError as exc:
                raise ValueError(f"Corrupted or invalid TAR archive: {archive_path.name} ({exc})") from exc
            except PermissionError as exc:
                raise PermissionError(f"Cannot read archive {archive_path.name}: permission denied") from exc

            source_dir = self._find_product_dir(temp_path, target_dir.name)

            for item in source_dir.iterdir():
                dest = target_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(target_dir))

            # No chown/chmod needed on Windows — files inherit parent ACLs

        self.printer.success(f"Extracted to {target_dir}")
        return target_dir

    def _extract_zip(self, archive_path: Path, target_path: Path):
        """Extract ZIP file with path traversal protection"""
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            for member in zip_ref.namelist():
                member_path = (target_path / member).resolve()
                if not str(member_path).startswith(str(target_path.resolve())):
                    raise ValueError(f"Path traversal attempt detected: {member}")
            zip_ref.extractall(target_path)

    def _extract_tar(self, archive_path: Path, target_path: Path):
        """Extract TAR file with path traversal protection"""
        with tarfile.open(archive_path, "r:*") as tar_ref:
            for member in tar_ref.getmembers():
                member_path = (target_path / member.name).resolve()
                if not str(member_path).startswith(str(target_path.resolve())):
                    raise ValueError(f"Path traversal attempt detected: {member.name}")
            tar_ref.extractall(target_path)

    def _extract_rar(self, archive_path: Path, target_path: Path):
        """Extract RAR file — requires unrar or 7z in PATH"""
        unrar = shutil.which("unrar")
        sevenz = shutil.which("7z")

        if unrar:
            subprocess.run(
                ["unrar", "x", "-o+", str(archive_path), str(target_path) + "\\"],
                check=True, timeout=300,
            )
        elif sevenz:
            subprocess.run(
                ["7z", "x", str(archive_path), f"-o{target_path}", "-y"],
                check=True, timeout=300,
            )
        else:
            raise FileNotFoundError(
                "No RAR extractor found. Install 7-Zip (winget install 7zip.7zip) "
                "or WinRAR and ensure it's in your PATH."
            )

        # Post-extraction validation
        target_resolved = target_path.resolve()
        for item in target_path.rglob("*"):
            if not str(item.resolve()).startswith(str(target_resolved)):
                if item.is_file():
                    item.unlink()
                raise ValueError(f"Path traversal attempt detected in RAR archive: {item}")

    def _find_product_dir(self, temp_path: Path, product_name: str) -> Path:
        """Find actual product directory within extracted archive"""
        subdirs = [d for d in temp_path.iterdir() if d.is_dir()]

        if len(subdirs) == 1 and not list(temp_path.glob("*.[jt]s")):
            return subdirs[0]

        for subdir in subdirs:
            if subdir.name.lower() == product_name.lower():
                return subdir

        package_json = list(temp_path.rglob("package.json"))
        if package_json:
            return package_json[0].parent

        return temp_path


def is_admin() -> bool:
    """Check if the current process is running as Administrator."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
