#!/bin/bash
# PlexDevelopment Installer Setup Script
# Downloads and installs the Python-based installer from GitHub
# Usage: curl -sSL https://plexdev.xyz/setup.sh | sudo bash
# Explicit insecure beta: curl -sSL https://plexdev.xyz/setup.sh | sudo bash -s -- --insecure-beta

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
PINNED_RELEASE_FINGERPRINT="431E869D5BB519AFF7B028379B0DFA4BF86307BD"
ALLOW_INSECURE_BETA=false

# Parse command line arguments
while [ "$#" -gt 0 ]; do
    case "$1" in
        --insecure-beta)
            VERSION="Beta"
            GITHUB_BRANCH="dev"
            ALLOW_INSECURE_BETA=true
            ;;
        -b)
            echo "The ambiguous -b option is no longer accepted."
            echo "Use --insecure-beta to explicitly acknowledge that beta is not signature-enforced."
            exit 1
            ;;
        *)
            echo "Usage: $0 [--insecure-beta]"
            echo "  --insecure-beta  Install dev branch and explicitly permit failed beta verification"
            exit 1
            ;;
    esac
    shift
done

# Prompt helper that works when the script is piped into bash (curl | sudo bash).
# In that case stdin is the script itself, so we read from /dev/tty instead.
# Falls back to a safe default answer when no terminal is available.
prompt_user() {
    local prompt_text="$1" __var_name="$2" default_answer="${3:-n}"
    local answer=""
    if [ -t 0 ]; then
        read -rp "$prompt_text" answer || answer="$default_answer"
    elif [ -r /dev/tty ]; then
        read -rp "$prompt_text" answer < /dev/tty || answer="$default_answer"
    else
        echo "${prompt_text}(non-interactive, defaulting to '${default_answer}')"
        answer="$default_answer"
    fi
    printf -v "$__var_name" '%s' "$answer"
}

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
    clear 2>/dev/null || true
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

if [ "$ALLOW_INSECURE_BETA" = true ]; then
    print_warning "INSECURE BETA MODE: signature or checksum verification failures may be bypassed."
fi

# Check for required commands
print_step "Checking system requirements..."

MISSING_CMDS=()
for cmd in curl python3 gpg sha256sum; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_CMDS+=($cmd)
    fi
done

