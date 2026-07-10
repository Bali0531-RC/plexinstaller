#!/usr/bin/env python3
"""
Shared utilities for PlexDevelopment Installer and Plex CLI.

Contains update logic, GPG verification, version comparison, and CLI entrypoint
management that were previously duplicated between installer.py and plex_cli.py.
"""

import ctypes
import hashlib
import json
import ntpath
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

INSTALLER_DIR = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "plexinstaller"
UPDATE_REPOSITORY = "Bali0531-RC/plexinstaller"
UPDATE_BRANCH = "windows-experimental"
UPDATE_CHANNEL = UPDATE_BRANCH
UPDATE_BASE_URL = f"https://raw.githubusercontent.com/{UPDATE_REPOSITORY}/{UPDATE_BRANCH}"
VERSION_CHECK_URL = f"{UPDATE_BASE_URL}/version.json"
VERSION_SIGNATURE_URL = f"{UPDATE_BASE_URL}/version.json.sig"
RELEASE_KEY_URL = f"{UPDATE_BASE_URL}/release-key.gpg"
RELEASE_KEY_FINGERPRINT = "431E869D5BB519AFF7B028379B0DFA4BF86307BD"

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_SIGNATURE_BYTES = 1024 * 1024
MAX_RELEASE_KEY_BYTES = 1024 * 1024
MAX_UPDATE_FILE_BYTES = 16 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_UPDATE_PATH_PREFIX = f"/{UPDATE_REPOSITORY}/{UPDATE_BRANCH}/"

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


def _is_windows() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    """Return whether this process has Windows Administrator privileges."""
    if not _is_windows():
        return False
    try:
        windll = getattr(ctypes, "windll", None)
        shell32 = getattr(windll, "shell32", None)
        check_admin = getattr(shell32, "IsUserAnAdmin", None)
        return bool(check_admin()) if check_admin is not None else False
    except (AttributeError, OSError):
        return False


def _validate_download_url(url: str, *, allow_insecure_urls: bool = False) -> str:
    """Validate an update URL against the pinned Windows update channel."""
    if not isinstance(url, str) or not url:
        raise ValueError("Download URL must be a non-empty string")

    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Unsafe download URL for {url!r}") from exc

    if parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError(f"Unsafe download URL for {url!r}")

    # This hook is only for isolated tests using a local HTTP server. Production
    # callers retain the strict raw-GitHub branch policy below.
    if allow_insecure_urls and parsed.scheme.lower() == "http":
        if not parsed.hostname or parsed.query:
            raise ValueError(f"Unsafe download URL for {url!r}")
        return url

    decoded_path = unquote(parsed.path)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "raw.githubusercontent.com"
        or port not in (None, 443)
        or parsed.query
        or not decoded_path.startswith(_UPDATE_PATH_PREFIX)
        or "\\" in decoded_path
        or ".." in decoded_path.split("/")
    ):
        raise ValueError(f"URL is outside the {UPDATE_CHANNEL} update channel: {url!r}")
    return url


