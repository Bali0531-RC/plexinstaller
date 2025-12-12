#!/bin/bash
# PlexDevelopment Installer Setup Script
# Downloads and installs the Python-based installer from GitHub
# Usage: curl -sSL https://plexdev.live/setup.sh | sudo bash
# Or with beta flag: curl -sSL https://plexdev.live/setup.sh | sudo bash -s -- -b

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
GITHUB_REPO="Bali0531-RC/plexinstaller"
GITHUB_BRANCH="main"
VERSION="Stable"
INSTALL_DIR="/opt/plexinstaller"
BIN_DIR="/usr/local/bin"

# Parse command line arguments
while getopts "b" opt; do
    case $opt in
        b)
            VERSION="Beta"
            GITHUB_BRANCH="beta"  # Use beta branch if it exists
            ;;
        \?)
            echo "Usage: $0 [-b]"
            echo "  -b    Install beta version (default: stable)"
            exit 1
            ;;
    esac
done

# Print functions
print_header() {
    echo -e "\n${BOLD}${PURPLE}#===== $1 =====#${NC}\n"
}

print_success() {
    echo -e "${GREEN}[✓] $1${NC}"
}

print_error() {
    echo -e "${RED}[✗] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[!] $1${NC}"
}

print_step() {
    echo -e "${CYAN}[+] $1${NC}"
}

# Banner
display_banner() {
    clear
    echo -e "${BOLD}${CYAN}"
    echo "  _____  _           _____                 _                                  _   "
    echo " |  __ \| |         |  __ \               | |                                | |  "
    echo " | |__) | | _____  _| |  | | _____   _____| | ___  _ __  _ __ ___   ___ _ __ | |_ "
    echo " |  ___/| |/ _ \ \/ / |  | |/ _ \ \ / / _ \ |/ _ \| '_ \| '_ \` _ \ / _ \ '_ \| __|"
    echo " | |    | |  __/>  <| |__| |  __/\ V /  __/ | (_) | |_) | | | | | |  __/ | | | |_ "
    echo " |_|    |_|\___/_/\_\_____/ \___| \_/ \___|_|\___/| .__/|_| |_| |_|\___|_| |_|\__|"
    echo "                                                  | |                             "
    echo "                                                  |_|                             "
    echo -e "${NC}"
    echo -e "${BOLD}${PURPLE} UNOFFICIAL Installation Script for PlexDevelopment Products${NC}\n"
    echo -e "${CYAN}${VERSION^^} Version - Automated Installation System${NC}\n"
}

display_banner

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

print_success "Running with root privileges"

# Check for required commands
print_step "Checking system requirements..."

MISSING_CMDS=()
for cmd in curl wget git python3; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_CMDS+=($cmd)
    fi
done

