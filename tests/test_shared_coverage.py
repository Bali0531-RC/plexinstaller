"""Additional coverage tests for shared.py."""

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
    _download_bytes,
    _force_symlink,
    _parse_manifest,
    _remove_path,
    _replace_staged_files,
    _validate_download_url,
    _validated_download_specs,
    _write_entrypoint,
    ensure_cli_entrypoints,
    perform_update,
    verify_gpg_signature,
)


def _noop(*_a, **_kw):
    pass


_PRINTERS = dict(
    print_info=_noop,
    print_success=_noop,
    print_warning=_noop,
    print_error=_noop,
)


def _response(content: bytes, url: str = "https://example.com/f", max_read_size: int | None = None):
    response = mock.MagicMock()
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    response.geturl.return_value = url
    offset = 0

    def read(n: int = -1) -> bytes:
        nonlocal offset
        if offset >= len(content):
            return b""
        requested = len(content) - offset if n < 0 else n
        if max_read_size is not None:
            requested = min(requested, max_read_size)
        chunk = content[offset : offset + requested]
        offset += len(chunk)
        return chunk

    response.read.side_effect = read
    return response


# ---------------------------------------------------------------------------
# _validate_download_url
# ---------------------------------------------------------------------------


class TestValidateDownloadUrl:
    def test_non_string_rejected(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_download_url(None)

    def test_empty_rejected(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_download_url("")

    def test_http_rejected_by_default(self):
        with pytest.raises(ValueError, match="scheme"):
            _validate_download_url("http://example.com/x")

    def test_http_allowed_with_flag(self):
        assert _validate_download_url("http://example.com/x", allow_insecure_urls=True)

    def test_ftp_rejected_even_insecure(self):
        with pytest.raises(ValueError, match="scheme"):
            _validate_download_url("ftp://example.com/x", allow_insecure_urls=True)

    def test_credentials_rejected(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _validate_download_url("https://user:pass@example.com/x")

    def test_fragment_rejected(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _validate_download_url("https://example.com/x#frag")

    def test_missing_host_rejected(self):
        with pytest.raises(ValueError, match="Unsafe"):
            _validate_download_url("https:///x")


# ---------------------------------------------------------------------------
# _download_bytes
# ---------------------------------------------------------------------------


class TestDownloadBytes:
    def test_returns_content(self):
        with mock.patch("shared.urllib.request.urlopen", return_value=_response(b"hello")):
            assert _download_bytes("https://example.com/f", timeout=5, max_bytes=100) == b"hello"

    def test_oversized_download_rejected(self):
        with mock.patch("shared.urllib.request.urlopen", return_value=_response(b"x" * 11)):
            with pytest.raises(ValueError, match="size limit"):
                _download_bytes("https://example.com/f", timeout=5, max_bytes=10)

    def test_short_reads_cannot_hide_oversized_download(self):
        response = _response(b"x" * 11, max_read_size=3)
        with mock.patch("shared.urllib.request.urlopen", return_value=response):
            with pytest.raises(ValueError, match="size limit"):
                _download_bytes("https://example.com/f", timeout=5, max_bytes=10)
        assert response.read.call_count > 1

    def test_insecure_redirect_rejected(self):
        resp = _response(b"data", url="http://evil.example/f")
        with mock.patch("shared.urllib.request.urlopen", return_value=resp):
            with pytest.raises(ValueError, match="scheme"):
                _download_bytes("https://example.com/f", timeout=5, max_bytes=100)


# ---------------------------------------------------------------------------
# _parse_manifest / _validated_download_specs
# ---------------------------------------------------------------------------


class TestParseManifest:
    def test_invalid_json(self):
        with pytest.raises(ValueError, match="Invalid version manifest"):
            _parse_manifest(b"{bad json")

    def test_invalid_utf8(self):
        with pytest.raises(ValueError, match="Invalid version manifest"):
            _parse_manifest(b"\xff\xfe\x00bad")

    def test_non_object(self):
        with pytest.raises(ValueError, match="JSON object"):
            _parse_manifest(b"[1, 2]")

    def test_valid(self):
        assert _parse_manifest(b'{"version": "1.0"}') == {"version": "1.0"}


class TestValidatedDownloadSpecs:
    def test_missing_maps_rejected(self):
        with pytest.raises(ValueError, match="must be objects"):
            _validated_download_specs({}, {"installer": "installer.py"})

    def test_missing_url_rejected(self):
        data = {"download_urls": {}, "checksums": {}}
        with pytest.raises(ValueError, match="No download URL"):
            _validated_download_specs(data, {"installer": "installer.py"})

    def test_bad_checksum_rejected(self):
        data = {
            "download_urls": {"installer": "https://example.com/i.py"},
            "checksums": {"installer": "nothex"},
        }
        with pytest.raises(ValueError, match="SHA-256"):
            _validated_download_specs(data, {"installer": "installer.py"})

    def test_valid_spec_lowercased(self):
        digest = "A" * 64
        data = {
            "download_urls": {"installer": "https://example.com/i.py"},
            "checksums": {"installer": digest},
        }
        specs = _validated_download_specs(data, {"installer": "installer.py"})
        assert specs["installer"] == ("https://example.com/i.py", "a" * 64)


# ---------------------------------------------------------------------------
# _remove_path / _replace_staged_files
# ---------------------------------------------------------------------------


class TestRemovePath:
    def test_removes_directory(self, tmp_path: Path):
        d = tmp_path / "dir"
        d.mkdir()
        (d / "f").write_text("x")
        _remove_path(d)
        assert not d.exists()

    def test_removes_file(self, tmp_path: Path):
        f = tmp_path / "f"
        f.write_text("x")
        _remove_path(f)
        assert not f.exists()

    def test_removes_symlink(self, tmp_path: Path):
        target = tmp_path / "t"
        target.write_text("x")
        link = tmp_path / "l"
        link.symlink_to(target)
        _remove_path(link)
        assert not link.is_symlink()

    def test_missing_path_noop(self, tmp_path: Path):
        _remove_path(tmp_path / "nope")


class TestReplaceStagedFiles:
    def test_rollback_error_reported(self, tmp_path: Path):
        install = tmp_path / "install"
        install.mkdir()
        (install / "a.py").write_text("old a")
        stage = tmp_path / "stage"
        stage.mkdir()
        (stage / "a.py").write_text("new a")
        (stage / "b.py").write_text("new b")

        original_replace = shared.os.replace
        state = {"published": 0}

        def flaky_replace(src, dst):
            src_s = str(src)
            if src_s.startswith(str(stage)):
                state["published"] += 1
                if state["published"] == 2:
                    raise OSError("simulated publish failure")
            elif ".update-rollback-" in src_s:
                raise OSError("rollback also failed")
            return original_replace(src, dst)

        with mock.patch("shared.os.replace", side_effect=flaky_replace):
            with pytest.raises(RuntimeError, match="rollback was incomplete"):
                _replace_staged_files({"a.py": stage / "a.py", "b.py": stage / "b.py"}, install)


# ---------------------------------------------------------------------------
# verify_gpg_signature failure paths
# ---------------------------------------------------------------------------


class TestVerifyGpgSignature:
    def test_missing_release_key(self, tmp_path: Path):
        errors = []
        ok = verify_gpg_signature(
            b"{}",
            print_info=_noop,
            print_success=_noop,
            print_warning=_noop,
            print_error=errors.append,
            key_path=tmp_path / "missing.gpg",
        )
        assert ok is False
        assert "not found" in errors[0]

    def test_fingerprint_mismatch(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")
        colon = "pub:u:...\nfpr:::::::::DEADBEEF:\n"
        with mock.patch(
            "shared.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, stdout=colon, stderr=""),
        ):
            errors = []
            ok = verify_gpg_signature(
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
                key_path=key,
            )
        assert ok is False
        assert "fingerprint mismatch" in errors[0]

    def _good_key_result(self):
        colon = f"pub:u:...\nfpr:::::::::{RELEASE_KEY_FINGERPRINT}:\n"
        return subprocess.CompletedProcess([], 0, stdout=colon, stderr="")

    def test_import_failure(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")

        def fake_run(cmd, **kwargs):
            if "--show-keys" in cmd:
                return self._good_key_result()
            if "--import" in cmd:
                return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="import broke")
            raise AssertionError("unexpected gpg call")

        with (
            mock.patch("shared.subprocess.run", side_effect=fake_run),
            mock.patch("shared._download_bytes", return_value=b"sig"),
        ):
            errors = []
            ok = verify_gpg_signature(
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
                key_path=key,
            )
        assert ok is False
        assert "import" in errors[0]

    def test_verify_wrong_signer(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")

        def fake_run(cmd, **kwargs):
            if "--show-keys" in cmd:
                return self._good_key_result()
            if "--import" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "--verify" in cmd:
                stdout = "[GNUPG:] VALIDSIG " + "F" * 40 + "\n"
                return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
            raise AssertionError("unexpected gpg call")

        with (
            mock.patch("shared.subprocess.run", side_effect=fake_run),
            mock.patch("shared._download_bytes", return_value=b"sig"),
        ):
            errors = []
            ok = verify_gpg_signature(
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
                key_path=key,
            )
        assert ok is False
        assert "verification failed" in errors[0]

    def test_valid_signature_passes(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")

        def fake_run(cmd, **kwargs):
            if "--show-keys" in cmd:
                return self._good_key_result()
            if "--import" in cmd:
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
            if "--verify" in cmd:
                stdout = f"[GNUPG:] VALIDSIG {RELEASE_KEY_FINGERPRINT}\n"
                return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
            raise AssertionError("unexpected gpg call")

        with (
            mock.patch("shared.subprocess.run", side_effect=fake_run),
            mock.patch("shared._download_bytes", return_value=b"sig"),
        ):
            ok = verify_gpg_signature(b"{}", key_path=key, **_PRINTERS)
        assert ok is True

    def test_gpg_missing(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")
        with mock.patch("shared.subprocess.run", side_effect=FileNotFoundError("gpg")):
            errors = []
            ok = verify_gpg_signature(
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
                key_path=key,
            )
        assert ok is False
        assert "gpg is required" in errors[0]

    def test_unexpected_exception(self, tmp_path: Path):
        key = tmp_path / "key.gpg"
        key.write_bytes(b"key material")
        with mock.patch("shared.subprocess.run", side_effect=RuntimeError("boom")):
            errors = []
            ok = verify_gpg_signature(
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
                key_path=key,
            )
        assert ok is False
        assert "boom" in errors[0]


# ---------------------------------------------------------------------------
# ensure_cli_entrypoints / _write_entrypoint / _force_symlink
# ---------------------------------------------------------------------------


class TestEnsureCliEntrypoints:
    def test_non_root_is_noop(self):
        with mock.patch("shared.os.geteuid", return_value=1000), mock.patch("shared._write_entrypoint") as we:
            ensure_cli_entrypoints()
        we.assert_not_called()

    def test_root_writes_both_entrypoints(self, tmp_path: Path):
        bin_dir = tmp_path / "bin"

        def fake_path(p):
            assert p == "/usr/local/bin"
            return bin_dir

        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.Path", side_effect=fake_path),
            mock.patch("shared._write_entrypoint") as we,
        ):
            ensure_cli_entrypoints()
        assert we.call_count == 2
        assert bin_dir.exists()

    def test_exceptions_swallowed(self):
        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.Path", side_effect=RuntimeError("no fs")),
        ):
            ensure_cli_entrypoints()  # must not raise


class TestWriteEntrypoint:
    def test_missing_script_is_noop(self, tmp_path: Path):
        entry = tmp_path / "plex"
        _write_entrypoint(entry, tmp_path / "missing.py")
        assert not entry.exists()

    def test_creates_executable_wrapper(self, tmp_path: Path):
        script = tmp_path / "cli.py"
        script.write_text("print('hi')")
        entry = tmp_path / "plex"
        _write_entrypoint(entry, script)
        assert entry.exists()
        assert entry.stat().st_mode & 0o777 == 0o755
        content = entry.read_text()
        assert "#!/bin/sh" in content
        assert str(script) in content

    def test_replaces_existing_entrypoint(self, tmp_path: Path):
        script = tmp_path / "cli.py"
        script.write_text("x")
        entry = tmp_path / "plex"
        entry.write_text("old")
        _write_entrypoint(entry, script)
        assert "exec" in entry.read_text()


class TestForceSymlink:
    def test_missing_target_noop(self, tmp_path: Path):
        link = tmp_path / "link"
        _force_symlink(link, tmp_path / "missing")
        assert not link.exists()

    def test_creates_symlink(self, tmp_path: Path):
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / "link"
        _force_symlink(link, target)
        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_correct_existing_symlink_kept(self, tmp_path: Path):
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / "link"
        link.symlink_to(target)
        _force_symlink(link, target)
        assert link.resolve() == target.resolve()

    def test_replaces_wrong_symlink(self, tmp_path: Path):
        target = tmp_path / "target"
        target.write_text("x")
        other = tmp_path / "other"
        other.write_text("y")
        link = tmp_path / "link"
        link.symlink_to(other)
        _force_symlink(link, target)
        assert link.resolve() == target.resolve()

    def test_replaces_regular_file(self, tmp_path: Path):
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / "link"
        link.write_text("plain file")
        _force_symlink(link, target)
        assert link.is_symlink()

    def test_typeerror_fallback(self, tmp_path: Path):
        target = tmp_path / "target"
        target.write_text("x")
        link = tmp_path / "link"
        link.write_text("plain")

        original_unlink = Path.unlink
        state = {"raised": False}

        def unlink(self, missing_ok=False):
            if missing_ok and not state["raised"]:
                state["raised"] = True
                raise TypeError("missing_ok unsupported")
            return original_unlink(self)

        with mock.patch.object(Path, "unlink", unlink):
            _force_symlink(link, target)
        assert link.is_symlink()


# ---------------------------------------------------------------------------
# perform_update
# ---------------------------------------------------------------------------


def _manifest_for(contents: dict[str, bytes], base_url: str = "https://example.com") -> dict:
    urls = {}
    checksums = {}
    for key, filename in UPDATE_FILE_MAP.items():
        content = contents[filename]
        urls[key] = f"{base_url}/{filename}"
        checksums[key] = hashlib.sha256(content).hexdigest()
    return {"version": "9.9.9", "download_urls": urls, "checksums": checksums}


class TestPerformUpdate:
    def test_non_root_warns(self):
        warnings = []
        with mock.patch("shared.os.geteuid", return_value=1000):
            perform_update(
                {},
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=warnings.append,
                print_error=_noop,
            )
        assert "requires root" in warnings[0]

    def test_gpg_failure_aborts(self):
        errors = []
        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=False),
        ):
            perform_update(
                {},
                b"{}",
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
            )
        assert any("aborted" in e for e in errors)

    def test_manifest_mismatch_fails(self):
        errors = []
        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            perform_update(
                {"version": "other"},
                b'{"version": "1.0"}',
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
            )
        assert any("preserved" in e for e in errors)

    def test_successful_update_installs_and_restarts(self, tmp_path: Path):
        contents = {filename: f"# {filename}\n".encode() for filename in UPDATE_FILE_MAP.values()}
        manifest = _manifest_for(contents)
        manifest_bytes = json.dumps(manifest).encode()

        def fake_download(url, **kwargs):
            return contents[url.rsplit("/", 1)[1]]

        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch.object(shared, "INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=fake_download),
            mock.patch("shared.ensure_cli_entrypoints") as entry,
            mock.patch("shared.os.execv") as execv,
        ):
            perform_update(manifest, manifest_bytes, **_PRINTERS)

        entry.assert_called_once()
        execv.assert_called_once()
        for filename in UPDATE_FILE_MAP.values():
            assert (tmp_path / filename).read_bytes() == contents[filename]
        assert (tmp_path / "installer.py").stat().st_mode & 0o777 == 0o755
        assert (tmp_path / "utils.py").stat().st_mode & 0o777 == 0o644

    def test_checksum_mismatch_preserves_install(self, tmp_path: Path):
        contents = {filename: f"# {filename}\n".encode() for filename in UPDATE_FILE_MAP.values()}
        manifest = _manifest_for(contents)
        manifest_bytes = json.dumps(manifest).encode()
        (tmp_path / "installer.py").write_text("original")

        errors = []
        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch.object(shared, "INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=b"tampered content"),
            mock.patch("shared.os.execv") as execv,
        ):
            perform_update(
                manifest,
                manifest_bytes,
                print_info=_noop,
                print_success=_noop,
                print_warning=_noop,
                print_error=errors.append,
            )

        execv.assert_not_called()
        assert any("Checksum mismatch" in e for e in errors)
        assert (tmp_path / "installer.py").read_text() == "original"

    def test_restart_failure_warns(self, tmp_path: Path):
        contents = {filename: b"x" for filename in UPDATE_FILE_MAP.values()}
        manifest = _manifest_for(contents)
        manifest_bytes = json.dumps(manifest).encode()

        warnings = []
        with (
            mock.patch("shared.os.geteuid", return_value=0),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch.object(shared, "INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=b"x"),
            mock.patch("shared.ensure_cli_entrypoints"),
            mock.patch("shared.os.execv", side_effect=OSError("cannot exec")),
        ):
            perform_update(
                manifest,
                manifest_bytes,
                print_info=_noop,
                print_success=_noop,
                print_warning=warnings.append,
                print_error=_noop,
            )
        assert any("restart failed" in w for w in warnings)
