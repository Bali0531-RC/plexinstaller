"""Tests for shared.py — version comparison, GPG verification helpers, symlink management."""

import hashlib
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

import shared
from shared import (
    RELEASE_KEY_FINGERPRINT,
    UPDATE_FILE_MAP,
    _force_symlink,
    _replace_staged_files,
    _validate_download_url,
    download_missing_files,
    is_newer_version,
    perform_update,
    verify_gpg_signature,
)

# ---------------------------------------------------------------------------
# is_newer_version
# ---------------------------------------------------------------------------


class TestIsNewerVersion:
    def test_newer_major(self):
        assert is_newer_version("4.0.0", "3.1.17") is True

    def test_newer_minor(self):
        assert is_newer_version("3.2.0", "3.1.17") is True

    def test_newer_patch(self):
        assert is_newer_version("3.1.18", "3.1.17") is True

    def test_same_version(self):
        assert is_newer_version("3.1.17", "3.1.17") is False

    def test_older_version(self):
        assert is_newer_version("3.1.16", "3.1.17") is False

    def test_shorter_remote(self):
        assert is_newer_version("4.0", "3.1.17") is True

    def test_shorter_local(self):
        assert is_newer_version("3.1.17", "4.0") is False

    def test_equal_different_length(self):
        assert is_newer_version("3.1.0", "3.1") is False

    def test_garbage_returns_false(self):
        assert is_newer_version("abc", "3.1.17") is False

    def test_empty_returns_false(self):
        assert is_newer_version("", "") is False


# ---------------------------------------------------------------------------
# verify_gpg_signature
# ---------------------------------------------------------------------------


def _noop(*_a, **_kw):
    """Dummy printer callback."""


_PRINTER_KWARGS = dict(
    print_info=_noop,
    print_success=_noop,
    print_warning=_noop,
    print_error=_noop,
)


def _response(content: bytes, url: str = "https://example.com/file"):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    offset = 0

    def read(size: int = -1) -> bytes:
        nonlocal offset
        if size < 0:
            chunk = content[offset:]
            offset = len(content)
            return chunk
        chunk = content[offset : offset + size]
        offset += len(chunk)
        return chunk

    response.read.side_effect = read
    response.geturl.return_value = url
    return response


