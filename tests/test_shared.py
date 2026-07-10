"""Focused tests for the Windows shared update and entrypoint helpers."""

import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

import shared
from shared import (
    RELEASE_KEY_FINGERPRINT,
    RELEASE_KEY_URL,
    UPDATE_BRANCH,
    UPDATE_FILE_MAP,
    VERSION_CHECK_URL,
    VERSION_SIGNATURE_URL,
    _add_to_system_path,
    _create_cmd_wrapper,
    _download_bytes,
    _replace_staged_files,
    _validate_download_url,
    download_missing_files,
    is_newer_version,
    perform_update,
    verify_gpg_signature,
)


class StreamResponse:
    """A context-managed response whose reads consume bytes like a real stream."""

    def __init__(self, content: bytes, url: str, *, content_length: int | None = None) -> None:
        self._content = content
        self._offset = 0
        self._url = url
        self.read_sizes: list[int] = []
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if size < 0:
            chunk = self._content[self._offset :]
            self._offset = len(self._content)
            return chunk
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _noop(*_args, **_kwargs) -> None:
    return None


_PRINTER_KWARGS = {
    "print_info": _noop,
    "print_success": _noop,
    "print_warning": _noop,
    "print_error": _noop,
}


def _branch_url(filename: str) -> str:
    return f"https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/{UPDATE_BRANCH}/{filename}"


def _manifest(files: dict[str, bytes]) -> tuple[dict, bytes]:
    data = {
        "download_urls": {key: _branch_url(UPDATE_FILE_MAP[key]) for key in files},
        "checksums": {key: hashlib.sha256(content).hexdigest() for key, content in files.items()},
    }
    return data, json.dumps(data, sort_keys=True).encode()


def _populate_except(install_dir: Path, missing: set[str]) -> None:
    for filename in set(UPDATE_FILE_MAP.values()) - missing:
        (install_dir / filename).write_bytes(b"present")


def test_channel_constants_never_target_main_or_dev():
    assert UPDATE_BRANCH == "windows-experimental"
    for url in (VERSION_CHECK_URL, VERSION_SIGNATURE_URL, RELEASE_KEY_URL):
        assert "/windows-experimental/" in url
        assert "/main/" not in url
        assert "/dev/" not in url
    assert RELEASE_KEY_FINGERPRINT == "431E869D5BB519AFF7B028379B0DFA4BF86307BD"


@pytest.mark.parametrize(
    "url",
    [
        "http://raw.githubusercontent.com/Bali0531-RC/plexinstaller/windows-experimental/file.py",
        "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/main/file.py",
        "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/dev/file.py",
        "https://github.com/Bali0531-RC/plexinstaller/windows-experimental/file.py",
        "https://user:pass@raw.githubusercontent.com/Bali0531-RC/plexinstaller/windows-experimental/file.py",
        "https://raw.githubusercontent.com/Bali0531-RC/plexinstaller/windows-experimental/file.py#fragment",
        "file:///tmp/file.py",
    ],
)
def test_url_policy_rejects_non_channel_or_unsafe_urls(url: str):
    with pytest.raises(ValueError):
        _validate_download_url(url)


def test_url_policy_accepts_only_pinned_channel_https():
    url = _branch_url("shared.py")
    assert _validate_download_url(url) == url


def test_download_is_chunked_and_bounded():
    content = b"x" * 150_000
    response = StreamResponse(content, _branch_url("shared.py"), content_length=len(content))
    with mock.patch("shared.urllib.request.urlopen", return_value=response):
        assert _download_bytes(_branch_url("shared.py"), timeout=1, max_bytes=len(content)) == content
    assert response.read_sizes
    assert -1 not in response.read_sizes
    assert max(response.read_sizes) <= 64 * 1024


def test_download_rejects_short_read():
    response = StreamResponse(b"short", _branch_url("shared.py"), content_length=100)
    with mock.patch("shared.urllib.request.urlopen", return_value=response):
        with pytest.raises(ValueError, match="Incomplete download"):
            _download_bytes(_branch_url("shared.py"), timeout=1, max_bytes=100)


def test_download_rejects_oversize_response():
    response = StreamResponse(b"12345", _branch_url("shared.py"))
    with mock.patch("shared.urllib.request.urlopen", return_value=response):
        with pytest.raises(ValueError, match="size limit"):
            _download_bytes(_branch_url("shared.py"), timeout=1, max_bytes=4)


