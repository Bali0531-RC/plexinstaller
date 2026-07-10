#!/usr/bin/env bash
# Prepare and optionally publish a signed PlexInstaller release.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION_FILE="$SCRIPT_DIR/version.json"
CHANGELOG_TS="$SCRIPT_DIR/web2/src/data/changelog.ts"
RELEASE_SIGNING_FINGERPRINT="431E869D5BB519AFF7B028379B0DFA4BF86307BD"
PREPARE_ONLY=false
ALLOW_DIRTY=false
PUBLISH_CURRENT=false
NEW_VERSION=""
UPDATE_CHANGELOG=""
CLI_CHANGELOG_ENTRIES=()

usage() {
  cat <<'EOF'
Usage: ./release.sh [options]

Options:
  --version VERSION    Release version. Defaults to the next patch version.
  --changelog          Prompt for new changelog entries.
  --entry TEXT         Add a changelog entry; may be repeated.
  --reuse-changelog    Reuse version.json changelog entries and upsert the site entry.
  --prepare-only       Generate hashes/changelogs/signatures without committing or pushing.
  --publish-current    Publish/update the already-prepared current version without changing files.
  --allow-dirty        Permit an existing worktree patch (implied by --prepare-only).
  -h, --help           Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --version)
      [ "$#" -ge 2 ] || { echo "--version requires a value" >&2; exit 64; }
      NEW_VERSION="$2"
      shift 2
      ;;
    --changelog)
      UPDATE_CHANGELOG="prompt"
      shift
      ;;
    --entry)
      [ "$#" -ge 2 ] || { echo "--entry requires text" >&2; exit 64; }
      UPDATE_CHANGELOG="cli"
      CLI_CHANGELOG_ENTRIES+=("$2")
      shift 2
      ;;
    --reuse-changelog)
      UPDATE_CHANGELOG="reuse"
      shift
      ;;
    --prepare-only)
      PREPARE_ONLY=true
      ALLOW_DIRTY=true
      shift
      ;;
    --publish-current)
      PUBLISH_CURRENT=true
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
done

if [ "$PUBLISH_CURRENT" = true ] && [ "$PREPARE_ONLY" = true ]; then
  echo "--publish-current cannot be combined with --prepare-only" >&2
  exit 64
fi

for command in jq gpg git sha256sum python3; do
  command -v "$command" >/dev/null 2>&1 || { echo "$command is required" >&2; exit 1; }
done
if [ "$PREPARE_ONLY" != true ]; then
  command -v gh >/dev/null 2>&1 || { echo "gh is required to publish a GitHub Release" >&2; exit 1; }
  gh auth status >/dev/null 2>&1 || { echo "Authenticate GitHub CLI first: gh auth login" >&2; exit 1; }
fi

if ! gpg --batch --with-colons --list-secret-keys "$RELEASE_SIGNING_FINGERPRINT" 2>/dev/null \
  | awk -F: -v expected="$RELEASE_SIGNING_FINGERPRINT" '$1 == "fpr" && toupper($10) == expected { found=1 } END { exit !found }'; then
  echo "Required release/Git signing key is unavailable: $RELEASE_SIGNING_FINGERPRINT" >&2
  exit 1
fi

[ -f "$VERSION_FILE" ] || { echo "Missing $VERSION_FILE" >&2; exit 1; }
if [ "$ALLOW_DIRTY" != true ] && [ -n "$(git -C "$SCRIPT_DIR" status --porcelain)" ]; then
  echo "Working tree must be clean. Commit reviewed implementation changes first, or use --prepare-only." >&2
  exit 1
fi

CURRENT_VERSION="$(jq -r '.version' "$VERSION_FILE")"
if [ "$PUBLISH_CURRENT" = true ]; then
  [ -z "$NEW_VERSION" ] || { echo "--publish-current cannot be combined with --version" >&2; exit 64; }
  [ -z "$UPDATE_CHANGELOG" ] || { echo "--publish-current cannot change the changelog" >&2; exit 64; }
  NEW_VERSION="$CURRENT_VERSION"
  UPDATE_CHANGELOG="reuse"
