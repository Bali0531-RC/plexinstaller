#!/usr/bin/env python3
"""
Plex CLI Management Tool
Command-line interface for managing PlexDevelopment applications
"""

import sys
import subprocess
import os
from pathlib import Path
from typing import List, Dict, Optional

# Configuration
INSTALL_DIR = Path("/var/www/plex")

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
    print()
    print(f"{YELLOW}Examples:{NC}")
    print("  plex list")
    print("  plex start plextickets")
    print("  plex restart plexstore")
    print("  plex logs plextickets")
    print("  plex config plexstore")

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

def is_valid_app(app: str) -> bool:
    """Check if app is a valid installed application"""
    return app in get_installed_apps()

def get_service_name(app: str) -> str:
    """Get systemd service name for app"""
    return f"plex-{app}"

def get_service_status(service_name: str) -> Dict[str, str]:
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
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Starting {app}...")
    
    try:
        subprocess.run(['systemctl', 'start', service_name], check=True)
        print_success(f"{app} started successfully")
        
        # Wait a moment and check if it's actually running
        import time
        time.sleep(2)
        
        status_info = get_service_status(service_name)
        if status_info['active']:
            print_success(f"{app} is now running")
        else:
            print_error(f"{app} failed to start properly")
            print(f"Check logs with: plex logs {app}")
            return 1
        
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to start {app}")
        return 1

def stop_app(app: str):
    """Stop an application"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Stopping {app}...")
    
    try:
        subprocess.run(['systemctl', 'stop', service_name], check=True)
        print_success(f"{app} stopped successfully")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to stop {app}")
        return 1

def restart_app(app: str):
    """Restart an application"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Restarting {app}...")
    
    try:
        subprocess.run(['systemctl', 'restart', service_name], check=True)
        print_success(f"{app} restarted successfully")
        
        # Wait a moment and check if it's running
        import time
        time.sleep(2)
        
        status_info = get_service_status(service_name)
        if status_info['active']:
            print_success(f"{app} is now running")
        else:
            print_error(f"{app} failed to start after restart")
            print(f"Check logs with: plex logs {app}")
            return 1
        
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to restart {app}")
        return 1

def show_status(app: str):
    """Show detailed status of an application"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print(f"{BOLD}{CYAN}Status for {app}:{NC}")
    print()
    
    try:
        subprocess.run(['systemctl', 'status', service_name, '--no-pager', '-l'])
        return 0
    except subprocess.CalledProcessError:
        return 1

def view_logs(app: str):
    """View application logs"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Showing logs for {app} (Press Ctrl+C to exit)...")
    print()
    
    try:
        subprocess.run(['journalctl', '-u', service_name, '-f', '--no-pager'])
        return 0
    except KeyboardInterrupt:
        print()
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to view logs for {app}")
        return 1

def edit_config(app: str):
    """Edit application configuration"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    app_dir = INSTALL_DIR / app
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
        print(f"  {GREEN}plex restart {app}{NC}")
        return 0
    except subprocess.CalledProcessError:
        print_error("Failed to open editor")
        return 1

def enable_app(app: str):
    """Enable application to start on boot"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Enabling {app} to start on boot...")
    
    try:
        subprocess.run(['systemctl', 'enable', service_name], check=True)
        print_success(f"{app} will now start automatically on boot")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to enable {app}")
        return 1

def disable_app(app: str):
    """Disable application from starting on boot"""
    if not is_valid_app(app):
        print_error(f"Application '{app}' not found. Use 'plex list' to see installed apps.")
        return 1
    
    service_name = get_service_name(app)
    print_info(f"Disabling {app} from starting on boot...")
    
    try:
        subprocess.run(['systemctl', 'disable', service_name], check=True)
        print_success(f"{app} will no longer start automatically on boot")
        return 0
    except subprocess.CalledProcessError:
        print_error(f"Failed to disable {app}")
        return 1

def main():
    """Main entry point"""
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