if [ ${#MISSING_CMDS[@]} -gt 0 ]; then
    print_warning "Missing required commands: ${MISSING_CMDS[*]}"
    print_step "Installing missing dependencies..."
    
    if command -v apt &> /dev/null; then
        apt update && apt install -y curl python3 python3-venv python3-pip gnupg coreutils
    elif command -v dnf &> /dev/null; then
        dnf install -y curl python3 python3-pip gnupg2 coreutils
    elif command -v yum &> /dev/null; then
        yum install -y curl python3 python3-pip gnupg2 coreutils
    elif command -v pacman &> /dev/null; then
        pacman -S --noconfirm curl python python-pip gnupg coreutils
    elif command -v zypper &> /dev/null; then
        zypper install -y curl python3 python3-pip gpg2 coreutils
    else
        print_error "Cannot automatically install dependencies. Please install manually: ${MISSING_CMDS[*]}"
        exit 1
    fi
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
print_success "Python $PYTHON_VERSION found"

# Importing venv is not enough on Debian-family systems: the module can exist
# while ensurepip is split into python<major.minor>-venv. Probe by creating an
# actual disposable environment, then install the missing distro package.
venv_available() {
    local probe_dir
    probe_dir=$(mktemp -d)
    if python3 -m venv "$probe_dir/venv" >/dev/null 2>&1 \
        && [ -x "$probe_dir/venv/bin/python" ] \
        && "$probe_dir/venv/bin/python" -m pip --version >/dev/null 2>&1; then
        rm -rf "$probe_dir"
        return 0
    fi
    rm -rf "$probe_dir"
    return 1
}

install_venv_support() {
    local python_series
    python_series=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

    print_warning "Python $python_series cannot create a pip-enabled virtual environment."
    print_step "Installing Python virtual environment support..."

    if command -v apt-get &> /dev/null; then
        apt-get update
        if ! apt-get install -y "python${python_series}-venv"; then
            print_warning "python${python_series}-venv was unavailable; trying python3-venv..."
            apt-get install -y python3-venv
        fi
    elif command -v dnf &> /dev/null; then
        dnf install -y python3-pip python3-virtualenv
    elif command -v yum &> /dev/null; then
        yum install -y python3-pip python3-virtualenv
    elif command -v pacman &> /dev/null; then
        pacman -S --noconfirm --needed python python-pip
    elif command -v zypper &> /dev/null; then
        zypper install -y python3-pip python3-virtualenv
    else
        print_error "Cannot automatically install virtual environment support."
        return 1
    fi
}

if ! venv_available; then
    install_venv_support || exit 1
    if ! venv_available; then
        PYTHON_SERIES=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        print_error "Python virtual environment support is still unavailable."
        print_error "Install python${PYTHON_SERIES}-venv (or python3-venv) and re-run setup."
        exit 1
    fi
fi
print_success "Python virtual environment support is ready"

# Stage the complete bundle outside the live installation directory.
print_step "Creating secure staging directory..."
STAGING_DIR=$(mktemp -d "${INSTALL_DIR}.staging.XXXXXX")
BACKUP_DIR=""
cleanup() {
    if [ -n "$STAGING_DIR" ]; then
        rm -rf "$STAGING_DIR"
    fi
}
trap cleanup EXIT
chmod 700 "$STAGING_DIR"

# Download installer files from GitHub
print_header "Downloading Installer Files"

GITHUB_RAW_URL="https://raw.githubusercontent.com/${GITHUB_REPO}/${GITHUB_BRANCH}"

FILES_TO_DOWNLOAD=(
    "installer.py"
    "config.py"
    "utils.py"
    "plex_cli.py"
    "telemetry_client.py"
    "addon_manager.py"
    "shared.py"
    "health_checker.py"
    "mongodb_manager.py"
    "backup_manager.py"
    "requirements.txt"
    "version.json"
    "version.json.sig"
    "release-key.gpg"
)

print_step "Downloading from GitHub repository: $GITHUB_REPO (branch: $GITHUB_BRANCH)"

for file in "${FILES_TO_DOWNLOAD[@]}"; do
    print_step "Downloading $file..."
    if curl --proto '=https' --tlsv1.2 --max-filesize 16777216 -fsSL \
        "${GITHUB_RAW_URL}/${file}" -o "$STAGING_DIR/$file"; then
        print_success "Downloaded $file"
    else
        print_error "Failed to download $file"
        print_error "Installation cannot continue."
        exit 1
    fi
done

# Verify GPG signature of version.json
print_header "Verifying GPG Signature"

GPG_VERIFIED=false
GPG_HOME=$(mktemp -d)
chmod 700 "$GPG_HOME"

fingerprint=$(gpg --batch --no-options --with-colons --show-keys --fingerprint "$STAGING_DIR/release-key.gpg" 2>/dev/null \
    | awk -F: '$1 == "pub" { want_fpr=1; next } $1 == "fpr" && want_fpr { print toupper($10); exit }')

if [ "$fingerprint" != "$PINNED_RELEASE_FINGERPRINT" ]; then
    print_error "Release key fingerprint mismatch (found: ${fingerprint:-none})"
elif ! gpg --batch --no-options --homedir "$GPG_HOME" --import-options import-clean \
    --import "$STAGING_DIR/release-key.gpg" >/dev/null 2>&1; then
    print_error "Could not import the pinned release key into the isolated keyring"
else
    VERIFY_STATUS="$STAGING_DIR/gpg-status"
    if gpg --batch --no-options --homedir "$GPG_HOME" --status-fd 1 --no-auto-key-retrieve \
        --verify "$STAGING_DIR/version.json.sig" "$STAGING_DIR/version.json" >"$VERIFY_STATUS" 2>/dev/null \
        && awk -v expected="$PINNED_RELEASE_FINGERPRINT" '$2 == "VALIDSIG" && ($3 == expected || $NF == expected) { found=1 } END { exit !found }' "$VERIFY_STATUS"; then
        print_success "GPG signature and pinned release key verified"
        GPG_VERIFIED=true
    else
        print_error "version.json signature verification failed"
    fi
fi
rm -rf "$GPG_HOME"

if [ "$GPG_VERIFIED" != true ] && [ "$ALLOW_INSECURE_BETA" != true ]; then
    print_error "Stable installation requires valid signature and exact pinned key fingerprint."
    exit 1
fi
if [ "$GPG_VERIFIED" != true ]; then
    print_warning "Explicit insecure beta mode is bypassing failed signature verification."
fi

# Verify SHA256 checksums from version.json
print_header "Verifying File Checksums"

# Helper: read a JSON checksum value (prefer jq, fall back to python3)
read_checksum() {
    local key="$1" file="$2"
    if command -v jq &> /dev/null; then
        jq -r ".checksums.${key} // empty" "$file" 2>/dev/null || true
    elif command -v python3 &> /dev/null; then
        python3 -c "import json,sys; d=json.load(open('$file')); print(d.get('checksums',{}).get('$key',''))" 2>/dev/null || true
    else
        echo ""
    fi
}

if [ -f "$STAGING_DIR/version.json" ]; then
    CHECKSUM_FAILED=false
    for key in installer config utils plex_cli telemetry_client addon_manager shared health_checker mongodb_manager backup_manager requirements; do
        expected=$(read_checksum "$key" "$STAGING_DIR/version.json")
        if [ -z "$expected" ]; then
            print_error "Missing checksum for $key"
            CHECKSUM_FAILED=true
            continue
        fi

        # Map JSON key to filename
        case "$key" in
            installer)        fname="installer.py" ;;
            config)           fname="config.py" ;;
            utils)            fname="utils.py" ;;
            plex_cli)         fname="plex_cli.py" ;;
            telemetry_client) fname="telemetry_client.py" ;;
            addon_manager)    fname="addon_manager.py" ;;
            shared)           fname="shared.py" ;;
            health_checker)   fname="health_checker.py" ;;
            mongodb_manager)  fname="mongodb_manager.py" ;;
            backup_manager)   fname="backup_manager.py" ;;
            requirements)     fname="requirements.txt" ;;
            *)                continue ;;
        esac

        filepath="$STAGING_DIR/$fname"
        if [ ! -f "$filepath" ]; then
            print_error "File not found for checksum: $fname"
            CHECKSUM_FAILED=true
            continue
        fi

        actual=$(sha256sum "$filepath" | awk '{print $1}')
        if [ "$actual" = "$expected" ]; then
            print_success "Checksum OK: $fname"
        else
            print_error "Checksum mismatch: $fname"
            CHECKSUM_FAILED=true
        fi
    done

    if [ "$CHECKSUM_FAILED" = true ]; then
        echo ""
        if [ "$ALLOW_INSECURE_BETA" != true ]; then
            print_error "Stable installation aborted because checksums did not verify."
            exit 1
        fi
        print_warning "Explicit insecure beta mode is bypassing checksum failures."
    fi