fi
if [ -z "$NEW_VERSION" ]; then
  IFS='.' read -r major minor patch <<< "$CURRENT_VERSION"
  NEW_VERSION="$major.$minor.$((patch + 1))"
  if [ -t 0 ]; then
    read -r -p "New version [$NEW_VERSION]: " requested_version
    NEW_VERSION="${requested_version:-$NEW_VERSION}"
  fi
fi
[[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Invalid semantic version: $NEW_VERSION" >&2; exit 64; }

if [ -z "$UPDATE_CHANGELOG" ]; then
  if [ "$NEW_VERSION" = "$CURRENT_VERSION" ]; then
    UPDATE_CHANGELOG="reuse"
  elif [ -t 0 ]; then
    read -r -p "Update changelog? [Y/n]: " answer
    case "${answer,,}" in n|no) UPDATE_CHANGELOG="reuse" ;; *) UPDATE_CHANGELOG="prompt" ;; esac
  else
    echo "Use --changelog or --reuse-changelog in non-interactive mode." >&2
    exit 64
  fi
fi

CHANGELOG_ENTRIES=()
if [ "$UPDATE_CHANGELOG" = "cli" ]; then
  CHANGELOG_ENTRIES=("${CLI_CHANGELOG_ENTRIES[@]}")
elif [ "$UPDATE_CHANGELOG" = "prompt" ]; then
  if [ ! -t 0 ]; then
    echo "--changelog requires an interactive terminal; use --reuse-changelog for automation." >&2
    exit 64
  fi
  echo "Enter changelog entries (one per line; empty line finishes):"
  while true; do
    read -r -p "  • " entry
    [ -n "$entry" ] || break
    CHANGELOG_ENTRIES+=("$entry")
  done
  [ "${#CHANGELOG_ENTRIES[@]}" -gt 0 ] || { echo "At least one changelog entry is required." >&2; exit 64; }
else
  mapfile -t CHANGELOG_ENTRIES < <(jq -r '.changelog[]?' "$VERSION_FILE")
  [ "${#CHANGELOG_ENTRIES[@]}" -gt 0 ] || { echo "version.json has no changelog entries to reuse." >&2; exit 64; }
fi

publish_github_release() {
  local tag_name="$1"
  local remote_tag_output
  local remote_tag_oid=""
  local local_tag_oid
  local release_notes

  if ! remote_tag_output="$(git -C "$SCRIPT_DIR" ls-remote --tags origin "refs/tags/$tag_name")"; then
    echo "Could not inspect remote tag $tag_name; refusing to publish blindly." >&2
    return 1
  fi
  if [ -n "$remote_tag_output" ]; then
    remote_tag_oid="$(printf '%s\n' "$remote_tag_output" | awk 'NR == 1 { print $1 }')"
  fi

  if git -C "$SCRIPT_DIR" rev-parse -q --verify "refs/tags/$tag_name" >/dev/null; then
    local_tag_oid="$(git -C "$SCRIPT_DIR" rev-parse "refs/tags/$tag_name")"
    if [ -n "$remote_tag_oid" ] && [ "$local_tag_oid" != "$remote_tag_oid" ]; then
      echo "Local and remote tag $tag_name differ; refusing to overwrite either tag." >&2
      return 1
    fi
  elif [ -n "$remote_tag_oid" ]; then
    git -C "$SCRIPT_DIR" fetch --no-tags origin "refs/tags/$tag_name:refs/tags/$tag_name"
  else
    git -C "$SCRIPT_DIR" tag -s -u "$RELEASE_SIGNING_FINGERPRINT" "$tag_name" -m "PlexInstaller $NEW_VERSION"
  fi

  if [ "$(git -C "$SCRIPT_DIR" rev-list -n 1 "$tag_name")" != "$(git -C "$SCRIPT_DIR" rev-parse HEAD)" ]; then
    echo "Tag $tag_name points to another commit; refusing to move it." >&2
    return 1
  fi
  if ! git -C "$SCRIPT_DIR" verify-tag --raw "$tag_name" 2>&1 \
    | awk -v expected="$RELEASE_SIGNING_FINGERPRINT" \
      '$1 == "[GNUPG:]" && $2 == "VALIDSIG" && ($3 == expected || $NF == expected) { found=1 } END { exit !found }'; then
    echo "Tag $tag_name is not signed by $RELEASE_SIGNING_FINGERPRINT; refusing to publish it." >&2
    return 1
  fi

  git -C "$SCRIPT_DIR" push origin HEAD
  git -C "$SCRIPT_DIR" push origin "refs/tags/$tag_name"

  release_notes="$(mktemp)"
  trap 'rm -f "${release_notes:-}"' EXIT
  {
    printf '## Changes\n\n'
    printf -- '- %s\n' "${CHANGELOG_ENTRIES[@]}"
    printf '\n## Verification\n\n'
    printf 'Release metadata and checksums are in `version.json`; verify it with `version.json.sig` and `release-key.gpg`.\n'
  } > "$release_notes"

  if gh release view "$tag_name" --repo Bali0531-RC/plexinstaller >/dev/null 2>&1; then
    gh release edit "$tag_name" --repo Bali0531-RC/plexinstaller --title "$NEW_VERSION" --notes-file "$release_notes"
  else
    gh release create "$tag_name" \
      --repo Bali0531-RC/plexinstaller \
      --verify-tag \
      --title "$NEW_VERSION" \
      --notes-file "$release_notes"
  fi
  gh release upload "$tag_name" \
    "$VERSION_FILE" "$SCRIPT_DIR/version.json.sig" "$SCRIPT_DIR/release-key.gpg" \
    --repo Bali0531-RC/plexinstaller \
    --clobber
  rm -f "$release_notes"
  trap - EXIT
}

