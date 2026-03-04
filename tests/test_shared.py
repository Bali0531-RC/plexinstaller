"""Tests for shared.py — version comparison, GPG verification helpers, symlink management."""

import subprocess
from pathlib import Path
from unittest import mock

from shared import _force_symlink, download_missing_files, is_newer_version, verify_gpg_signature

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


class TestVerifyGpgSignature:
    def test_returns_true_when_sig_download_fails(self):
        """If the .sig can't be fetched we skip verification (backwards compat)."""
        with mock.patch("shared.urllib.request.urlopen", side_effect=Exception("no network")):
            assert verify_gpg_signature(b"{}", **_PRINTER_KWARGS) is True

    def test_returns_true_when_gpg_not_installed(self):
        """If gpg is missing we skip verification."""
        # First call: sig download succeeds, second: key download succeeds
        fake_resp = mock.MagicMock()
        fake_resp.__enter__ = mock.MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = mock.MagicMock(return_value=False)
        fake_resp.read.return_value = b"sig-bytes"

        with mock.patch("shared.urllib.request.urlopen", return_value=fake_resp):
            with mock.patch("shared.subprocess.run", side_effect=FileNotFoundError("gpg")):
                with mock.patch("shared.os.write"):
                    with mock.patch("shared.os.close"):
                        with mock.patch("shared.os.unlink"):
                            assert verify_gpg_signature(b"{}", **_PRINTER_KWARGS) is True

    def test_returns_false_on_bad_signature(self):
        """gpg --verify returns non-zero → verification fails."""
        fake_resp = mock.MagicMock()
        fake_resp.__enter__ = mock.MagicMock(return_value=fake_resp)
        fake_resp.__exit__ = mock.MagicMock(return_value=False)
        fake_resp.read.return_value = b"sig-bytes"

        bad_result = subprocess.CompletedProcess(args=[], returncode=1, stderr="BAD SIG")

        def _mock_run(cmd, **kw):
            if cmd[0] == 'gpg' and '--verify' in cmd:
                return bad_result
            return subprocess.CompletedProcess(args=cmd, returncode=0)

        with mock.patch("shared.urllib.request.urlopen", return_value=fake_resp):
            with mock.patch("shared.subprocess.run", side_effect=_mock_run):
                with mock.patch("shared.os.write"):
                    with mock.patch("shared.os.close"):
                        with mock.patch("shared.os.unlink"):
                            assert verify_gpg_signature(b"{}", **_PRINTER_KWARGS) is False


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
    def _make_version_data(self):
        return {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {"utils": "abc123"},
        }

    def test_noop_when_all_files_present(self, tmp_path: Path):
        """No downloads when every managed file already exists."""
        for fn in ['installer.py', 'config.py', 'utils.py', 'plex_cli.py',
                    'telemetry_client.py', 'addon_manager.py', 'shared.py',
                    'health_checker.py', 'mongodb_manager.py', 'backup_manager.py']:
            (tmp_path / fn).write_text("")

        with mock.patch("shared.INSTALLER_DIR", tmp_path):
            with mock.patch("shared.urllib.request.urlopen") as m:
                download_missing_files(**_PRINTER_KWARGS)
                m.assert_not_called()

    def test_downloads_missing_file(self, tmp_path: Path):
        """Missing file is downloaded and written with checksum verification."""
        import hashlib
        content = b"# utils code"
        checksum = hashlib.sha256(content).hexdigest()

        # Create all files except utils.py
        from shared import UPDATE_FILE_MAP
        for fn in set(UPDATE_FILE_MAP.values()) - {"utils.py"}:
            (tmp_path / fn).write_text("")

        version_data = {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {"utils": checksum},
        }

        def fake_urlopen(url, **kw):
            resp = mock.MagicMock()
            resp.__enter__ = mock.MagicMock(return_value=resp)
            resp.__exit__ = mock.MagicMock(return_value=False)
            resp.read.return_value = (
                json.dumps(version_data).encode()
                if "version.json" in url else content
            )
            return resp

        import json
        with mock.patch("shared.INSTALLER_DIR", tmp_path):
            with mock.patch("shared.urllib.request.urlopen", side_effect=fake_urlopen):
                download_missing_files(**_PRINTER_KWARGS)

        assert (tmp_path / "utils.py").exists()
        assert (tmp_path / "utils.py").read_bytes() == content

    def test_skips_on_checksum_mismatch(self, tmp_path: Path):
        """File with bad checksum is not written."""
        content = b"# bad content"

        from shared import UPDATE_FILE_MAP
        for fn in set(UPDATE_FILE_MAP.values()) - {"utils.py"}:
            (tmp_path / fn).write_text("")

        version_data = {
            "download_urls": {"utils": "https://example.com/utils.py"},
            "checksums": {"utils": "wrong_checksum"},
        }

        def fake_urlopen(url, **kw):
            resp = mock.MagicMock()
            resp.__enter__ = mock.MagicMock(return_value=resp)
            resp.__exit__ = mock.MagicMock(return_value=False)
            resp.read.return_value = (
                json.dumps(version_data).encode()
                if "version.json" in url else content
            )
            return resp

        import json
        with mock.patch("shared.INSTALLER_DIR", tmp_path):
            with mock.patch("shared.urllib.request.urlopen", side_effect=fake_urlopen):
                download_missing_files(**_PRINTER_KWARGS)

        assert not (tmp_path / "utils.py").exists()

    def test_handles_network_error(self, tmp_path: Path):
        """Network failure when fetching version.json is handled gracefully."""
        with mock.patch("shared.INSTALLER_DIR", tmp_path):
            with mock.patch("shared.urllib.request.urlopen", side_effect=Exception("offline")):
                download_missing_files(**_PRINTER_KWARGS)  # should not raise
