#!/usr/bin/env python3
"""
Shared utilities for PlexDevelopment Installer and Plex CLI.

Contains update logic, GPG verification, version comparison, and CLI entrypoint
management that were previously duplicated between installer.py and plex_cli.py.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

INSTALLER_DIR = Path("/opt/plexinstaller")
VERSION_CHECK_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json"
VERSION_SIGNATURE_URL = "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/version.json.sig"
RELEASE_KEY_FINGERPRINT = "431E869D5BB519AFF7B028379B0DFA4BF86307BD"

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 1024 * 1024
MAX_UPDATE_FILE_BYTES = 16 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")

# Files managed by the auto-update system
MANAGED_FILES = [
    "installer.py",
    "config.py",
    "utils.py",
    "plex_cli.py",
    "telemetry_client.py",
    "addon_manager.py",
    "shared.py",
    "health_checker.py",
    "mongodb_manager.py",
    "backup_manager.py",
]

# Mapping from version.json keys to filenames
UPDATE_FILE_MAP = {
    "installer": "installer.py",
    "config": "config.py",
    "utils": "utils.py",
    "plex_cli": "plex_cli.py",
    "telemetry_client": "telemetry_client.py",
    "addon_manager": "addon_manager.py",
    "shared": "shared.py",
    "health_checker": "health_checker.py",
    "mongodb_manager": "mongodb_manager.py",
    "backup_manager": "backup_manager.py",
}


def _validate_download_url(url: str, *, allow_insecure_urls: bool = False) -> str:
    """Reject unsafe update URLs; HTTP requires an explicit test-only opt-in."""
    if not isinstance(url, str) or not url:
        raise ValueError("Download URL must be a non-empty string")
    parsed = urlsplit(url)
    allowed_schemes = {"https", "http"} if allow_insecure_urls else {"https"}
    if parsed.scheme.lower() not in allowed_schemes:
        raise ValueError(f"Unsafe download URL scheme for {url!r}")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError(f"Unsafe download URL for {url!r}")
    return url


def _download_bytes(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
    allow_insecure_urls: bool = False,
) -> bytes:
    """Download a bounded response while rejecting insecure redirects."""
    _validate_download_url(url, allow_insecure_urls=allow_insecure_urls)
    with urllib.request.urlopen(url, timeout=timeout) as response:
        final_url = response.geturl() if hasattr(response, "geturl") else None
        if isinstance(final_url, str):
            _validate_download_url(final_url, allow_insecure_urls=allow_insecure_urls)
        content = bytes(response.read(max_bytes + 1))
    if len(content) > max_bytes:
        raise ValueError(f"Download exceeds the {max_bytes}-byte size limit")
    return content


def _parse_manifest(version_json_bytes: bytes) -> dict:
    """Parse an authenticated manifest as a JSON object."""
    try:
        data = json.loads(version_json_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid version manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Version manifest must be a JSON object")
    return data


def _validated_download_specs(
    version_data: dict,
    files: dict[str, str],
    *,
    allow_insecure_urls: bool = False,
) -> dict[str, tuple[str, str]]:
    """Return validated URL/checksum pairs for every requested file."""
    urls = version_data.get("download_urls")
    checksums = version_data.get("checksums")
    if not isinstance(urls, dict) or not isinstance(checksums, dict):
        raise ValueError("Manifest download_urls and checksums must be objects")

    specs: dict[str, tuple[str, str]] = {}
    for key, filename in files.items():
        url = urls.get(key)
        checksum = checksums.get(key)
        if not isinstance(url, str):
            raise ValueError(f"No download URL provided for {filename}")
        if not isinstance(checksum, str) or not _SHA256_PATTERN.fullmatch(checksum):
            raise ValueError(f"No valid SHA-256 checksum provided for {filename}")
        specs[key] = (
            _validate_download_url(url, allow_insecure_urls=allow_insecure_urls),
            checksum.lower(),
        )
    return specs


def _verify_checksum(content: bytes, expected_hash: str, filename: str) -> None:
    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != expected_hash.lower():
        raise ValueError(f"Checksum mismatch for {filename}: expected {expected_hash}, got {actual_hash}")


def _file_mode(filename: str) -> int:
    return 0o755 if filename in {"installer.py", "plex_cli.py"} else 0o644


def _write_staged_file(path: Path, content: bytes, mode: int) -> None:
    """Write and fsync one staged file with its final permissions."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)
    os.chmod(path, mode)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _replace_staged_files(staged: dict[str, Path], install_dir: Path) -> None:
    """Replace staged files and restore every old file on any failure."""
    rollback_dir = Path(tempfile.mkdtemp(prefix=".update-rollback-", dir=install_dir))
    states: list[tuple[Path, Path | None]] = []
    try:
        for filename, staged_path in staged.items():
            target = install_dir / filename
            backup: Path | None = None
            if target.exists() or target.is_symlink():
                backup = rollback_dir / filename
                os.replace(target, backup)
            states.append((target, backup))
            os.replace(staged_path, target)
    except Exception as update_error:
        rollback_errors: list[str] = []
        for target, backup in reversed(states):
            try:
                _remove_path(target)
                if backup is not None and (backup.exists() or backup.is_symlink()):
                    os.replace(backup, target)
            except Exception as rollback_error:
                rollback_errors.append(f"{target.name}: {rollback_error}")
        if rollback_errors:
            details = "; ".join(rollback_errors)
            raise RuntimeError(f"Update failed ({update_error}); rollback was incomplete: {details}") from update_error
        raise
    finally:
        shutil.rmtree(rollback_dir, ignore_errors=True)


