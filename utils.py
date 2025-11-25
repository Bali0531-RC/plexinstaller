#!/usr/bin/env python3
"""
Utility functions for PlexDevelopment Installer
"""

import os
import sys
import subprocess
import shutil
import tempfile
import zipfile
import tarfile
import socket
import time
from pathlib import Path
from typing import Optional, List, Tuple

class ColorPrinter:
    """Colored output printer"""
    
    # ANSI color codes
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color
    
    def header(self, message: str):
        """Print header"""
        print(f"\n{self.BOLD}{self.PURPLE}#----- {message} -----#{self.NC}\n", file=sys.stderr)
    
    def step(self, message: str):
        """Print step"""
        print(f"{self.BLUE}[+] {self.CYAN}{message}{self.NC}", file=sys.stderr)
    
    def success(self, message: str):
        """Print success"""
        print(f"{self.GREEN}[✓] {message}{self.NC}", file=sys.stderr)
    
    def error(self, message: str):
        """Print error"""
        print(f"{self.RED}[✗] {message}{self.NC}", file=sys.stderr)
    
    def warning(self, message: str):
        """Print warning"""
        print(f"{self.YELLOW}[!] {message}{self.NC}", file=sys.stderr)

class SystemDetector:
    """System detection and package management"""
    
    def __init__(self):
        self.printer = ColorPrinter()
        self.distribution = None
        self.pkg_manager = None
    
    def detect(self):
        """Detect Linux distribution and package manager"""
        self.printer.header("System Detection")
        
        # Read /etc/os-release
        try:
            with open('/etc/os-release') as f:
                for line in f:
                    if line.startswith('ID='):
                        self.distribution = line.split('=')[1].strip().strip('"')
                        break
        except FileNotFoundError:
            self.printer.error("Cannot detect distribution (/etc/os-release not found)")
            sys.exit(1)
        
        self.printer.step(f"Detected distribution: {self.distribution}")
        
        # Detect package manager
        pkg_managers = {
            'apt': ['apt', 'apt-get'],
            'dnf': ['dnf'],
            'yum': ['yum'],
            'pacman': ['pacman'],
            'zypper': ['zypper']
        }
        
        for name, commands in pkg_managers.items():
            if any(shutil.which(cmd) for cmd in commands):
                self.pkg_manager = name
                break
        
        if not self.pkg_manager:
            self.printer.error("Cannot determine package manager")
            sys.exit(1)
        
        self.printer.success(f"Using package manager: {self.pkg_manager}")
    
    def install_dependencies(self):
        """Install system dependencies"""
        from config import Config
        
        self.printer.header("Installing Dependencies")
        
        config = Config()
        packages = config.SYSTEM_PACKAGES.get(self.pkg_manager, [])
        
        if not packages:
            self.printer.warning("No package list for this package manager")
            return
        
        # Update package lists
        self.printer.step("Updating package lists...")
        
        update_cmds = {
            'apt': ['apt', 'update', '-y'],
            'dnf': ['dnf', 'update', '-y'],
            'yum': ['yum', 'update', '-y'],
            'pacman': ['pacman', '-Syu', '--noconfirm'],
            'zypper': ['zypper', 'refresh']
        }
        
        cmd = update_cmds.get(self.pkg_manager)
        if cmd:
            try:
                subprocess.run(['sudo'] + cmd, check=False)
            except Exception as e:
                self.printer.warning(f"Update failed: {e}")
        
        # Install packages
        self.printer.step(f"Installing {len(packages)} packages...")
        
        install_cmds = {
            'apt': ['apt', 'install', '-y'] + packages,
            'dnf': ['dnf', 'install', '-y'] + packages,
            'yum': ['yum', 'install', '-y'] + packages,
            'pacman': ['pacman', '-S', '--noconfirm', '--needed'] + packages,
            'zypper': ['zypper', 'install', '-y'] + packages
        }
        
        cmd = install_cmds.get(self.pkg_manager)
        if cmd:
            try:
                subprocess.run(['sudo'] + cmd, check=True)
                self.printer.success("System dependencies installed")
            except subprocess.CalledProcessError as e:
                self.printer.error(f"Package installation failed: {e}")
        
        # Install Node.js
        self._install_nodejs()
    
    def _install_nodejs(self):
        """Install Node.js 20+"""
        self.printer.step("Installing Node.js 20+...")
        
        if self.pkg_manager in ['apt', 'dnf', 'yum']:
            # Use NodeSource repository
            script_url = {
                'apt': 'https://deb.nodesource.com/setup_20.x',
                'dnf': 'https://rpm.nodesource.com/setup_20.x',
                'yum': 'https://rpm.nodesource.com/setup_20.x'
            }[self.pkg_manager]
            
            try:
                # Download and run setup script
                subprocess.run(
                    f"curl -fsSL {script_url} | sudo -E bash -",
                    shell=True,
                    check=True
                )
                
                # Install nodejs
                install_cmd = {
                    'apt': ['apt', 'install', '-y', 'nodejs'],
                    'dnf': ['dnf', 'install', '-y', 'nodejs'],
                    'yum': ['yum', 'install', '-y', 'nodejs']
                }[self.pkg_manager]
                
                subprocess.run(['sudo'] + install_cmd, check=True)
                self.printer.success("Node.js installed")
            except subprocess.CalledProcessError as e:
                self.printer.error(f"Node.js installation failed: {e}")
        
        elif self.pkg_manager == 'pacman':
            try:
                subprocess.run(
                    ['sudo', 'pacman', '-S', '--noconfirm', '--needed', 'nodejs', 'npm'],
                    check=True
                )
                self.printer.success("Node.js installed")
            except subprocess.CalledProcessError as e:
                self.printer.error(f"Node.js installation failed: {e}")
        
        # Verify installation
        try:
            result = subprocess.run(['node', '-v'], capture_output=True, text=True)
            version = result.stdout.strip()
            self.printer.step(f"Node.js version: {version}")
        except FileNotFoundError:
            self.printer.error("Node.js not found after installation")