else
    print_error "version.json not found"
    exit 1
fi

# Rewrite download URLs for dev branch AFTER integrity checks
if [ "$GITHUB_BRANCH" = "dev" ] && [ -f "$STAGING_DIR/version.json" ]; then
    print_step "Patching version.json download URLs for dev branch..."
    sed -i 's|/plexinstaller/main/|/plexinstaller/dev/|g' "$STAGING_DIR/version.json"
    print_success "Download URLs updated to use dev branch"
fi

# Install Python dependencies
print_step "Installing Python dependencies..."
if [ -f "${STAGING_DIR}/requirements.txt" ]; then
    rm -rf "${STAGING_DIR}/.venv"
    if ! python3 -m venv "${STAGING_DIR}/.venv"; then
        print_error "Failed to create isolated Python virtual environment"
        exit 1
    fi
    if ! "${STAGING_DIR}/.venv/bin/python" -m pip install -r "${STAGING_DIR}/requirements.txt" --quiet; then
        print_error "Failed to install Python dependencies from requirements.txt"
        exit 1
    fi
else
    print_error "requirements.txt not found"
    exit 1
fi

# Make Python files executable
print_step "Setting permissions..."
chmod 755 "${STAGING_DIR}/installer.py" "${STAGING_DIR}/plex_cli.py"
chmod 644 "${STAGING_DIR}/config.py" "${STAGING_DIR}/utils.py" "${STAGING_DIR}/telemetry_client.py"
chmod 644 "${STAGING_DIR}/addon_manager.py" "${STAGING_DIR}/shared.py" "${STAGING_DIR}/health_checker.py"
chmod 644 "${STAGING_DIR}/mongodb_manager.py" "${STAGING_DIR}/backup_manager.py"
chmod 644 "${STAGING_DIR}/version.json" "${STAGING_DIR}/version.json.sig" "${STAGING_DIR}/release-key.gpg"

