"""Release publishing and changelog-page workflow contracts."""

from pathlib import Path

ROOT = Path(__file__).parents[1]
RELEASE_SCRIPT = (ROOT / "release.sh").read_text()
VITE_CONFIG = (ROOT / "web2/vite.config.ts").read_text()
CI_WORKFLOW = (ROOT / ".github/workflows/ci.yml").read_text()
HOMEPAGE_RELEASES = (ROOT / "web2/src/components/ReleaseTimeline.tsx").read_text()


def test_complete_changelog_is_a_first_party_page():
    assert (ROOT / "web2/changelog.html").is_file()
    assert (ROOT / "web2/src/pages/changelog.tsx").is_file()
    assert 'changelog: resolve(__dirname, "changelog.html")' in VITE_CONFIG
    assert "dist/changelog.html" in CI_WORKFLOW
    assert 'href="/changelog.html"' in HOMEPAGE_RELEASES


def test_publish_mode_requires_authenticated_github_cli():
    assert "command -v gh" in RELEASE_SCRIPT
    assert "gh auth status" in RELEASE_SCRIPT


def test_publish_mode_creates_signed_tag_and_github_release():
    assert 'tag -s -u "$RELEASE_SIGNING_FINGERPRINT"' in RELEASE_SCRIPT
    assert 'gh release create "$tag_name"' in RELEASE_SCRIPT
    assert 'gh release edit "$tag_name"' in RELEASE_SCRIPT
    assert 'gh release upload "$tag_name"' in RELEASE_SCRIPT
    assert "--verify-tag" in RELEASE_SCRIPT
    assert 'publish_github_release "$NEW_VERSION"' in RELEASE_SCRIPT


def test_publish_current_recovers_release_without_regenerating_metadata():
    assert "--publish-current" in RELEASE_SCRIPT
    publish_current = RELEASE_SCRIPT.index('if [ "$PUBLISH_CURRENT" = true ]; then')
    metadata_mutation = RELEASE_SCRIPT.index('sed -i "s/^INSTALLER_VERSION')
    assert publish_current < metadata_mutation
    assert 'echo "Published current signed release $NEW_VERSION."' in RELEASE_SCRIPT
    assert "--publish-current cannot be combined with --prepare-only" in RELEASE_SCRIPT


def test_publish_reuses_only_the_expected_remote_signed_tag():
    assert 'ls-remote --tags origin "refs/tags/$tag_name"' in RELEASE_SCRIPT
    assert 'fetch --no-tags origin "refs/tags/$tag_name:refs/tags/$tag_name"' in RELEASE_SCRIPT
    assert 'local_tag_oid" != "$remote_tag_oid' in RELEASE_SCRIPT
    assert 'verify-tag --raw "$tag_name"' in RELEASE_SCRIPT
    assert 'expected="$RELEASE_SIGNING_FINGERPRINT"' in RELEASE_SCRIPT


def test_prepare_only_still_skips_commit_push_and_release():
    prepare_guard = RELEASE_SCRIPT.index('if [ "$PREPARE_ONLY" = true ]; then')
    commit = RELEASE_SCRIPT.index('git -C "$SCRIPT_DIR" commit')
    final_publish = RELEASE_SCRIPT.rindex('publish_github_release "$NEW_VERSION"')
    assert prepare_guard < commit < final_publish


def test_signature_generation_is_atomic():
    assert 'SIGNATURE_TMP="$(mktemp' in RELEASE_SCRIPT
    assert 'KEY_TMP="$(mktemp' in RELEASE_SCRIPT
    assert 'mv "$SIGNATURE_TMP" "$SCRIPT_DIR/version.json.sig"' in RELEASE_SCRIPT
    assert 'mv "$KEY_TMP" "$SCRIPT_DIR/release-key.gpg"' in RELEASE_SCRIPT