class DNSChecker:
    """DNS verification utilities"""
    
    def __init__(self):
        self.printer = ColorPrinter()
    
    def check(self, domain: str) -> bool:
        """Check if domain points to this server"""
        self.printer.step(f"Checking DNS for: {domain}")
        
        # Get server's public IP
        server_ip = self._get_public_ip()
        if not server_ip:
            self.printer.error("Cannot determine server IP")
            return False
        
        self.printer.step(f"Server IP: {server_ip}")
        
        # Resolve domain
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
    
    def _get_public_ip(self) -> Optional[str]:
        """Get server's public IP address"""
        services = [
            'https://ifconfig.me',
            'https://api.ipify.org',
            'https://icanhazip.com'
        ]
        
        for service in services:
            try:
                result = subprocess.run(
                    ['curl', '-s', '-m', '5', service],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except (subprocess.TimeoutExpired, Exception):
                continue
        
        return None

class FirewallManager:
    """Firewall port management"""
    
    def __init__(self):
        self.printer = ColorPrinter()
    
    def open_port(self, port: int, description: str):
        """Open firewall port"""
        self.printer.step(f"Opening port {port} for {description}")
        
        # Check which firewall is in use
        if shutil.which('ufw'):
            self._open_ufw(port, description)
        elif shutil.which('firewall-cmd'):
            self._open_firewalld(port)
        elif shutil.which('iptables'):
            self._open_iptables(port)
        else:
            self.printer.warning("No supported firewall found")
    
    def close_port(self, port: int):
        """Close firewall port that was previously opened."""
        self.printer.step(f"Reverting firewall rule on port {port}")

        if shutil.which('ufw'):
            self._close_ufw(port)
        elif shutil.which('firewall-cmd'):
            self._close_firewalld(port)
        elif shutil.which('iptables'):
            self._close_iptables(port)

    def _open_ufw(self, port: int, description: str):
        """Open port in UFW"""
        try:
            subprocess.run(
                ['sudo', 'ufw', 'allow', f'{port}/tcp', 'comment', description],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} opened in UFW")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to open port in UFW")
    
    def _open_firewalld(self, port: int):
        """Open port in firewalld"""
        try:
            subprocess.run(
                ['sudo', 'firewall-cmd', '--permanent', f'--add-port={port}/tcp'],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['sudo', 'firewall-cmd', '--reload'],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} opened in firewalld")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to open port in firewalld")
    
    def _open_iptables(self, port: int):
        """Open port in iptables"""
        try:
            subprocess.run(
                ['sudo', 'iptables', '-A', 'INPUT', '-p', 'tcp', '--dport', str(port), '-j', 'ACCEPT'],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} opened in iptables")
            self.printer.warning("iptables rule may not persist after reboot")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to open port in iptables")

    def _close_ufw(self, port: int):
        try:
            subprocess.run(
                ['sudo', 'ufw', 'delete', 'allow', f'{port}/tcp'],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} rule removed from UFW")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to remove UFW rule")

    def _close_firewalld(self, port: int):
        try:
            subprocess.run(
                ['sudo', 'firewall-cmd', '--permanent', f'--remove-port={port}/tcp'],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ['sudo', 'firewall-cmd', '--reload'],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} removed from firewalld")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to remove firewalld rule")

    def _close_iptables(self, port: int):
        try:
            subprocess.run(
                ['sudo', 'iptables', '-D', 'INPUT', '-p', 'tcp', '--dport', str(port), '-j', 'ACCEPT'],
                check=True,
                capture_output=True
            )
            self.printer.success(f"Port {port} rule removed from iptables")
        except subprocess.CalledProcessError:
            self.printer.warning("Failed to remove iptables rule")