class TestVerifyGpgSignature:
    def test_signature_download_failure_fails_closed(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        key_output = f"pub:::::::::\nfpr:::::::::{RELEASE_KEY_FINGERPRINT}:\n"
        with (
            mock.patch(
                "shared.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=key_output, stderr=""),
            ),
            mock.patch("shared.urllib.request.urlopen", side_effect=OSError("offline")),
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False

    def test_missing_gpg_fails_closed(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        with mock.patch("shared.subprocess.run", side_effect=FileNotFoundError("gpg")):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False

    def test_wrong_bundled_fingerprint_is_rejected_before_download(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        key_output = "pub:::::::::\nfpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:\n"
        with (
            mock.patch(
                "shared.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=key_output, stderr=""),
            ),
            mock.patch("shared.urllib.request.urlopen") as urlopen,
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False
            urlopen.assert_not_called()

    def test_valid_signature_must_report_pinned_fingerprint(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        key_output = f"pub:::::::::\nfpr:::::::::{RELEASE_KEY_FINGERPRINT}:\n"
        valid_status = f"[GNUPG:] VALIDSIG {RELEASE_KEY_FINGERPRINT} 0 0 0 0 0 0 0 0 0 {RELEASE_KEY_FINGERPRINT}\n"

        def run(cmd, **_kwargs):
            if "--show-keys" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=key_output, stderr="")
            if "--verify" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout=valid_status, stderr="")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        with (
            mock.patch("shared.subprocess.run", side_effect=run),
            mock.patch("shared.urllib.request.urlopen", return_value=_response(b"sig")),
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is True


# ---------------------------------------------------------------------------
# _force_symlink
# ---------------------------------------------------------------------------


class TestForceSymlink:
    def test_creates_symlink(self, tmp_path: Path):
        target = tmp_path / "target.py"
        target.write_text("#!/usr/bin/env python3\n")
        link = tmp_path / "link"

        _force_symlink(link, target)

        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_replaces_existing_wrong_symlink(self, tmp_path: Path):
        target = tmp_path / "real_target.py"
        target.write_text("#!/usr/bin/env python3\n")

        old_target = tmp_path / "old_target.py"
        old_target.write_text("old\n")

        link = tmp_path / "link"
        link.symlink_to(old_target)

        _force_symlink(link, target)

        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_skips_when_already_correct(self, tmp_path: Path):
        target = tmp_path / "target.py"
        target.write_text("ok\n")

        link = tmp_path / "link"
        link.symlink_to(target)

        _force_symlink(link, target)  # should be a no-op
        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_noop_when_target_missing(self, tmp_path: Path):
        missing = tmp_path / "nonexistent"
        link = tmp_path / "link"

        _force_symlink(link, missing)
        assert not link.exists()


# ---------------------------------------------------------------------------
# download_missing_files
# ---------------------------------------------------------------------------


class TestDownloadMissingFiles:
    @staticmethod
    def _populate_except(install_dir: Path, missing: set[str]) -> None:
        for filename in set(UPDATE_FILE_MAP.values()) - missing:
            (install_dir / filename).write_text("present")

    def test_noop_when_all_files_present(self, tmp_path: Path):
        """No downloads when every managed file already exists."""
        for fn in [
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
        ]:
            (tmp_path / fn).write_text("")

        with mock.patch("shared.INSTALLER_DIR", tmp_path):
            with mock.patch("shared.urllib.request.urlopen") as m:
                download_missing_files(**_PRINTER_KWARGS)
                m.assert_not_called()

    def test_downloads_missing_file(self, tmp_path: Path):
        """Missing file is downloaded and written with checksum verification."""
        content = b"# utils code"
        checksum = hashlib.sha256(content).hexdigest()
        self._populate_except(tmp_path, {"utils.py"})

        version_data = {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {"utils": checksum},
        }

        manifest = json.dumps(version_data).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=[manifest, content]),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)

        assert (tmp_path / "utils.py").exists()
        assert (tmp_path / "utils.py").read_bytes() == content

    def test_skips_on_checksum_mismatch(self, tmp_path: Path):
        """File with bad checksum is not written."""
        content = b"# bad content"
        self._populate_except(tmp_path, {"utils.py"})

        version_data = {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {"utils": "0" * 64},
        }
        manifest = json.dumps(version_data).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=[manifest, content]),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)

        assert not (tmp_path / "utils.py").exists()

    def test_handles_network_error(self, tmp_path: Path):
        """Network failure when fetching version.json is handled gracefully."""
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=Exception("offline")),
        ):
            download_missing_files(**_PRINTER_KWARGS)  # should not raise

    def test_manifest_is_authenticated_before_repair_download(self, tmp_path: Path):
        self._populate_except(tmp_path, {"utils.py"})
        manifest = json.dumps(
            {
                "download_urls": {"utils": "https://example.com/utils.py"},
                "checksums": {"utils": "0" * 64},
            }
        ).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=manifest) as download,
            mock.patch("shared.verify_gpg_signature", return_value=False),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert download.call_count == 1
        assert not (tmp_path / "utils.py").exists()

    def test_all_missing_files_are_staged_before_replacement(self, tmp_path: Path):
        self._populate_except(tmp_path, {"config.py", "utils.py"})
        config = b"tampered"
        utils = b"utils"
        manifest = json.dumps(
            {
                "download_urls": {
                    "config": "https://example.com/config.py",
                    "utils": "https://example.com/utils.py",
                },
                "checksums": {
                    "config": "0" * 64,
                    "utils": hashlib.sha256(utils).hexdigest(),
                },
            }
        ).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=[manifest, config, utils]),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert not (tmp_path / "config.py").exists()
        assert not (tmp_path / "utils.py").exists()


# ---------------------------------------------------------------------------
# Additional is_newer_version cases
# ---------------------------------------------------------------------------