if [ "$PUBLISH_CURRENT" = true ]; then
  python3 - "$SCRIPT_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "version.json").read_text())
files = {
    "installer": "installer.py", "config": "config.py", "utils": "utils.py",
    "plex_cli": "plex_cli.py", "telemetry_client": "telemetry_client.py",
    "addon_manager": "addon_manager.py", "shared": "shared.py",
    "health_checker": "health_checker.py", "mongodb_manager": "mongodb_manager.py",
    "backup_manager": "backup_manager.py", "requirements": "requirements.txt",
}
for key, filename in files.items():
    if manifest["checksums"].get(key) != hashlib.sha256((root / filename).read_bytes()).hexdigest():
        raise SystemExit(f"Stale checksum for {filename}; prepare the release first")
PY
  VERIFY_HOME="$(mktemp -d)"
  trap 'rm -rf "$VERIFY_HOME"' EXIT
  chmod 700 "$VERIFY_HOME"
  GNUPGHOME="$VERIFY_HOME" gpg --batch --import "$SCRIPT_DIR/release-key.gpg" >/dev/null 2>&1
  GNUPGHOME="$VERIFY_HOME" gpg --batch --no-auto-key-retrieve --status-fd 1 \
    --verify "$SCRIPT_DIR/version.json.sig" "$VERSION_FILE" 2>/dev/null \
    | awk -v expected="$RELEASE_SIGNING_FINGERPRINT" \
      '$1 == "[GNUPG:]" && $2 == "VALIDSIG" && ($3 == expected || $NF == expected) { found=1 } END { exit !found }'
  rm -rf "$VERIFY_HOME"
  trap - EXIT
  publish_github_release "$NEW_VERSION"
  echo "Published current signed release $NEW_VERSION."
  exit 0
fi

sed -i "s/^INSTALLER_VERSION = \".*\"/INSTALLER_VERSION = \"$NEW_VERSION\"/" "$SCRIPT_DIR/installer.py"
sed -i "s/^version = \".*\"/version = \"$NEW_VERSION\"/" "$SCRIPT_DIR/pyproject.toml"
TODAY="$(date +%Y-%m-%d)"

CHANGELOG_JSON="$(printf '%s\n' "${CHANGELOG_ENTRIES[@]}" | jq -R . | jq -s .)"
CHECKSUMS_JSON="$(python3 - "$SCRIPT_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
files = {
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
print(json.dumps({key: hashlib.sha256((root / filename).read_bytes()).hexdigest() for key, filename in sorted(files.items())}))
PY
)"

jq --arg version "$NEW_VERSION" \
   --arg date "$TODAY" \
   --argjson changelog "$CHANGELOG_JSON" \
   --argjson checksums "$CHECKSUMS_JSON" \
   '.version = $version | .release_date = $date | .changelog = $changelog | .checksums = $checksums | del(.gpg_signature)' \
   "$VERSION_FILE" > "$VERSION_FILE.tmp"
mv "$VERSION_FILE.tmp" "$VERSION_FILE"