class TestVerifyGpgSignature:
    def test_missing_gpg_fails_closed(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        with mock.patch("shared.shutil.which", return_value=None):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False

    def test_signature_download_failure_fails_closed(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        with (
            mock.patch("shared.shutil.which", return_value="gpg"),
            mock.patch("shared._download_bytes", side_effect=OSError("offline")),
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False

    def test_downloaded_key_failure_fails_closed(self, tmp_path: Path):
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path / "missing"),
            mock.patch("shared.__file__", str(tmp_path / "shared.py")),
            mock.patch("shared.shutil.which", return_value="gpg"),
            mock.patch("shared._download_bytes", side_effect=OSError("key unavailable")) as download,
        ):
            assert verify_gpg_signature(b"{}", **_PRINTER_KWARGS) is False
        assert download.call_args.args[0] == RELEASE_KEY_URL

    def test_wrong_key_fingerprint_fails_before_import(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        wrong = "pub:::::::::\nfpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:\n"
        with (
            mock.patch("shared.shutil.which", return_value="gpg"),
            mock.patch("shared._download_bytes", return_value=b"signature"),
            mock.patch("shared._make_path_private"),
            mock.patch(
                "shared.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=wrong, stderr=""),
            ) as run,
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False
        assert run.call_count == 1

    def test_requires_validsig_for_pinned_fingerprint_and_isolates_home(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        key_output = f"pub:::::::::\nfpr:::::::::{RELEASE_KEY_FINGERPRINT}:\n"
        valid_status = f"[GNUPG:] VALIDSIG {RELEASE_KEY_FINGERPRINT} 0 0 0 0 0 0 0 0 0 {RELEASE_KEY_FINGERPRINT}\n"
        calls: list[tuple[list[str], dict]] = []

        def run(command, **kwargs):
            calls.append((command, kwargs))
            if "--show-keys" in command:
                return subprocess.CompletedProcess(command, 0, stdout=key_output, stderr="")
            if "--verify" in command:
                return subprocess.CompletedProcess(command, 0, stdout=valid_status, stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with (
            mock.patch("shared.shutil.which", return_value="gpg"),
            mock.patch("shared._download_bytes", return_value=b"signature"),
            mock.patch("shared._make_path_private"),
            mock.patch("shared.subprocess.run", side_effect=run),
        ):
            assert verify_gpg_signature(b'{"version":"1"}', key_path=key, **_PRINTER_KWARGS) is True

        assert len(calls) == 3
        for command, kwargs in calls:
            assert "--homedir" in command
            assert "--no-options" in command
            assert kwargs["env"]["GNUPGHOME"] == command[command.index("--homedir") + 1]
        verify_command = calls[-1][0]
        assert verify_command[verify_command.index("--status-fd") + 1] == "1"
        assert "--no-auto-key-retrieve" in verify_command

    def test_zero_exit_without_validsig_fails_closed(self, tmp_path: Path):
        key = tmp_path / "release-key.gpg"
        key.write_bytes(b"key")
        key_output = f"pub:::::::::\nfpr:::::::::{RELEASE_KEY_FINGERPRINT}:\n"

        def run(command, **_kwargs):
            stdout = key_output if "--show-keys" in command else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with (
            mock.patch("shared.shutil.which", return_value="gpg"),
            mock.patch("shared._download_bytes", return_value=b"signature"),
            mock.patch("shared._make_path_private"),
            mock.patch("shared.subprocess.run", side_effect=run),
        ):
            assert verify_gpg_signature(b"{}", key_path=key, **_PRINTER_KWARGS) is False


class TestDownloadMissingFiles:
    def test_manifest_is_authenticated_before_file_urls_are_used(self, tmp_path: Path):
        _populate_except(tmp_path, {"utils.py"})
        _, manifest_bytes = _manifest({"utils": b"new-utils"})
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=manifest_bytes) as download,
            mock.patch("shared.verify_gpg_signature", return_value=False),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert download.call_count == 1
        assert not (tmp_path / "utils.py").exists()

    @pytest.mark.parametrize("missing_field", ["download_urls", "checksums"])
    def test_requires_url_and_checksum_for_every_missing_file(self, tmp_path: Path, missing_field: str):
        _populate_except(tmp_path, {"utils.py"})
        data, _ = _manifest({"utils": b"new-utils"})
        data[missing_field].pop("utils")
        manifest_bytes = json.dumps(data).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=manifest_bytes) as download,
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert download.call_count == 1
        assert not (tmp_path / "utils.py").exists()

    def test_rejects_main_branch_file_url(self, tmp_path: Path):
        _populate_except(tmp_path, {"utils.py"})
        data, _ = _manifest({"utils": b"new-utils"})
        data["download_urls"]["utils"] = data["download_urls"]["utils"].replace("/windows-experimental/", "/main/")
        manifest_bytes = json.dumps(data).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", return_value=manifest_bytes) as download,
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert download.call_count == 1
        assert not (tmp_path / "utils.py").exists()

    def test_all_missing_files_are_staged_before_atomic_activation(self, tmp_path: Path):
        _populate_except(tmp_path, {"config.py", "utils.py"})
        config = b"new-config"
        utils = b"new-utils"
        data, _ = _manifest({"config": config, "utils": utils})
        data["checksums"]["config"] = "0" * 64
        manifest_bytes = json.dumps(data).encode()
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=[manifest_bytes, config, utils]),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert not (tmp_path / "config.py").exists()
        assert not (tmp_path / "utils.py").exists()

    def test_successfully_activates_verified_missing_files(self, tmp_path: Path):
        _populate_except(tmp_path, {"utils.py"})
        content = b"new-utils"
        _, manifest_bytes = _manifest({"utils": content})
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared._download_bytes", side_effect=[manifest_bytes, content]),
            mock.patch("shared.verify_gpg_signature", return_value=True),
        ):
            download_missing_files(**_PRINTER_KWARGS)
        assert (tmp_path / "utils.py").read_bytes() == content


class TestTransactionalReplacement:
    def test_failure_restores_existing_and_deletes_newly_created_files(self, tmp_path: Path):
        install_dir = tmp_path / "install"
        stage_dir = tmp_path / "stage"
        install_dir.mkdir()
        stage_dir.mkdir()
        (install_dir / "old.py").write_bytes(b"old")
        (install_dir / "last.py").write_bytes(b"last-old")
        (stage_dir / "old.py").write_bytes(b"new")
        (stage_dir / "created.py").write_bytes(b"created")
        (stage_dir / "last.py").write_bytes(b"last-new")
        real_replace = shared.os.replace

        def flaky_replace(source, target):
            if Path(source) == stage_dir / "last.py" and Path(target) == install_dir / "last.py":
                raise OSError("activation failed")
            return real_replace(source, target)

        with mock.patch("shared.os.replace", side_effect=flaky_replace):
            with pytest.raises(OSError, match="activation failed"):
                _replace_staged_files(
                    {
                        "old.py": stage_dir / "old.py",
                        "created.py": stage_dir / "created.py",
                        "last.py": stage_dir / "last.py",
                    },
                    install_dir,
                )

        assert (install_dir / "old.py").read_bytes() == b"old"
        assert (install_dir / "last.py").read_bytes() == b"last-old"
        assert not (install_dir / "created.py").exists()

    def test_perform_update_verifies_exact_manifest_bytes(self, tmp_path: Path):
        authenticated = {"download_urls": {}, "checksums": {}}
        supplied = {
            "download_urls": {"installer": _branch_url("installer.py")},
            "checksums": {"installer": "0" * 64},
        }
        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared.is_admin", return_value=True),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch("shared._download_bytes") as download,
        ):
            perform_update(supplied, json.dumps(authenticated).encode(), **_PRINTER_KWARGS)
        download.assert_not_called()

    def test_perform_update_download_failure_preserves_all_targets(self, tmp_path: Path):
        files = {key: f"new-{key}".encode() for key in UPDATE_FILE_MAP}
        data, manifest_bytes = _manifest(files)
        for filename in UPDATE_FILE_MAP.values():
            (tmp_path / filename).write_bytes(f"old-{filename}".encode())
        downloads = [files[key] for key in UPDATE_FILE_MAP]
        downloads[3] = b"tampered"

        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared.is_admin", return_value=True),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch("shared._download_bytes", side_effect=downloads),
            mock.patch("shared.ensure_cli_entrypoints") as wrappers,
            mock.patch("shared.subprocess.Popen") as restart,
        ):
            perform_update(data, manifest_bytes, **_PRINTER_KWARGS)

        for filename in UPDATE_FILE_MAP.values():
            assert (tmp_path / filename).read_bytes() == f"old-{filename}".encode()
        wrappers.assert_not_called()
        restart.assert_not_called()

    def test_perform_update_activates_then_restarts_with_windows_semantics(self, tmp_path: Path):
        files = {key: f"new-{key}".encode() for key in UPDATE_FILE_MAP}
        data, manifest_bytes = _manifest(files)
        for filename in UPDATE_FILE_MAP.values():
            (tmp_path / filename).write_bytes(f"old-{filename}".encode())

        with (
            mock.patch("shared.INSTALLER_DIR", tmp_path),
            mock.patch("shared.is_admin", return_value=True),
            mock.patch("shared.verify_gpg_signature", return_value=True),
            mock.patch("shared._download_bytes", side_effect=[files[key] for key in UPDATE_FILE_MAP]),
            mock.patch("shared.ensure_cli_entrypoints") as wrappers,
            mock.patch("shared.subprocess.Popen") as restart,
            mock.patch("shared.sys.exit", side_effect=SystemExit(0)) as exit_process,
        ):
            with pytest.raises(SystemExit):
                perform_update(data, manifest_bytes, **_PRINTER_KWARGS)

        for key, filename in UPDATE_FILE_MAP.items():
            assert (tmp_path / filename).read_bytes() == files[key]
        wrappers.assert_called_once_with()
        restart.assert_called_once_with([sys.executable, *sys.argv])
        exit_process.assert_called_once_with(0)