def _content_length(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Length") if headers is not None and hasattr(headers, "get") else None
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip().isdigit():
        raise ValueError("Invalid Content-Length header")
    return int(value.strip())


def _download_bytes(
    url: str,
    *,
    timeout: int,
    max_bytes: int,
    allow_insecure_urls: bool = False,
) -> bytes:
    """Download a bounded response in chunks and reject unsafe redirects."""
    if max_bytes < 0:
        raise ValueError("Download size limit must not be negative")
    _validate_download_url(url, allow_insecure_urls=allow_insecure_urls)

    with urllib.request.urlopen(url, timeout=timeout) as response:
        final_url = response.geturl() if hasattr(response, "geturl") else None
        if isinstance(final_url, str):
            _validate_download_url(final_url, allow_insecure_urls=allow_insecure_urls)

        expected_length = _content_length(response)
        if expected_length is not None and expected_length > max_bytes:
            raise ValueError(f"Download exceeds the {max_bytes}-byte size limit")

        limit = max_bytes + 1
        content = bytearray()
        while len(content) < limit:
            chunk = response.read(min(_DOWNLOAD_CHUNK_BYTES, limit - len(content)))
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise TypeError("Download stream returned non-byte content")
            content.extend(chunk)

    if len(content) > max_bytes:
        raise ValueError(f"Download exceeds the {max_bytes}-byte size limit")
    if expected_length is not None and len(content) != expected_length:
        raise ValueError(f"Incomplete download: expected {expected_length} bytes, received {len(content)}")
    return bytes(content)


def _read_bounded_file(path: Path, max_bytes: int) -> bytes:
    """Read a local key file without allowing an unbounded allocation."""
    content = bytearray()
    with path.open("rb") as handle:
        while len(content) <= max_bytes:
            chunk = handle.read(min(_DOWNLOAD_CHUNK_BYTES, max_bytes + 1 - len(content)))
            if not chunk:
                break
            content.extend(chunk)
    if len(content) > max_bytes:
        raise ValueError(f"{path.name} exceeds the {max_bytes}-byte size limit")
    return bytes(content)


def _parse_manifest(version_json_bytes: bytes) -> dict:
    """Parse authenticated manifest bytes as a JSON object."""
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
    """Require a valid channel URL and SHA-256 checksum for every file."""
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


def _make_path_private(path: Path, *, directory: bool) -> None:
    """Restrict a temporary path, including its Windows ACL when possible."""
    try:
        path.chmod(0o700 if directory else 0o600)
    except OSError:
        pass

    if not _is_windows():
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
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _write_staged_file(path: Path, content: bytes) -> None:
    """Create and fsync a file inside a private staging directory."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    _make_path_private(path, directory=False)


def _atomic_write(path: Path, content: bytes) -> None:
    """Atomically replace one file with fully written content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _replace_staged_files(staged: dict[str, Path], install_dir: Path) -> None:
    """Activate staged files and completely roll back any failed transaction."""
    rollback_dir = Path(tempfile.mkdtemp(prefix=".update-rollback-", dir=install_dir))
    _make_path_private(rollback_dir, directory=True)
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
    """Extract primary-key fingerprints from GnuPG colon output."""
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
    """Repair missing files only after authenticating the exact manifest bytes."""
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
            _make_path_private(stage_dir, directory=True)
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
                _write_staged_file(staged_path, content)
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
    key_url: str = RELEASE_KEY_URL,
    key_path: Path | None = None,
    allow_insecure_urls: bool = False,
) -> bool:
    """Verify the manifest with a fingerprint-pinned key in an isolated keyring."""
    del print_warning  # Kept in the callback API for existing callers.
    try:
        gpg = shutil.which("gpg")
        if gpg is None:
            print_error("gpg is required for update verification")
            return False

        release_key: Path | None = None
        if key_path is not None:
            if not key_path.is_file():
                print_error(f"Bundled release key not found: {key_path}")
                return False
            release_key = key_path
        else:
            for candidate in (INSTALLER_DIR / "release-key.gpg", Path(__file__).resolve().with_name("release-key.gpg")):
                if candidate.is_file():
                    release_key = candidate
                    break

        if release_key is not None:
            key_bytes = _read_bounded_file(release_key, MAX_RELEASE_KEY_BYTES)
        else:
            print_info("Downloading pinned GPG release key...")
            key_bytes = _download_bytes(
                key_url,
                timeout=10,
                max_bytes=MAX_RELEASE_KEY_BYTES,
                allow_insecure_urls=allow_insecure_urls,
            )

        print_info("Downloading GPG signature...")
        sig_bytes = _download_bytes(
            signature_url,
            timeout=10,
            max_bytes=MAX_SIGNATURE_BYTES,
            allow_insecure_urls=allow_insecure_urls,
        )

        with tempfile.TemporaryDirectory(prefix="plexinstaller-gpg-") as temp_dir:
            temp_path = Path(temp_dir)
            _make_path_private(temp_path, directory=True)
            gpg_home = temp_path / "gnupg"
            gpg_home.mkdir(mode=0o700)
            _make_path_private(gpg_home, directory=True)
            temp_key = temp_path / "release-key.gpg"
            sig_path = temp_path / "version.json.sig"
            data_path = temp_path / "version.json"
            _write_staged_file(temp_key, key_bytes)
            _write_staged_file(sig_path, sig_bytes)
            _write_staged_file(data_path, version_json_bytes)

            gpg_env = os.environ.copy()
            gpg_env["GNUPGHOME"] = str(gpg_home)
            common_args = [gpg, "--batch", "--no-options", "--homedir", str(gpg_home)]
            key_result = subprocess.run(
                [*common_args, "--with-colons", "--show-keys", "--fingerprint", str(temp_key)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
                env=gpg_env,
                check=False,
            )
            primary_fingerprints = _primary_key_fingerprints(key_result.stdout) if key_result.returncode == 0 else []
            if primary_fingerprints != [RELEASE_KEY_FINGERPRINT]:
                found = ", ".join(primary_fingerprints) or "none"
                print_error(f"Release key fingerprint mismatch (found: {found})")
                return False

            import_result = subprocess.run(
                [*common_args, "--import-options", "import-clean", "--import", str(temp_key)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=15,
                env=gpg_env,
                check=False,
            )
            if import_result.returncode != 0:
                print_error(f"Could not import release key: {import_result.stderr.strip()}")
                return False

            result = subprocess.run(
                [
                    *common_args,
                    "--status-fd",
                    "1",
                    "--no-auto-key-retrieve",
                    "--verify",
                    str(sig_path),
                    str(data_path),
                ],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
                env=gpg_env,
                check=False,
            )
            valid_fingerprints = _valid_signature_fingerprints(result.stdout)
            if result.returncode != 0 or RELEASE_KEY_FINGERPRINT not in valid_fingerprints:
                detail = result.stderr.strip() or "signature was not made by the pinned release key"
                print_error(f"GPG signature verification failed: {detail}")
                return False

        print_success("GPG signature and pinned release key verified")
        return True
    except FileNotFoundError:
        print_error("gpg is required for update verification")
        return False
    except Exception as exc:
        print_error(f"GPG verification error: {exc}")
        return False


def ensure_cli_entrypoints() -> None:
    """Ensure ``plexinstaller`` and ``plex`` commands are available on PATH.

    On Windows we create small .cmd wrapper scripts in the installer directory
    and add it to the user PATH if necessary.
    """
    if not _is_windows() or not is_admin():
        return

    try:
        INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
        _create_cmd_wrapper(INSTALLER_DIR / "plexinstaller.cmd", INSTALLER_DIR / "installer.py")
        _create_cmd_wrapper(INSTALLER_DIR / "plex.cmd", INSTALLER_DIR / "plex_cli.py")
        _add_to_system_path(INSTALLER_DIR)
    except Exception:
        pass


def _create_cmd_wrapper(wrapper_path: Path, target: Path) -> None:
    """Atomically create a .cmd wrapper that invokes an adjacent script."""
    if not target.exists():
        return
    if wrapper_path.parent != target.parent or any(character in target.name for character in {'"', "%", "\r", "\n"}):
        raise ValueError("Command wrapper target must be a safe adjacent filename")
    content = f'@echo off\r\npython "%~dp0{target.name}" %*\r\n'.encode("ascii")
    _atomic_write(wrapper_path, content)


def _normalized_windows_path(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path.strip().strip('"')))


def _path_contains(entries: str, directory: str) -> bool:
    expected = _normalized_windows_path(directory)
    return any(_normalized_windows_path(entry) == expected for entry in entries.split(";") if entry.strip())


def _add_to_system_path(directory: Path) -> None:
    """Append to the registry PATH without setx expansion or truncation."""
    if not _is_windows() or not is_admin():
        return

    try:
        import winreg as _winreg

        winreg: Any = _winreg
        access = winreg.KEY_READ | winreg.KEY_SET_VALUE | getattr(winreg, "KEY_WOW64_64KEY", 0)
        key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path, 0, access) as key:
            try:
                existing, value_type = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                existing, value_type = "", winreg.REG_EXPAND_SZ
            if not isinstance(existing, str):
                raise TypeError("System PATH registry value is not a string")

            directory_text = str(directory)
            if not _path_contains(existing, directory_text):
                separator = "" if not existing or existing.endswith(";") else ";"
                updated = f"{existing}{separator}{directory_text}"
                if value_type not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    value_type = winreg.REG_EXPAND_SZ
                winreg.SetValueEx(key, "Path", 0, value_type, updated)

        process_path = os.environ.get("PATH", "")
        if not _path_contains(process_path, str(directory)):
            separator = "" if not process_path or process_path.endswith(";") else ";"
            os.environ["PATH"] = f"{process_path}{separator}{directory}"
    except (ImportError, OSError, TypeError):
        return


def _restart_current_process() -> None:
    """Start the updated command in a replacement process."""
    subprocess.Popen([sys.executable, *sys.argv])


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
    """Install a complete authenticated update as a rollback-safe transaction."""
    if not is_admin():
        print_warning("Auto-update requires Administrator. Re-run the command as Administrator.")
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
            _make_path_private(stage_dir, directory=True)
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
                _write_staged_file(staged_path, content)
                staged[filename] = staged_path

            _replace_staged_files(staged, INSTALLER_DIR)
    except Exception as exc:
        print_error(f"Update failed; the previous installation was preserved: {exc}")
        return

    ensure_cli_entrypoints()
    print_success("Update completed successfully. Restarting...")
    try:
        _restart_current_process()
    except Exception as exc:
        print_warning(f"Update installed, but automatic restart failed: {exc}")
        return
    sys.exit(0)