# Atomically switch the complete verified bundle into place, preserving the old
# bundle for immediate rollback until wrappers are successfully installed.
print_step "Activating verified installer bundle..."
if [ -e "$INSTALL_DIR" ]; then
    BACKUP_DIR="${INSTALL_DIR}.backup.$(date +%s)"
    mv "$INSTALL_DIR" "$BACKUP_DIR"
fi
if ! mv "$STAGING_DIR" "$INSTALL_DIR"; then
    print_error "Could not activate the staged installer bundle"
    if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
        mv "$BACKUP_DIR" "$INSTALL_DIR"
    fi
    exit 1
fi
STAGING_DIR=""

rollback_activation() {
    if [ -n "$BACKUP_DIR" ] && [ -e "$BACKUP_DIR" ]; then
        rm -rf "$INSTALL_DIR"
        mv "$BACKUP_DIR" "$INSTALL_DIR"
    fi
}
trap 'rollback_activation; cleanup' ERR

# Create venv-backed command wrappers.
print_step "Creating installer command..."
mkdir -p "$BIN_DIR"
cat >"${BIN_DIR}/plexinstaller.tmp" <<EOF
#!/bin/sh
python="${INSTALL_DIR}/.venv/bin/python"
if [ ! -x "\$python" ]; then python="\${PYTHON:-python3}"; fi
exec "\$python" "${INSTALL_DIR}/installer.py" "\$@"
EOF
chmod 755 "${BIN_DIR}/plexinstaller.tmp"
mv -f "${BIN_DIR}/plexinstaller.tmp" "${BIN_DIR}/plexinstaller"
print_success "Created 'plexinstaller' command"

# Install the plex CLI tool
print_header "Installing Plex CLI Management Tool"
print_step "Setting up 'plex' command..."

cat >"${BIN_DIR}/plex.tmp" <<EOF
#!/bin/sh
python="${INSTALL_DIR}/.venv/bin/python"
if [ ! -x "\$python" ]; then python="\${PYTHON:-python3}"; fi
exec "\$python" "${INSTALL_DIR}/plex_cli.py" "\$@"
EOF
chmod 755 "${BIN_DIR}/plex.tmp"
mv -f "${BIN_DIR}/plex.tmp" "${BIN_DIR}/plex"

if [ -n "$BACKUP_DIR" ]; then
    rm -rf "$BACKUP_DIR"
    BACKUP_DIR=""
fi
trap cleanup EXIT

print_success "Plex CLI tool installed successfully!"

# Set version environment variable
export PLEX_INSTALLER_VERSION="$VERSION"

# Display installation summary
print_header "Installation Complete!"

echo -e "${GREEN}✓ Installer Version:${NC} $VERSION"
echo -e "${GREEN}✓ Installation Path:${NC} $INSTALL_DIR"
echo -e "${GREEN}✓ Python Version:${NC} $PYTHON_VERSION"
if [ "$GPG_VERIFIED" = true ]; then
    echo -e "${GREEN}✓ GPG Signature:${NC} Verified"
else
    echo -e "${YELLOW}○ GPG Signature:${NC} Not verified"
fi
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
echo -e "  ${YELLOW}plex logs drakostore${NC}"
echo ""

# Ask if user wants to run installer now
print_step "Setup complete!"
echo ""
prompt_user "Would you like to run the installer now? (y/n): " run_now "n"

if [ "$run_now" = "y" ] || [ "$run_now" = "Y" ]; then
    print_header "Starting PlexDevelopment Installer"
    echo ""
    exec plexinstaller
else
    echo ""
    print_success "Setup complete! Run 'plexinstaller' when you're ready to install products."
    echo ""
fi
