#!/usr/bin/env python3
"""
Shared utilities for PlexDevelopment Installer and Plex CLI.

Contains update logic, GPG verification, version comparison, and CLI entrypoint
management that were previously duplicated between installer.py and plex_cli.py.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

INSTALLER_DIR = Path("/opt/plexinstaller")
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json"

# Files managed by the auto-update system
MANAGED_FILES = [
    'installer.py', 'config.py', 'utils.py', 'plex_cli.py',
    'telemetry_client.py', 'addon_manager.py', 'shared.py',
]

# Mapping from version.json keys to filenames
UPDATE_FILE_MAP = {
    'installer': 'installer.py',
    'config': 'config.py',
    'utils': 'utils.py',
    'plex_cli': 'plex_cli.py',
    'telemetry_client': 'telemetry_client.py',
    'addon_manager': 'addon_manager.py',
    'shared': 'shared.py',
}


def is_newer_version(remote: str, local: str) -> bool:
    """Compare semantic-ish version strings.

    Returns True if *remote* is strictly newer than *local*.
    """
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


def verify_gpg_signature(
    version_json_bytes: bytes,
    *,
    print_info: Callable[[str], None],
    print_success: Callable[[str], None],
    print_warning: Callable[[str], None],
    print_error: Callable[[str], None],
) -> bool:
    """Download version.json.sig and verify *version_json_bytes* against it.

    The public key (release-key.gpg) is imported automatically from the repo
    if not already in the local keyring.

    Printer callbacks are injected so both the TUI installer and the headless
    CLI can reuse this without depending on a specific printer class.
    """
    SIG_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json.sig"
    KEY_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/release-key.gpg"

    # Download signature
    try:
        print_info("Downloading GPG signature...")
        with urllib.request.urlopen(SIG_URL, timeout=10) as resp:
            sig_bytes = resp.read()
    except Exception:
        print_warning("Could not download version.json.sig — skipping GPG verification")
        return True  # backwards-compatible

    # Import public key (idempotent)
    try:
        with urllib.request.urlopen(KEY_URL, timeout=10) as resp:
            key_bytes = resp.read()
        subprocess.run(
            ['gpg', '--batch', '--yes', '--import'],
            input=key_bytes,
            capture_output=True,
            timeout=15,
        )
    except Exception:
        pass  # key may already be imported

    # Verify
    sig_fd, sig_path = tempfile.mkstemp(suffix='.sig')
    data_fd, data_path = tempfile.mkstemp(suffix='.json')
    try:
        os.write(sig_fd, sig_bytes)
        os.close(sig_fd)
        os.write(data_fd, version_json_bytes)
        os.close(data_fd)

        result = subprocess.run(
            ['gpg', '--verify', sig_path, data_path],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            print_success("GPG signature verified")
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
    finally:
        for p in (sig_path, data_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def ensure_cli_entrypoints() -> None:
    """Ensure ``/usr/local/bin/plex`` and ``/usr/local/bin/plexinstaller`` point
    at the current installer bundle."""
    if os.geteuid() != 0:
        return

    try:
        bin_dir = Path("/usr/local/bin")
        bin_dir.mkdir(parents=True, exist_ok=True)

        _force_symlink(bin_dir / "plexinstaller", INSTALLER_DIR / "installer.py")
        _force_symlink(bin_dir / "plex", INSTALLER_DIR / "plex_cli.py")
    except Exception:
        pass


def _force_symlink(link_path: Path, target: Path) -> None:
    """Force *link_path* to be a symlink pointing at *target*."""
    if not target.exists():
        return
    try:
        if link_path.is_symlink():
            if link_path.resolve() == target.resolve():
                return
            link_path.unlink(missing_ok=True)
        elif link_path.exists():
            link_path.unlink(missing_ok=True)
        link_path.symlink_to(target)
    except TypeError:
        # Python < 3.8 missing_ok fallback
        if link_path.is_symlink() or link_path.exists():
            link_path.unlink()
        link_path.symlink_to(target)


def perform_update(
    version_data: Dict,
    version_json_bytes: bytes,
    *,
    print_info: Callable[[str], None],
    print_success: Callable[[str], None],
    print_warning: Callable[[str], None],
    print_error: Callable[[str], None],
) -> None:
    """Download and install a new installer version with checksum verification.

    On failure the previous files are restored from backup.
    """
    if os.geteuid() != 0:
        print_warning("Auto-update requires root. Re-run the command with sudo.")
        return

    # Verify GPG signature
    if not verify_gpg_signature(
        version_json_bytes,
        print_info=print_info,
        print_success=print_success,
        print_warning=print_warning,
        print_error=print_error,
    ):
        print_error("Update aborted: GPG signature verification failed")
        return

    install_dir = INSTALLER_DIR
    backup_dir = install_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    checksums = version_data.get('checksums', {})
    urls = version_data.get('download_urls', {})

    # Backup current files
    for filename in MANAGED_FILES:
        src = install_dir / filename
        if src.exists():
            shutil.copy2(src, backup_dir / f"{filename}.bak")

    try:
        for key, filename in UPDATE_FILE_MAP.items():
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
                        f"Checksum mismatch for {filename}: "
                        f"expected {expected_hash}, got {actual_hash}"
                    )
                print_success(f"Checksum verified for {filename}")
            else:
                raise ValueError(
                    f"No checksum provided for {filename}. Aborting update for security."
                )

            target.write_bytes(content)
            os.chmod(target, 0o755 if filename.endswith('.py') else 0o644)

        ensure_cli_entrypoints()

        print_success("Update completed successfully. Restarting...")
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        print_error(f"Update failed: {e}")
        print_warning("Restoring backup files...")
        try:
            if backup_dir.exists():
                for filename in MANAGED_FILES:
                    backup = backup_dir / f"{filename}.bak"
                    target = install_dir / filename
                    if backup.exists():
                        shutil.copy2(backup, target)
                print_success("Backup restored successfully")
            else:
                print_warning("No backup directory found; nothing to restore.")
        except Exception:
            print_error("Could not restore backup. Manual intervention may be required.")