class TestIsNewerVersionExtra:
    def test_two_component_versions(self):
        assert is_newer_version("2.1", "2.0") is True

    def test_four_component_versions(self):
        assert is_newer_version("1.2.3.4", "1.2.3.3") is True

    def test_zero_versions(self):
        assert is_newer_version("0.0.1", "0.0.0") is True

    def test_single_component(self):
        assert is_newer_version("2", "1") is True

    def test_single_component_equal(self):
        assert is_newer_version("1", "1") is False

    def test_padding_works_correctly(self):
        """'3.1' and '3.1.0' should be equal."""
        assert is_newer_version("3.1", "3.1.0") is False
        assert is_newer_version("3.1.0", "3.1") is False


# ---------------------------------------------------------------------------
# Additional _force_symlink cases
# ---------------------------------------------------------------------------


class TestForceSymlinkExtra:
    def test_replaces_regular_file_with_symlink(self, tmp_path: Path):
        target = tmp_path / "target.py"
        target.write_text("code\n")

        link = tmp_path / "link"
        link.write_text("I'm a regular file, not a symlink")

        _force_symlink(link, target)

        assert link.is_symlink()
        assert link.resolve() == target.resolve()


# ---------------------------------------------------------------------------
# Additional download_missing_files cases
# ---------------------------------------------------------------------------


class TestDownloadMissingFilesExtra:
    def test_skips_file_without_download_url(self, tmp_path: Path):
        for fn in set(UPDATE_FILE_MAP.values()) - {"utils.py"}:
            (tmp_path / fn).write_text("")

        # version.json has no download URL for utils
        version_data = {
            "download_urls": {},
            "checksums": {"utils": "0" * 64},
        }
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=json.dumps(version_data).encode()),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)

        assert not (tmp_path / "utils.py").exists()

    def test_skips_file_without_checksum(self, tmp_path: Path):
        for fn in set(UPDATE_FILE_MAP.values()) - {"utils.py"}:
            (tmp_path / fn).write_text("")

        version_data = {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {},
        }

        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=json.dumps(version_data).encode()),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)

        assert not (tmp_path / "utils.py").exists()


class TestUrlPolicy:
    def test_https_is_allowed(self):
        assert _validate_download_url("https://example.com/file") == "https://example.com/file"

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/file",
            "file:///tmp/payload",
            "https://user:pass@example.com/file",
            "https://example.com/file#fragment",
        ],
    )
    def test_unsafe_urls_are_rejected(self, url):
        with pytest.raises(ValueError):
            _validate_download_url(url)

    def test_http_requires_explicit_test_opt_in(self):
        assert _validate_download_url("http://127.0.0.1/file", allow_insecure_urls=True)


class TestTransactionalReplacement:
    def test_replacement_failure_rolls_back_all_targets(self, tmp_path: Path):
        install_dir = tmp_path / "install"
        stage_dir = tmp_path / "stage"
        install_dir.mkdir()
        stage_dir.mkdir()
        (install_dir / "a.py").write_bytes(b"old-a")
        (install_dir / "b.py").write_bytes(b"old-b")
        (stage_dir / "a.py").write_bytes(b"new-a")
        (stage_dir / "b.py").write_bytes(b"new-b")
        real_replace = shared.os.replace
        target_b = install_dir / "b.py"

        def flaky_replace(source, target):
            if Path(source) == stage_dir / "b.py" and Path(target) == target_b:
                raise OSError("simulated activation failure")
            return real_replace(source, target)

        with mock.patch("shared.os.replace", side_effect=flaky_replace):
            with pytest.raises(OSError):
                _replace_staged_files(
                    {"a.py": stage_dir / "a.py", "b.py": stage_dir / "b.py"},
                    install_dir,
                )
        assert (install_dir / "a.py").read_bytes() == b"old-a"
        assert (install_dir / "b.py").read_bytes() == b"old-b"

    def test_perform_update_rejects_unauthenticated_manifest_object(self, tmp_path: Path):
        authenticated = {"download_urls": {}, "checksums": {}}
        supplied = {"download_urls": {"installer": "https://evil.test/payload"}, "checksums": {}}
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch("shared._download_bytes") as download,
        ):
            perform_update(supplied, json.dumps(authenticated).encode(), **_PRINTER_KWARGS)
        download.assert_not_called()