class NginxManager:
    """Nginx configuration management"""
    
    def __init__(self):
        self.printer = ColorPrinter()
        from config import Config
        self.config = Config()
    
    def setup(self, domain: str, port: int, service_name: str, install_path: Path):
        """Setup nginx reverse proxy"""
        self.printer.step(f"Configuring Nginx for {service_name}")
        
        config_file = self.config.nginx_available / f"{domain}.conf"
        
        # Create nginx config
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
        root {install_path};
        internal;
    }}
}}
"""
        
        # Write config
        config_file.write_text(nginx_config)
        os.chmod(config_file, 0o644)
        
        # Enable site
        enabled_link = self.config.nginx_enabled / f"{domain}.conf"
        if enabled_link.exists():
            enabled_link.unlink()
        enabled_link.symlink_to(config_file)
        
        # Test and reload nginx
        try:
            subprocess.run(['sudo', 'nginx', '-t'], check=True, capture_output=True)
            subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'], check=True)
            self.printer.success("Nginx configured")
        except subprocess.CalledProcessError as e:
            self.printer.error(f"Nginx configuration failed: {e.stderr.decode()}")
            raise

class SSLManager:
    """SSL certificate management"""
    
    def __init__(self):
        self.printer = ColorPrinter()
    
    def setup(self, domain: str, email: str):
        """Setup SSL certificate with certbot"""
        self.printer.step(f"Setting up SSL for {domain}")
        
        try:
            subprocess.run([
                'sudo', 'certbot', '--nginx',
                '-d', domain,
                '--non-interactive',
                '--agree-tos',
                '--email', email,
                '--redirect',
                '--keep-until-expiring'
            ], check=True)
            
            self.printer.success("SSL certificate obtained")
        except subprocess.CalledProcessError as e:
            self.printer.error("SSL setup failed")
            self.printer.error("Check: DNS records, firewall ports 80/443")
            raise
    
    def setup_auto_renewal(self):
        """Setup automatic SSL renewal with cron"""
        self.printer.step("Setting up SSL auto-renewal")
        
        cron_entry = "0 2 * * * /usr/bin/certbot renew --quiet --deploy-hook 'systemctl reload nginx'\n"
        
        try:
            # Get current crontab
            result = subprocess.run(
                ['sudo', 'crontab', '-l'],
                capture_output=True,
                text=True
            )
            current_cron = result.stdout if result.returncode == 0 else ""
            
            # Add renewal entry if not present
            if 'certbot renew' not in current_cron:
                new_cron = current_cron + cron_entry
                subprocess.run(
                    ['sudo', 'crontab', '-'],
                    input=new_cron,
                    text=True,
                    check=True
                )
                self.printer.success("SSL auto-renewal configured")
            else:
                self.printer.step("SSL auto-renewal already configured")
        except subprocess.CalledProcessError as e:
            self.printer.error(f"Failed to setup auto-renewal: {e}")

class SystemdManager:
    """Systemd service management"""
    
    def __init__(self):
        self.printer = ColorPrinter()
    
    def create_service(self, service_name: str, install_path: Path):
        """Create systemd service file"""
        service_file = Path(f"/etc/systemd/system/plex-{service_name}.service")
        
        service_content = f"""[Unit]
