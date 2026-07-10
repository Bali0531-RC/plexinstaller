#!/usr/bin/env python3
"""Prepare a signed release manifest for the Windows experimental channel."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "version.json"
SIGNATURE = ROOT / "version.json.sig"
PUBLIC_KEY = ROOT / "release-key.gpg"
INSTALLER = ROOT / "installer.py"
PYPROJECT = ROOT / "pyproject.toml"
UPDATE_BRANCH = "windows-experimental"
REPOSITORY = "Bali0531-RC/plexinstaller"
SIGNING_FINGERPRINT = "431E869D5BB519AFF7B028379B0DFA4BF86307BD"
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
MANAGED_FILES = {
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


def _atomic_write(path: Path, content: bytes) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _replace_once(path: Path, pattern: str, replacement: str) -> None:
    original = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, original, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"Could not update version in {path.name}")
    _atomic_write(path, updated.encode("utf-8"))


def _fingerprints(output: str) -> list[str]:
    fingerprints: list[str] = []
    awaiting_primary = False
    for line in output.splitlines():
        fields = line.split(":")
        record_type = fields[0] if fields else ""
        if record_type in {"pub", "sec"}:
            awaiting_primary = True
        elif record_type == "fpr" and awaiting_primary and len(fields) > 9:
            fingerprints.append(fields[9].upper())
            awaiting_primary = False
    return fingerprints


def _require_signing_key(gpg: str) -> None:
    result = subprocess.run(
        [gpg, "--batch", "--no-options", "--with-colons", "--list-secret-keys", "--fingerprint", SIGNING_FINGERPRINT],
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if result.returncode != 0 or SIGNING_FINGERPRINT not in _fingerprints(result.stdout):
        raise RuntimeError(f"Required signing key is unavailable: {SIGNING_FINGERPRINT}")


def _verify_artifacts(gpg: str) -> None:
    with tempfile.TemporaryDirectory(prefix="plexinstaller-release-verify-") as temp_dir:
        home = Path(temp_dir)
        os.chmod(home, 0o700)
        env = os.environ.copy()
        env["GNUPGHOME"] = str(home)
        key_info = subprocess.run(
            [gpg, "--batch", "--no-options", "--with-colons", "--show-keys", "--fingerprint", str(PUBLIC_KEY)],
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            check=False,
        )
        if _fingerprints(key_info.stdout) != [SIGNING_FINGERPRINT]:
            raise RuntimeError("Exported release key fingerprint does not match the pinned key")
        subprocess.run([gpg, "--batch", "--import", str(PUBLIC_KEY)], env=env, check=True, capture_output=True)
        verification = subprocess.run(
            [
                gpg,
                "--batch",
                "--no-auto-key-retrieve",
                "--status-fd",
                "1",
                "--verify",
                str(SIGNATURE),
                str(MANIFEST),
            ],
            capture_output=True,
            text=True,
            errors="replace",
            env=env,
            check=False,
        )
        valid = any(
            line.startswith("[GNUPG:] VALIDSIG ")
            and (line.split()[2].upper() == SIGNING_FINGERPRINT or line.split()[-1].upper() == SIGNING_FINGERPRINT)
            for line in verification.stdout.splitlines()
        )
        if verification.returncode != 0 or not valid:
            raise RuntimeError("Detached manifest signature verification failed")


def prepare(version: str, changelog: list[str]) -> None:
    if not SEMVER.fullmatch(version):
        raise ValueError(f"Invalid semantic version: {version}")
    if not changelog:
        raise ValueError("At least one changelog entry is required")

    gpg = shutil.which("gpg")
    if gpg is None:
        raise RuntimeError("gpg is required to prepare a signed Windows release")
    _require_signing_key(gpg)

    _replace_once(INSTALLER, r'^INSTALLER_VERSION = ".*"$', f'INSTALLER_VERSION = "{version}"')
    _replace_once(PYPROJECT, r'^version = ".*"$', f'version = "{version}"')

    checksums = {
        key: hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        for key, filename in sorted(MANAGED_FILES.items())
    }
    base_url = f"https://raw.githubusercontent.com/{REPOSITORY}/{UPDATE_BRANCH}"
    manifest = {
        "version": version,
        "channel": UPDATE_BRANCH,
        "release_date": date.today().isoformat(),
        "changelog": changelog,
        "download_urls": {key: f"{base_url}/{filename}" for key, filename in MANAGED_FILES.items()},
        "checksums": checksums,
    }
    _atomic_write(MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))

    signature_fd, signature_name = tempfile.mkstemp(prefix=".version.json.sig.", dir=ROOT)
    os.close(signature_fd)
    signature_temp = Path(signature_name)
    key_fd, key_name = tempfile.mkstemp(prefix=".release-key.gpg.", dir=ROOT)
    os.close(key_fd)
    key_temp = Path(key_name)
    try:
        subprocess.run(
            [
                gpg,
                "--batch",
                "--yes",
                "--detach-sign",
                "--armor",
                "--local-user",
                SIGNING_FINGERPRINT,
                "--output",
                str(signature_temp),
                str(MANIFEST),
            ],
            check=True,
        )
        exported = subprocess.run(
            [gpg, "--batch", "--yes", "--armor", "--export", SIGNING_FINGERPRINT],
            check=True,
            capture_output=True,
        ).stdout
        if not signature_temp.stat().st_size or not exported:
            raise RuntimeError("GPG did not produce complete release artifacts")
        key_temp.write_bytes(exported)
        os.chmod(signature_temp, 0o644)
        os.chmod(key_temp, 0o644)
        os.replace(signature_temp, SIGNATURE)
        os.replace(key_temp, PUBLIC_KEY)
    finally:
        signature_temp.unlink(missing_ok=True)
        key_temp.unlink(missing_ok=True)

    _verify_artifacts(gpg)
    print(f"Prepared signed Windows release {version} for {UPDATE_BRANCH}.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--entry", action="append", dest="entries", default=[])
    args = parser.parse_args()
    prepare(args.version, args.entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