class TestWindowsEntrypoints:
    def test_cmd_wrapper_is_relative_and_atomic(self, tmp_path: Path):
        target = tmp_path / "installer.py"
        target.write_text("print('ok')")
        wrapper = tmp_path / "plexinstaller.cmd"
        replace = shared.os.replace

        with mock.patch("shared.os.replace", wraps=replace) as atomic_replace:
            _create_cmd_wrapper(wrapper, target)

        assert wrapper.read_bytes() == b'@echo off\r\npython "%~dp0installer.py" %*\r\n'
        assert atomic_replace.call_count == 1
        assert not list(tmp_path.glob(".plexinstaller.cmd.*"))

    def test_cmd_wrapper_preserves_existing_file_if_atomic_replace_fails(self, tmp_path: Path):
        target = tmp_path / "installer.py"
        target.write_text("print('ok')")
        wrapper = tmp_path / "plexinstaller.cmd"
        wrapper.write_bytes(b"old-wrapper")
        with mock.patch("shared.os.replace", side_effect=OSError("busy")):
            with pytest.raises(OSError):
                _create_cmd_wrapper(wrapper, target)
        assert wrapper.read_bytes() == b"old-wrapper"
        assert not list(tmp_path.glob(".plexinstaller.cmd.*"))

    def test_system_path_update_preserves_full_existing_value(self, tmp_path: Path, monkeypatch):
        existing = r"C:\Windows\System32;C:\Program Files\Tool;%SystemRoot%\System32"
        writes: list[tuple[str, str, int, str]] = []

        class FakeKey:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        fake_winreg = types.SimpleNamespace(
            KEY_READ=1,
            KEY_SET_VALUE=2,
            KEY_WOW64_64KEY=4,
            HKEY_LOCAL_MACHINE=object(),
            REG_SZ=1,
            REG_EXPAND_SZ=2,
            OpenKey=lambda *_args: FakeKey(),
            QueryValueEx=lambda *_args: (existing, 2),
            SetValueEx=lambda _key, name, reserved, value_type, value: writes.append(
                (name, value, value_type, str(reserved))
            ),
        )
        monkeypatch.setitem(sys.modules, "winreg", fake_winreg)
        monkeypatch.setenv("PATH", existing)
        with (
            mock.patch("shared._is_windows", return_value=True),
            mock.patch("shared.is_admin", return_value=True),
        ):
            _add_to_system_path(tmp_path)

        assert len(writes) == 1
        assert writes[0][1] == f"{existing};{tmp_path}"
        assert os.environ["PATH"] == f"{existing};{tmp_path}"

    def test_entrypoints_are_import_safe_off_windows(self):
        with (
            mock.patch("shared._is_windows", return_value=False),
            mock.patch("shared._create_cmd_wrapper") as wrapper,
            mock.patch("shared._add_to_system_path") as path_update,
        ):
            shared.ensure_cli_entrypoints()
        wrapper.assert_not_called()
        path_update.assert_not_called()


@pytest.mark.parametrize(
    ("remote", "local", "expected"),
    [
        ("4.0.0", "3.9.9", True),
        ("3.1", "3.1.0", False),
        ("3.1.18", "3.1.17", True),
        ("invalid", "3.1.17", False),
    ],
)
def test_is_newer_version(remote: str, local: str, expected: bool):
    assert is_newer_version(remote, local) is expected
