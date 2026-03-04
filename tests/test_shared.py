"""Tests for shared.py — version comparison, GPG verification helpers, symlink management."""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from shared import is_newer_version, verify_gpg_signature, _force_symlink


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
