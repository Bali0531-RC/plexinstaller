#!/bin/bash
# Build a .deb package for PlexInstaller
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Read version from version.json
VERSION=$(python3 -c "import json; print(json.load(open('${REPO_ROOT}/version.json'))['version'])")
PACKAGE_NAME="plexinstaller"
INSTALL_DIR="/opt/plexinstaller"

echo "Building ${PACKAGE_NAME} v${VERSION}..."

# Create build directory structure
BUILD_DIR=$(mktemp -d)
PKG_DIR="${BUILD_DIR}/${PACKAGE_NAME}_${VERSION}"
mkdir -p "${PKG_DIR}/DEBIAN"
mkdir -p "${PKG_DIR}${INSTALL_DIR}"

# Copy application files
APP_FILES=(
    installer.py
    config.py
    utils.py
    plex_cli.py
    telemetry_client.py
    addon_manager.py
    shared.py
    health_checker.py
    mongodb_manager.py
    backup_manager.py
    requirements.txt
    version.json
    version.json.sig
    release-key.gpg
)

for file in "${APP_FILES[@]}"; do
    if [ -f "${REPO_ROOT}/${file}" ]; then
        cp "${REPO_ROOT}/${file}" "${PKG_DIR}${INSTALL_DIR}/"
    fi
done

# Generate control file with correct version
sed "s/__VERSION__/${VERSION}/" "${REPO_ROOT}/debian/control" > "${PKG_DIR}/DEBIAN/control"

# Copy maintainer scripts
for script in postinst prerm; do
    if [ -f "${REPO_ROOT}/debian/${script}" ]; then
        cp "${REPO_ROOT}/debian/${script}" "${PKG_DIR}/DEBIAN/"
        chmod 755 "${PKG_DIR}/DEBIAN/${script}"
    fi
done

# Set permissions
chmod 755 "${PKG_DIR}${INSTALL_DIR}/installer.py"
chmod 755 "${PKG_DIR}${INSTALL_DIR}/plex_cli.py"
chmod 644 "${PKG_DIR}${INSTALL_DIR}"/*.txt "${PKG_DIR}${INSTALL_DIR}"/*.json 2>/dev/null || true

# Build the .deb
dpkg-deb --build --root-owner-group "${PKG_DIR}"

# Move to output location
OUTPUT_DIR="${REPO_ROOT}/dist"
mkdir -p "${OUTPUT_DIR}"
mv "${PKG_DIR}.deb" "${OUTPUT_DIR}/${PACKAGE_NAME}_${VERSION}_all.deb"

# Cleanup
rm -rf "${BUILD_DIR}"

echo "Package built: dist/${PACKAGE_NAME}_${VERSION}_all.deb"
