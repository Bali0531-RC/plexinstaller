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
from pathlib import Path
from typing import Optional, Dict, Tuple
from dataclasses import dataclass

from config import Config, ProductConfig
from utils import (
    ColorPrinter, SystemDetector, DNSChecker, FirewallManager,
    NginxManager, SSLManager, SystemdManager, ArchiveExtractor
)

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

class PlexInstaller:
    """Main installer class"""
    
    def __init__(self, version: str = "stable"):
        self.version = version
        self.config = Config()
        self.printer = ColorPrinter()
        self.system = SystemDetector()
        self.dns_checker = DNSChecker()
        self.firewall = FirewallManager()
        self.nginx = NginxManager()
        self.ssl = SSLManager()
        self.systemd = SystemdManager()
        self.extractor = ArchiveExtractor()
        
    def run(self):
        """Main entry point"""
        os.system('clear' if os.name != 'nt' else 'cls')
        self._display_banner()
        
        # System checks
        if not self._check_root():
            return
        
        self.system.detect()
        self.system.install_dependencies()
        
        # Main menu
        self._show_main_menu()



    def _display_banner(self):
        """Display PlexDevelopment banner"""
        print(f"{ColorPrinter.BOLD}{ColorPrinter.CYAN}", end="")
        print("  _____  _           _____                 _                                  _   ")
        print(" |  __ \\| |         |  __ \\               | |                                | |  ")
        print(" | |__) | | _____  _| |  | | _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ ")
        print(" |  ___/| |/ _ \\ \\/ / |  | |/ _ \\ \\ / / _ \\ |/ _ \\| '_ \\| '_ \\` _ \\ / _ \\ '_ \\| __|")
        print(" | |    | |  __/>  <| |__| |  __/\\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ ")
        print(" |_|    |_|\\___/_/\\_\\_____/ \\___| \\_/ \\___|_|\\___/| .__/|_| |_| |_|\\___|_| |_|\\__|")
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
    
    def _show_main_menu(self):
        """Display main menu and handle user choice"""
        while True:
            os.system('clear' if os.name != 'nt' else 'cls')
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
        try:
            # Check for multi-instance
            instance_name = self._handle_multi_instance(product)
            
            # Find archive
            archive_path = self._find_archive(product)
            if not archive_path:
                return
            
            # Extract product
            install_path = self._extract_product(archive_path, instance_name)
            if not install_path:
                return
            
            # Install NPM dependencies
            if not self._install_npm_dependencies(install_path):
                return
            
            # Create 502 error page
            self._create_502_page(install_path, product)
            
            # MongoDB setup
            mongo_creds = self._setup_mongodb(instance_name, install_path)
            
            # Web setup (domain, SSL, nginx)
            domain = None
            port = default_port
            if needs_web:
                domain, port = self._setup_web(instance_name, default_port, install_path)
            
            # Dashboard setup for PlexTickets
            if has_dashboard:
                self._install_dashboard(install_path)
            
            # Systemd service
            self._setup_systemd(instance_name, install_path)
            
            # Post-installation
            self._post_install(instance_name, install_path, domain, needs_web)
            
            self.printer.success(f"{product} installed successfully!")
            
        except KeyboardInterrupt:
            self.printer.warning("\nInstallation cancelled by user")
        except Exception as e:
            self.printer.error(f"Installation failed: {e}")
            raise
    
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
        for search_dir in search_dirs:
            if search_dir.exists():
                # Look for product-specific archives
                for pattern in [f"*{product}*.zip", f"*{product}*.rar"]:
                    archives.extend(search_dir.rglob(pattern))
        
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
                ["npm", "install", "--unsafe-perm", "--loglevel=error"],
                cwd=install_path,
                check=True,
                capture_output=True
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
        
        # MongoDB installation and setup would go here
        # This is a placeholder - implement based on your needs
        self.printer.warning("MongoDB setup not yet implemented in Python version")
        return None
    
    def _setup_web(self, instance_name: str, default_port: int, install_path: Path) -> Tuple[str, int]:
        """Setup web server (nginx, SSL)"""
        # Get port
        port_input = input(f"Enter port (default: {default_port}): ").strip()
        port = int(port_input) if port_input else default_port
        
        # Get domain
        domain = input(f"Enter domain (e.g., {instance_name}.example.com): ").strip()
        if not domain:
            raise ValueError("Domain cannot be empty")
        
        # Get email for SSL
        email = input("Enter email for SSL certificates: ").strip()
        if not email:
            raise ValueError("Email cannot be empty")
        
        # Open firewall port
        self.firewall.open_port(port, instance_name)
        
        # Check DNS
        if not self.dns_checker.check(domain):
            proceed = input("DNS check failed. Proceed anyway? (y/n): ").strip().lower()
            if proceed != 'y':
                raise ValueError("Installation aborted due to DNS issues")
        
        # Setup nginx
        self.nginx.setup(domain, port, instance_name, install_path)
        
        # Setup SSL
        self.ssl.setup(domain, email)
        
        return domain, port
    
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
            self.printer.info("ℹ MongoDB not installed or not using systemd")
        
        # Check SSL certificates
        print("\n=== SSL Certificates ===")
        certbot_installed = subprocess.run(['which', 'certbot'], 
                                          capture_output=True).returncode == 0
        if certbot_installed:
            try:
                result = subprocess.run(['certbot', 'certificates'], 
                                      capture_output=True, text=True)
                if 'No certificates found' in result.stdout:
                    self.printer.info("ℹ No SSL certificates found")
                else:
                    # Count certificates
                    cert_count = result.stdout.count('Certificate Name:')
                    self.printer.success(f"✓ Found {cert_count} SSL certificate(s)")
            except:
                self.printer.warning("⚠ Could not check SSL certificates")
        else:
            self.printer.info("ℹ Certbot not installed")
        
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