Description=PlexDevelopment - {service_name} Service
After=network.target nginx.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory={install_path}
ExecStart=/usr/bin/node .
Restart=on-failure
RestartSec=10
TimeoutStartSec=30s
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=plex-{service_name}

[Install]
WantedBy=multi-user.target
"""
        
        service_file.write_text(service_content)
        os.chmod(service_file, 0o644)
        
        # Reload systemd and enable service
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True, timeout=30)
        subprocess.run(['sudo', 'systemctl', 'enable', f'plex-{service_name}'], check=True, timeout=30)
        subprocess.run(['sudo', 'systemctl', 'start', f'plex-{service_name}'], check=True, timeout=60)
        
        self.printer.success(f"Service plex-{service_name} created and started")
    
    def start(self, service_name: str):
        """Start service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'start', service_name], check=True, timeout=60)
            self.printer.success(f"{service_name} started")
        except subprocess.CalledProcessError:
            self.printer.error(f"Failed to start {service_name}")
    
    def stop(self, service_name: str):
        """Stop service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'stop', service_name], check=True, timeout=60)
            self.printer.success(f"{service_name} stopped")
        except subprocess.CalledProcessError:
            self.printer.error(f"Failed to stop {service_name}")
    
    def restart(self, service_name: str):
        """Restart service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', service_name], check=True, timeout=60)
            self.printer.success(f"{service_name} restarted")
        except subprocess.CalledProcessError:
            self.printer.error(f"Failed to restart {service_name}")
    
    def get_status(self, service_name: str) -> str:
        """Get service status"""
        try:
            result = subprocess.run(
                ['systemctl', 'is-active', service_name],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"
    
    def view_logs(self, service_name: str):
        """View service logs"""
        try:
            subprocess.run(['sudo', 'journalctl', '-u', service_name, '-n', '50', '-f'])
        except KeyboardInterrupt:
            pass
    
    def remove_service(self, service_name: str):
        """Remove systemd service"""
        try:
            subprocess.run(['sudo', 'systemctl', 'stop', service_name], check=False, timeout=60)
            subprocess.run(['sudo', 'systemctl', 'disable', service_name], check=False, timeout=30)
            
            service_file = Path(f"/etc/systemd/system/{service_name}.service")
            # Use try/except instead of check-then-act to avoid race condition
            try:
                service_file.unlink()
            except FileNotFoundError:
                pass
            
            subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True, timeout=30)
            self.printer.success(f"Service {service_name} removed")
        except subprocess.CalledProcessError as e:
            self.printer.error(f"Failed to remove service: {e}")