if [ ${#MISSING_CMDS[@]} -gt 0 ]; then
    print_warning "Missing required commands: ${MISSING_CMDS[*]}"
    print_step "Installing missing dependencies..."
    
    if command -v apt &> /dev/null; then
        apt update && apt install -y curl wget git python3 python3-pip
    elif command -v dnf &> /dev/null; then
        dnf install -y curl wget git python3 python3-pip
    elif command -v yum &> /dev/null; then
        yum install -y curl wget git python3 python3-pip
    elif command -v pacman &> /dev/null; then
        pacman -S --noconfirm curl wget git python python-pip
    elif command -v zypper &> /dev/null; then
        zypper install -y curl wget git python3 python3-pip
    else
        print_error "Cannot automatically install dependencies. Please install manually: ${MISSING_CMDS[*]}"
        exit 1
    fi
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
print_success "Python $PYTHON_VERSION found"

# Create installation directory
print_step "Creating installation directory..."
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# Download installer files from GitHub
print_header "Downloading Installer Files"

GITHUB_RAW_URL="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}"

FILES_TO_DOWNLOAD=(
    "installer.py"
    "config.py"
    "utils.py"
    "plex_cli.py"
    "telemetry_client.py"
)

print_step "Downloading from GitHub repository: $GITHUB_REPO (branch: $GITHUB_BRANCH)"

for file in "${FILES_TO_DOWNLOAD[@]}"; do
    print_step "Downloading $file..."
    if curl -fsSL "${GITHUB_RAW_URL}/${file}" -o "$INSTALL_DIR/$file"; then
        print_success "Downloaded $file"
    else
        print_error "Failed to download $file"
        print_warning "Trying alternate method..."
        if wget -q "${GITHUB_RAW_URL}/${file}" -O "$INSTALL_DIR/$file"; then
            print_success "Downloaded $file (via wget)"
        else
            print_error "Failed to download $file. Installation cannot continue."
            exit 1
        fi
    fi
done

# Install Python dependencies for telemetry client
print_step "Installing Python dependencies..."
if command -v pip3 &> /dev/null; then
    pip3 install requests --quiet 2>/dev/null || pip3 install requests --break-system-packages --quiet 2>/dev/null || print_warning "Could not install requests module"
else
    print_warning "pip3 not found, telemetry may not work"
fi

# Make Python files executable
print_step "Setting permissions..."
chmod +x "${INSTALL_DIR}/installer.py"
chmod +x "${INSTALL_DIR}/plex_cli.py"
chmod 644 "${INSTALL_DIR}/config.py"
chmod 644 "${INSTALL_DIR}/utils.py"
chmod 644 "${INSTALL_DIR}/telemetry_client.py"

# Create symbolic link for the main installer
print_step "Creating installer command..."
ln -sf "${INSTALL_DIR}/installer.py" "${BIN_DIR}/plexinstaller"
print_success "Created 'plexinstaller' command"

# Install the plex CLI tool
print_header "Installing Plex CLI Management Tool"
print_step "Setting up 'plex' command..."

# Use a symlink so autoupdates to /opt/plexinstaller also update the CLI.
ln -sf "${INSTALL_DIR}/plex_cli.py" "${BIN_DIR}/plex"

print_success "Plex CLI tool installed successfully!"

# Set version environment variable
export PLEX_INSTALLER_VERSION="$VERSION"

# Display installation summary
print_header "Installation Complete!"

echo -e "${GREEN}✓ Installer Version:${NC} $VERSION"
echo -e "${GREEN}✓ Installation Path:${NC} $INSTALL_DIR"
echo -e "${GREEN}✓ Python Version:${NC} $PYTHON_VERSION"
echo ""

print_header "Available Commands"

echo -e "${BOLD}${CYAN}Main Installer:${NC}"
echo -e "  ${GREEN}plexinstaller${NC}       - Run the interactive installer"
echo ""

echo -e "${BOLD}${CYAN}Plex CLI Tool:${NC}"
echo -e "  ${GREEN}plex list${NC}           - List all installed applications"
echo -e "  ${GREEN}plex start <app>${NC}    - Start an application"
echo -e "  ${GREEN}plex stop <app>${NC}     - Stop an application"
echo -e "  ${GREEN}plex restart <app>${NC}  - Restart an application"
echo -e "  ${GREEN}plex logs <app>${NC}     - View application logs"
echo -e "  ${GREEN}plex status <app>${NC}   - Show application status"
echo -e "  ${GREEN}plex config <app>${NC}   - Edit application configuration"
echo ""

echo -e "${BOLD}${CYAN}Examples:${NC}"
echo -e "  ${YELLOW}plex list${NC}"
echo -e "  ${YELLOW}plex start plextickets${NC}"
echo -e "  ${YELLOW}plex logs plexstore${NC}"
echo ""

# Ask if user wants to run installer now
print_step "Setup complete!"
echo ""
read -p "Would you like to run the installer now? (y/n): " run_now

if [ "$run_now" = "y" ] || [ "$run_now" = "Y" ]; then
    print_header "Starting PlexDevelopment Installer"
    echo ""
    exec plexinstaller
else
    echo ""
    print_success "Setup complete! Run 'plexinstaller' when you're ready to install products."
    echo ""
fi