def _primary_key_fingerprints(colon_output: str) -> list[str]:
    """Extract primary-key fingerprints from GnuPG's colon format."""
    fingerprints: list[str] = []
    awaiting_primary_fingerprint = False
    for line in colon_output.splitlines():
        fields = line.split(":")
        record_type = fields[0] if fields else ""
        if record_type == "pub":
            awaiting_primary_fingerprint = True
        elif record_type == "fpr" and awaiting_primary_fingerprint and len(fields) > 9:
            fingerprints.append(fields[9].upper())
            awaiting_primary_fingerprint = False
    return fingerprints


def _valid_signature_fingerprints(status_output: str) -> set[str]:
    """Extract signing and primary fingerprints from VALIDSIG records."""
    fingerprints: set[str] = set()
    for line in status_output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "[GNUPG:]" and fields[1] == "VALIDSIG":
            fingerprints.add(fields[2].upper())
            if len(fields) >= 12:
                fingerprints.add(fields[-1].upper())
    return fingerprints


def download_missing_files(
    *,
    print_info: Callable[[str], None],
    print_success: Callable[[str], None],
    print_warning: Callable[[str], None],
    print_error: Callable[[str], None],
    allow_insecure_urls: bool = False,
) -> None:
    """Repair managed files only after authenticating the remote manifest.

    All missing files are staged and verified before any target is installed.
    ``allow_insecure_urls`` exists only for tests using a local HTTP server.
    """
    missing = {key: filename for key, filename in UPDATE_FILE_MAP.items() if not (INSTALLER_DIR / filename).exists()}
    if not missing:
        return

    print_info(f"Downloading {len(missing)} missing file(s)...")
    try:
        version_json_bytes = _download_bytes(
            VERSION_CHECK_URL,
            timeout=15,
            max_bytes=MAX_MANIFEST_BYTES,
            allow_insecure_urls=allow_insecure_urls,
        )
    except Exception as exc:
        print_error(f"Could not fetch version manifest: {exc}")
        return

    if not verify_gpg_signature(
        version_json_bytes,
        print_info=print_info,
        print_success=print_success,
        print_warning=print_warning,
        print_error=print_error,
        allow_insecure_urls=allow_insecure_urls,
    ):
        print_error("Missing-file repair aborted: manifest authentication failed")
        return

    try:
        specs = _validated_download_specs(
            _parse_manifest(version_json_bytes),
            missing,
            allow_insecure_urls=allow_insecure_urls,
        )
        INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".repair-stage-", dir=INSTALLER_DIR) as temp_dir:
            stage_dir = Path(temp_dir)
            staged: dict[str, Path] = {}
            for key, filename in missing.items():
                url, expected_hash = specs[key]
                print_info(f"Downloading {filename}...")
                content = _download_bytes(
                    url,
                    timeout=30,
                    max_bytes=MAX_UPDATE_FILE_BYTES,
                    allow_insecure_urls=allow_insecure_urls,
                )
                _verify_checksum(content, expected_hash, filename)
                staged_path = stage_dir / filename
                _write_staged_file(staged_path, content, _file_mode(filename))
                staged[filename] = staged_path

            _replace_staged_files(staged, INSTALLER_DIR)
            for filename in staged:
                print_success(f"Installed {filename}")
    except Exception as exc:
        print_error(f"Missing-file repair failed; no partial repair was kept: {exc}")