class ArchiveExtractor:
    """Archive extraction utilities"""
    
    def __init__(self):
        self.printer = ColorPrinter()
    
    def extract(self, archive_path: Path, target_dir: Path) -> Path:
        """Extract archive to target directory"""
        self.printer.step(f"Extracting {archive_path.name}")
        
        # Verify archive exists and is readable
        if not archive_path.exists():
            raise FileNotFoundError(f"Archive not found: {archive_path}")
        
        # Create target directory
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            raise PermissionError(f"Cannot create directory {target_dir}: permission denied")
        
        # Create temporary extraction directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Extract based on file type with improved error handling
            try:
                if archive_path.suffix == '.zip':
                    self._extract_zip(archive_path, temp_path)
                elif archive_path.suffix in ['.tar', '.gz', '.bz2', '.xz']:
                    self._extract_tar(archive_path, temp_path)
                elif archive_path.suffix == '.rar':
                    self._extract_rar(archive_path, temp_path)
                else:
                    raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
            except zipfile.BadZipFile:
                raise ValueError(f"Corrupted or invalid ZIP archive: {archive_path.name}")
            except tarfile.TarError as e:
                raise ValueError(f"Corrupted or invalid TAR archive: {archive_path.name} ({e})")
            except PermissionError:
                raise PermissionError(f"Cannot read archive {archive_path.name}: permission denied")
            
            # Find actual product directory
            source_dir = self._find_product_dir(temp_path, target_dir.name)
            
            # Move contents to target
            for item in source_dir.iterdir():
                dest = target_dir / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(target_dir))
            
            # Set permissions
            subprocess.run(['sudo', 'chown', '-R', 'root:root', str(target_dir)], timeout=60)
            subprocess.run(['sudo', 'find', str(target_dir), '-type', 'd', '-exec', 'chmod', '755', '{}', ';'], timeout=60)
            subprocess.run(['sudo', 'find', str(target_dir), '-type', 'f', '-exec', 'chmod', '644', '{}', ';'], timeout=60)
        
        self.printer.success(f"Extracted to {target_dir}")
        return target_dir
    
    def _extract_zip(self, archive_path: Path, target_path: Path):
        """Extract ZIP file with path traversal protection"""
        with zipfile.ZipFile(archive_path, 'r') as zip_ref:
            for member in zip_ref.namelist():
                # Validate each path before extraction
                member_path = (target_path / member).resolve()
                if not str(member_path).startswith(str(target_path.resolve())):
                    raise ValueError(f"Path traversal attempt detected: {member}")
            zip_ref.extractall(target_path)
    
    def _extract_tar(self, archive_path: Path, target_path: Path):
        """Extract TAR file with path traversal protection"""
        with tarfile.open(archive_path, 'r:*') as tar_ref:
            for member in tar_ref.getmembers():
                # Validate each path before extraction
                member_path = (target_path / member.name).resolve()
                if not str(member_path).startswith(str(target_path.resolve())):
                    raise ValueError(f"Path traversal attempt detected: {member.name}")
            tar_ref.extractall(target_path)
    
    def _extract_rar(self, archive_path: Path, target_path: Path):
        """Extract RAR file with path traversal protection"""
        # Check if unrar is available
        if not shutil.which('unrar'):
            raise FileNotFoundError("unrar command not found. Install it with: apt install unrar")
        
        subprocess.run([
            'unrar', 'x', '-o+', str(archive_path), str(target_path) + '/'
        ], check=True, timeout=300)
        
        # Post-extraction validation: ensure all files are within target
        target_resolved = target_path.resolve()
        for item in target_path.rglob('*'):
            if not str(item.resolve()).startswith(str(target_resolved)):
                # Remove the offending file and raise error
                if item.is_file():
                    item.unlink()
                raise ValueError(f"Path traversal attempt detected in RAR archive: {item}")
    
    def _find_product_dir(self, temp_path: Path, product_name: str) -> Path:
        """Find actual product directory within extracted archive"""
        # Check if there's a single subdirectory
        subdirs = [d for d in temp_path.iterdir() if d.is_dir()]
        
        if len(subdirs) == 1 and not list(temp_path.glob('*.[jt]s')):
            # Single subdirectory and no JS/TS files in root
            return subdirs[0]
        
        # Check for directory matching product name
        for subdir in subdirs:
            if subdir.name.lower() == product_name.lower():
                return subdir
        
        # Check for package.json
        package_json = list(temp_path.rglob('package.json'))
        if package_json:
            return package_json[0].parent
        
        # Default to temp_path itself
        return temp_path
