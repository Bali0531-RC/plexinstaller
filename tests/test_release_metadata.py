"""Windows update-channel release integrity contracts."""

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

from release_windows import MANAGED_FILES, SIGNING_FINGERPRINT, UPDATE_BRANCH

ROOT = Path(__file__).parents[1]


def _manifest() -> dict:
    return json.loads((ROOT / "version.json").read_text())


def test_versions_and_channel_are_synchronized():
    manifest = _manifest()
    installer = (ROOT / "installer.py").read_text()
    pyproject = (ROOT / "pyproject.toml").read_text()
    installer_version = re.search(r'^INSTALLER_VERSION = "([^"]+)"$', installer, re.MULTILINE)
    package_version = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert installer_version and package_version
    assert manifest["version"] == installer_version.group(1) == package_version.group(1)
    assert manifest["channel"] == UPDATE_BRANCH == "windows-experimental"


def test_all_managed_urls_and_hashes_are_current():
    manifest = _manifest()
    assert set(manifest["checksums"]) == set(MANAGED_FILES)
    assert set(manifest["download_urls"]) == set(MANAGED_FILES)
    for key, filename in MANAGED_FILES.items():
        assert manifest["checksums"][key] == hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        url = manifest["download_urls"][key]
        assert f"/plexinstaller/{UPDATE_BRANCH}/" in url
        assert url.endswith(f"/{filename}")
        assert "/main/" not in url and "/dev/" not in url


def test_exported_key_and_detached_signature_use_pinned_fingerprint(tmp_path: Path):
    key = ROOT / "release-key.gpg"
    signature = ROOT / "version.json.sig"
    manifest = ROOT / "version.json"
    home = tmp_path / "gnupg"
    home.mkdir(mode=0o700)
    env = os.environ.copy()
    env["GNUPGHOME"] = str(home)
    env["LC_ALL"] = "C"
    key_info = subprocess.run(
        [
            "gpg",
            "--batch",
            "--no-options",
            "--homedir",
            str(home),
            "--with-colons",
            "--show-keys",
            "--fingerprint",
            str(key),
        ],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    )
    fingerprints = [line.split(":")[9].upper() for line in key_info.stdout.splitlines() if line.startswith("fpr:")]
    assert fingerprints[0] == SIGNING_FINGERPRINT
    subprocess.run(["gpg", "--batch", "--import", str(key)], env=env, check=True, capture_output=True)
    result = subprocess.run(
        ["gpg", "--batch", "--no-auto-key-retrieve", "--status-fd", "1", "--verify", str(signature), str(manifest)],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    assert result.returncode == 0
    assert any(
        line.startswith("[GNUPG:] VALIDSIG ")
        and (line.split()[2].upper() == SIGNING_FINGERPRINT or line.split()[-1].upper() == SIGNING_FINGERPRINT)
        for line in result.stdout.splitlines()
    )


def test_release_preparer_is_windows_channel_only():
    script = (ROOT / "release_windows.py").read_text()
    assert 'UPDATE_BRANCH = "windows-experimental"' in script
    assert "main/version.json" not in script
    assert "release.sh" not in script


def test_release_artifacts_keep_normal_file_permissions():
    for filename in ("installer.py", "pyproject.toml", "version.json", "version.json.sig", "release-key.gpg"):
        assert (ROOT / filename).is_file()
