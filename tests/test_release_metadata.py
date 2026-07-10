"""Release metadata must stay synchronized through release.sh."""

import hashlib
import json
import re
from pathlib import Path

import installer

ROOT = Path(__file__).parents[1]
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
    "requirements": "requirements.txt",
}


def _manifest() -> dict:
    return json.loads((ROOT / "version.json").read_text())


def _top_site_release() -> tuple[str, str, list[str]]:
    content = (ROOT / "web2/src/data/changelog.ts").read_text()
    match = re.search(
        r'export const releases: ReleaseNote\[\] = \[\s*\{\s*version: (?P<version>".*?"),'
        r'\s*date: (?P<date>".*?"),\s*highlights: \[(?P<highlights>.*?)\]\s*\}',
        content,
        re.DOTALL,
    )
    assert match is not None, "Could not parse the first website release entry"
    highlights = [json.loads(value) for value in re.findall(r'("(?:[^"\\]|\\.)*")\s*,?', match.group("highlights"))]
    return json.loads(match.group("version")), json.loads(match.group("date")), highlights


def test_release_versions_are_synchronized():
    manifest = _manifest()
    pyproject = (ROOT / "pyproject.toml").read_text()
    package_version = re.search(r'^version = "(?P<version>[^"]+)"$', pyproject, re.MULTILINE)

    assert package_version is not None
    assert manifest["version"] == installer.INSTALLER_VERSION == package_version.group("version")


def test_website_release_matches_manifest():
    manifest = _manifest()
    site_version, site_date, site_highlights = _top_site_release()

    assert site_version == manifest["version"]
    assert site_date == manifest["release_date"]
    assert site_highlights == manifest["changelog"]


def test_all_signed_release_hashes_are_current():
    checksums = _manifest()["checksums"]
    assert set(checksums) == set(MANAGED_FILES)

    for key, filename in MANAGED_FILES.items():
        actual = hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        assert checksums[key] == actual, f"Stale checksum for {filename}; run release.sh"