def is_newer_version(remote: str, local: str) -> bool:
    """Compare semantic-ish version strings.

    Returns True if *remote* is strictly newer than *local*.
    """
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


def verify_gpg_signature(
    version_json_bytes: bytes,
    *,
    print_info: Callable[[str], None],
    print_success: Callable[[str], None],
    print_warning: Callable[[str], None],
    print_error: Callable[[str], None],
    signature_url: str = VERSION_SIGNATURE_URL,
    key_path: Path | None = None,
    allow_insecure_urls: bool = False,
) -> bool:
    """Verify the manifest with the bundled, fingerprint-pinned release key.

    A fresh isolated GnuPG home is used. The user's keyring is never trusted or
    modified, no key is downloaded, and every verification error fails closed.
    """
    del print_warning  # Retained in the shared callback API for compatibility.
    release_key = key_path if key_path is not None else INSTALLER_DIR / "release-key.gpg"
    try:
        if not release_key.is_file():
            print_error(f"Bundled release key not found: {release_key}")
            return False

        key_result = subprocess.run(
            ["gpg", "--batch", "--no-options", "--with-colons", "--show-keys", "--fingerprint", str(release_key)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        primary_fingerprints = _primary_key_fingerprints(key_result.stdout) if key_result.returncode == 0 else []
        if primary_fingerprints != [RELEASE_KEY_FINGERPRINT]:
            found = ", ".join(primary_fingerprints) or "none"
            print_error(f"Bundled release key fingerprint mismatch (found: {found})")
            return False

        print_info("Downloading GPG signature...")
        sig_bytes = _download_bytes(
            signature_url,
            timeout=10,
            max_bytes=MAX_SIGNATURE_BYTES,
            allow_insecure_urls=allow_insecure_urls,
        )

        with tempfile.TemporaryDirectory(prefix="plexinstaller-gpg-") as temp_dir:
            gpg_home = Path(temp_dir) / "home"
            gpg_home.mkdir(mode=0o700)
            sig_path = Path(temp_dir) / "version.json.sig"
            data_path = Path(temp_dir) / "version.json"
            _write_staged_file(sig_path, sig_bytes, 0o600)
            _write_staged_file(data_path, version_json_bytes, 0o600)

            import_result = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--no-options",
                    "--homedir",
                    str(gpg_home),
                    "--import-options",
                    "import-clean",
                    "--import",
                    str(release_key),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if import_result.returncode != 0:
                print_error(f"Could not import bundled release key: {import_result.stderr.strip()}")
                return False

            result = subprocess.run(
                [
                    "gpg",
                    "--batch",
                    "--no-options",
                    "--homedir",
                    str(gpg_home),
                    "--status-fd",
                    "1",
                    "--no-auto-key-retrieve",
                    "--verify",
                    str(sig_path),
                    str(data_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            valid_fingerprints = _valid_signature_fingerprints(result.stdout)
            if result.returncode != 0 or RELEASE_KEY_FINGERPRINT not in valid_fingerprints:
                detail = result.stderr.strip() or "signature was not made by the pinned release key"
                print_error(f"GPG signature verification failed: {detail}")
                return False

        print_success("GPG signature and pinned release key verified")
        return True
    except FileNotFoundError:
        print_error("gpg is required for stable update verification")
        return False
    except Exception as exc:
        print_error(f"GPG verification error: {exc}")
        return False


def ensure_cli_entrypoints() -> None:
    """Ensure commands run the installer through its isolated virtualenv."""
    if os.geteuid() != 0:
        return

    try:
        bin_dir = Path("/usr/local/bin")
        bin_dir.mkdir(parents=True, exist_ok=True)
        _write_entrypoint(bin_dir / "plexinstaller", INSTALLER_DIR / "installer.py")
        _write_entrypoint(bin_dir / "plex", INSTALLER_DIR / "plex_cli.py")
    except Exception:
        pass


def _write_entrypoint(entrypoint: Path, script: Path) -> None:
    """Atomically create a wrapper that invokes a script with the bundle venv."""
    if not script.exists():
        return
    bundled_python = INSTALLER_DIR / ".venv" / "bin" / "python"
    content = (
        "#!/bin/sh\n"
        f'python="{bundled_python}"\n'
        'if [ ! -x "$python" ]; then python="${PYTHON:-python3}"; fi\n'
        f'exec "$python" "{script}" "$@"\n'
    ).encode()
    fd, temp_name = tempfile.mkstemp(prefix=f".{entrypoint.name}.", dir=entrypoint.parent)
    temp_path = Path(temp_name)
    try:
        os.write(fd, content)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.chmod(temp_path, 0o755)
        os.replace(temp_path, entrypoint)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


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
    version_data: dict,
    version_json_bytes: bytes,
    *,
    print_info: Callable[[str], None],
    print_success: Callable[[str], None],
    print_warning: Callable[[str], None],
    print_error: Callable[[str], None],
    allow_insecure_urls: bool = False,
) -> None:
    """Install a complete authenticated update as a rollback-safe transaction.

    ``allow_insecure_urls`` is a testability hook for local HTTP servers and
    must remain disabled in production callers.
    """
    if os.geteuid() != 0:
        print_warning("Auto-update requires root. Re-run the command with sudo.")
        return

    if not verify_gpg_signature(
        version_json_bytes,
        print_info=print_info,
        print_success=print_success,
        print_warning=print_warning,
        print_error=print_error,
        allow_insecure_urls=allow_insecure_urls,
    ):
        print_error("Update aborted: GPG signature verification failed")
        return

    try:
        authenticated_data = _parse_manifest(version_json_bytes)
        if authenticated_data != version_data:
            raise ValueError("Parsed manifest does not match the authenticated manifest bytes")
        specs = _validated_download_specs(
            authenticated_data,
            UPDATE_FILE_MAP,
            allow_insecure_urls=allow_insecure_urls,
        )
        INSTALLER_DIR.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix=".update-stage-", dir=INSTALLER_DIR) as temp_dir:
            stage_dir = Path(temp_dir)
            staged: dict[str, Path] = {}
            for key, filename in UPDATE_FILE_MAP.items():
                url, expected_hash = specs[key]
                print_info(f"Downloading {filename}...")
                content = _download_bytes(
                    url,
                    timeout=30,
                    max_bytes=MAX_UPDATE_FILE_BYTES,
                    allow_insecure_urls=allow_insecure_urls,
                )
                _verify_checksum(content, expected_hash, filename)
                print_success(f"Checksum verified for {filename}")
                staged_path = stage_dir / filename
                _write_staged_file(staged_path, content, _file_mode(filename))
                staged[filename] = staged_path

            _replace_staged_files(staged, INSTALLER_DIR)
    except Exception as exc:
        print_error(f"Update failed; the previous installation was preserved: {exc}")
        return

    ensure_cli_entrypoints()
    print_success("Update completed successfully. Restarting...")
    try:
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except Exception as exc:
        print_warning(f"Update installed, but automatic restart failed: {exc}")