python3 - "$CHANGELOG_TS" "$NEW_VERSION" "$TODAY" "$CHANGELOG_JSON" <<'PY'
import json
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
version = sys.argv[2]
date = sys.argv[3]
highlights = json.loads(sys.argv[4])
content = path.read_text()
lines = [f'      {json.dumps(item, ensure_ascii=False)},' for item in highlights]
entry = (
    "  {\n"
    f'    version: {json.dumps(version)},\n'
    f'    date: {json.dumps(date)},\n'
    "    highlights: [\n"
    + "\n".join(lines)
    + "\n    ]\n"
    "  },"
)
pattern = re.compile(r'  \{\n    version: "' + re.escape(version) + r'",.*?\n  \},', re.DOTALL)
if pattern.search(content):
    content = pattern.sub(entry, content, count=1)
else:
    marker = "export const releases: ReleaseNote[] = ["
    position = content.find(marker)
    if position < 0:
        raise SystemExit("Could not locate releases array")
    insert_at = position + len(marker)
    content = content[:insert_at] + "\n" + entry + content[insert_at:]
path.write_text(content)
PY

SIGNATURE_TMP="$(mktemp "$SCRIPT_DIR/.version.json.sig.XXXXXX")"
KEY_TMP="$(mktemp "$SCRIPT_DIR/.release-key.gpg.XXXXXX")"
cleanup_release_artifacts() {
  rm -f "$SIGNATURE_TMP" "$KEY_TMP"
}
trap cleanup_release_artifacts EXIT
gpg --batch --yes --detach-sign --armor --local-user "$RELEASE_SIGNING_FINGERPRINT" \
  --output "$SIGNATURE_TMP" "$VERSION_FILE"
gpg --batch --yes --armor --export "$RELEASE_SIGNING_FINGERPRINT" > "$KEY_TMP"
test -s "$SIGNATURE_TMP"
test -s "$KEY_TMP"
mv "$SIGNATURE_TMP" "$SCRIPT_DIR/version.json.sig"
mv "$KEY_TMP" "$SCRIPT_DIR/release-key.gpg"
trap - EXIT

python3 - "$SCRIPT_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "version.json").read_text())
files = {
    "installer": "installer.py", "config": "config.py", "utils": "utils.py",
    "plex_cli": "plex_cli.py", "telemetry_client": "telemetry_client.py",
    "addon_manager": "addon_manager.py", "shared": "shared.py",
    "health_checker": "health_checker.py", "mongodb_manager": "mongodb_manager.py",
    "backup_manager": "backup_manager.py", "requirements": "requirements.txt",
}
for key, filename in files.items():
    actual = hashlib.sha256((root / filename).read_bytes()).hexdigest()
    if manifest["checksums"].get(key) != actual:
        raise SystemExit(f"Stale checksum for {filename}")
PY

VERIFY_HOME="$(mktemp -d)"
trap 'rm -rf "$VERIFY_HOME"' EXIT
chmod 700 "$VERIFY_HOME"
GNUPGHOME="$VERIFY_HOME" gpg --batch --import "$SCRIPT_DIR/release-key.gpg" >/dev/null 2>&1
GNUPGHOME="$VERIFY_HOME" gpg --batch --no-auto-key-retrieve --status-fd 1 \
  --verify "$SCRIPT_DIR/version.json.sig" "$VERSION_FILE" 2>/dev/null \
  | awk -v expected="$RELEASE_SIGNING_FINGERPRINT" '$1 == "[GNUPG:]" && $2 == "VALIDSIG" && ($3 == expected || $NF == expected) { found=1 } END { exit !found }'
rm -rf "$VERIFY_HOME"
trap - EXIT

echo "Prepared signed release v$NEW_VERSION ($TODAY)."
if [ "$PREPARE_ONLY" = true ]; then
  echo "Prepare-only mode: no commit or push performed."
  exit 0
fi

git -C "$SCRIPT_DIR" add version.json version.json.sig release-key.gpg installer.py pyproject.toml web2/src/data/changelog.ts
git -C "$SCRIPT_DIR" commit -S"$RELEASE_SIGNING_FINGERPRINT" -m "release: v$NEW_VERSION"

publish_github_release "$NEW_VERSION"

echo "Published signed tag and GitHub Release $NEW_VERSION."
