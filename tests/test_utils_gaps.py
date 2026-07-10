"""Gap-closing coverage tests for utils.py (no system interaction)."""

import errno
import io
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import utils as utils_module
from utils import (
    ArchiveExtractor,
    ArchiveLimitError,
    FirewallManager,
    SystemDetector,
    SystemdManager,
    UnsafeArchiveError,
    _archive_member_parts,
    _ArchiveEntry,
    _extract_validated_entries,
    _member_destination,
    _safe_extract,
    _validate_entry_layout,
    _validate_limits,
    _validated_tar_entries,
    _validated_zip_entries,
    _write_archive_file,
    install_staged_directory,
)

# ---------- SystemDetector (113->121, 172-179, 190-198, 228-236) ----------


def test_detect_os_release_without_id_line(monkeypatch):
    detector = SystemDetector()
    monkeypatch.setattr("builtins.open", lambda _p: io.StringIO("NAME=Linux\nVERSION=1\n"))
    monkeypatch.setattr(utils_module.shutil, "which", lambda cmd: "/usr/bin/apt" if cmd == "apt" else None)
    detector.detect()
    assert detector.distribution is None
    assert detector.pkg_manager == "apt"


def test_install_dependencies_unknown_pkg_manager_and_update_failure(monkeypatch):
    detector = SystemDetector()
    detector.pkg_manager = "apt"
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "update" in cmd:
            raise RuntimeError("mirror down")
        return SimpleNamespace(returncode=0, stdout="v20.0.0\n")

    monkeypatch.setattr(utils_module.subprocess, "run", fake_run)
    detector._install_nodejs = mock.MagicMock()
    detector.install_dependencies()
    assert any("install" in c for c in calls)


def test_install_dependencies_skips_commands_for_alien_manager(monkeypatch):
    detector = SystemDetector()
    detector.pkg_manager = "zypper"
    monkeypatch.setattr(utils_module.Config, "SYSTEM_PACKAGES", {"zypper": ["curl"]}, raising=False) if hasattr(
        utils_module, "Config"
    ) else None
    run = mock.MagicMock(return_value=SimpleNamespace(returncode=0, stdout="v20.0.0\n"))
    monkeypatch.setattr(utils_module.subprocess, "run", run)
    # unknown manager name so update/install command lookups return None
    detector.pkg_manager = "portage"
    from config import Config

    monkeypatch.setattr(Config, "SYSTEM_PACKAGES", {"portage": ["curl"]}, raising=False)
    detector._install_nodejs = mock.MagicMock()
    detector.install_dependencies()
    run.assert_not_called()


def test_install_nodejs_pacman_failure(monkeypatch):
    detector = SystemDetector()
    detector.pkg_manager = "pacman"
    import subprocess as real_subprocess

    def fake_run(cmd, **kwargs):
        if cmd[:1] == ["pacman"]:
            raise real_subprocess.CalledProcessError(1, cmd)
        return SimpleNamespace(returncode=0, stdout="v20.0.0\n")

    monkeypatch.setattr(utils_module.subprocess, "run", fake_run)
    detector._install_nodejs()


def test_install_nodejs_unknown_manager_verifies_only(monkeypatch):
    detector = SystemDetector()
    detector.pkg_manager = "portage"
    run = mock.MagicMock(return_value=SimpleNamespace(returncode=0, stdout="v20.0.0\n"))
    monkeypatch.setattr(utils_module.subprocess, "run", run)
    detector._install_nodejs()
    assert run.call_count == 1  # only node -v verification


# ---------- FirewallManager (384->exit) ----------


def test_close_port_without_any_firewall_tool(monkeypatch):
    fw = FirewallManager()
    monkeypatch.setattr(utils_module.shutil, "which", lambda _cmd: None)
    run = mock.MagicMock()
    monkeypatch.setattr(utils_module.subprocess, "run", run)
    fw.close_port(3000)
    run.assert_not_called()


# ---------- SystemdManager identity (607->609, 625->exit) ----------


def test_prepare_service_identity_chown_failure_preexisting_user(monkeypatch):
    mgr = SystemdManager()
    monkeypatch.setattr(utils_module.shutil, "which", lambda _cmd: "/usr/bin/tool")
    monkeypatch.setattr(utils_module.pwd, "getpwnam", lambda _u: SimpleNamespace(pw_uid=999))
    run = mock.MagicMock(side_effect=RuntimeError("chown failed"))
    monkeypatch.setattr(utils_module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="chown failed"):
        mgr.prepare_service_identity("myapp", Path("/tmp/fake"))
    # userdel must not be attempted for a pre-existing user
    assert all(call.args[0][0] != "userdel" for call in run.call_args_list)


def test_release_service_identity_without_groupdel(tmp_path, monkeypatch):
    mgr = SystemdManager()
    monkeypatch.setattr(utils_module.shutil, "which", lambda _cmd: None)
    run = mock.MagicMock()
    monkeypatch.setattr(utils_module.subprocess, "run", run)
    mgr.release_service_identity("myapp", tmp_path, remove_user=True)
    commands = [call.args[0][0] for call in run.call_args_list]
    assert "userdel" in commands
    assert "groupdel" not in commands


# ---------- install_staged_directory (789, 799-808) ----------


def test_install_staged_missing_renameat2(tmp_path, monkeypatch):
    monkeypatch.setattr(utils_module.ctypes, "CDLL", lambda *_a, **_k: SimpleNamespace())
    with pytest.raises(OSError, match="unavailable"):
        install_staged_directory(tmp_path / "src", tmp_path / "dst")


def test_install_staged_renameat2_generic_errno(tmp_path, monkeypatch):
    fake_renameat2 = mock.MagicMock(return_value=-1)
    fake_libc = SimpleNamespace(renameat2=fake_renameat2)
    monkeypatch.setattr(utils_module.ctypes, "CDLL", lambda *_a, **_k: fake_libc)
    monkeypatch.setattr(utils_module.ctypes, "get_errno", lambda: errno.EXDEV)
    with pytest.raises(OSError) as excinfo:
        install_staged_directory(tmp_path / "src", tmp_path / "dst")
    assert excinfo.value.errno == errno.EXDEV


def test_install_staged_non_linux_fallback_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(utils_module.sys, "platform", "darwin")
    # success
    src = tmp_path / "src"
    src.mkdir()
    install_staged_directory(src, tmp_path / "ok")
    assert (tmp_path / "ok").is_dir()
    # FileExistsError from os.rename
    monkeypatch.setattr(utils_module.os, "rename", mock.MagicMock(side_effect=FileExistsError("x")))
    with pytest.raises(FileExistsError, match="already exists"):
        install_staged_directory(tmp_path / "a", tmp_path / "b")
    # OSError with existing target
    existing = tmp_path / "existing"
    existing.mkdir()
    monkeypatch.setattr(utils_module.os, "rename", mock.MagicMock(side_effect=OSError("busy")))
    with pytest.raises(FileExistsError, match="already exists"):
        install_staged_directory(tmp_path / "a", existing)
    # OSError with missing target re-raises
    with pytest.raises(OSError, match="busy"):
        install_staged_directory(tmp_path / "a", tmp_path / "missing-target")


# ---------- archive member validation (814, 833-834) ----------


def test_archive_member_parts_rejects_non_string_and_nul():
    with pytest.raises(UnsafeArchiveError):
        _archive_member_parts(123)  # type: ignore[arg-type]
    with pytest.raises(UnsafeArchiveError):
        _archive_member_parts("bad\x00name")


def test_member_destination_rejects_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(UnsafeArchiveError, match="escapes extraction directory"):
        _member_destination(root, ("link", "file.txt"))


# ---------- entry layout / limits (845-854, 872-874) ----------


def test_layout_rejects_file_with_empty_path():
    entry = _ArchiveEntry(member=None, parts=(), is_dir=False, size=1, mode=0o644)
    with pytest.raises(UnsafeArchiveError, match="empty path"):
        _validate_entry_layout([entry], None)


def test_layout_empty_after_skipping_rootless_dirs():
    entry = _ArchiveEntry(member=None, parts=(), is_dir=True, size=0, mode=0o755)
    with pytest.raises(UnsafeArchiveError, match="Archive is empty"):
        _validate_entry_layout([entry], None)


def test_validate_limits_rejects_bad_limits_and_too_many_files():
    entry = _ArchiveEntry(member=None, parts=("a",), is_dir=False, size=1, mode=0o644)
    with pytest.raises(ValueError, match="positive"):
        _validate_limits([entry], 0, 100)
    with pytest.raises(ArchiveLimitError, match="too many files"):
        _validate_limits([entry, entry], 1, 100)


# ---------- zip/tar entry validation (902, 927) ----------


def test_zip_entries_negative_size_rejected():
    info = zipfile.ZipInfo("file.txt")
    info.file_size = -5
    archive = mock.MagicMock()
    archive.infolist.return_value = [info]
    with pytest.raises(UnsafeArchiveError, match="Invalid archive member size"):
        _validated_zip_entries(archive, 10, 1000, None)


def test_tar_entries_negative_size_rejected():
    member = tarfile.TarInfo("file.txt")
    member.type = tarfile.REGTYPE
    member.size = -5
    archive = [member]
    with pytest.raises(UnsafeArchiveError, match="Invalid archive member size"):
        _validated_tar_entries(archive, 10, 1000, None)


# ---------- streamed writes (951, 953, 957) ----------


class _FakeSource(io.BytesIO):
    pass


def test_write_archive_file_member_exceeds_declared_size(tmp_path):
    entry = _ArchiveEntry(member=None, parts=("f",), is_dir=False, size=2, mode=0o644)
    with pytest.raises(UnsafeArchiveError, match="exceeds its declared size"):
        _write_archive_file(_FakeSource(b"toolong"), tmp_path / "f", entry, 0, 1000)


def test_write_archive_file_total_exceeds_limit(tmp_path):
    entry = _ArchiveEntry(member=None, parts=("f",), is_dir=False, size=10, mode=0o644)
    with pytest.raises(ArchiveLimitError, match="more than"):
        _write_archive_file(_FakeSource(b"0123456789"), tmp_path / "f", entry, 0, 5)


def test_write_archive_file_short_member(tmp_path):
    entry = _ArchiveEntry(member=None, parts=("f",), is_dir=False, size=10, mode=0o644)
    with pytest.raises(UnsafeArchiveError, match="size mismatch"):
        _write_archive_file(_FakeSource(b"abc"), tmp_path / "f", entry, 0, 1000)


# ---------- extraction internals (972, 977, 984, 988, 991) ----------


def test_extract_entries_skips_empty_parts_and_rejects_symlink_dir(tmp_path):
    root = tmp_path / "root"
    real = root / "real"
    real.mkdir(parents=True)
    (root / "link").symlink_to(real)
    entries = [
        _ArchiveEntry(member=None, parts=(), is_dir=True, size=0, mode=0o755),
        _ArchiveEntry(member=None, parts=("link",), is_dir=True, size=0, mode=0o755),
    ]
    archive = mock.MagicMock(spec=zipfile.ZipFile)
    with pytest.raises(UnsafeArchiveError, match="Unsafe archive directory"):
        _extract_validated_entries(archive, entries, root, 1000)


def test_extract_entries_rejects_wrong_zip_member_metadata(tmp_path):
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("x.txt", "data")
    root = tmp_path / "root"
    root.mkdir()
    entry = _ArchiveEntry(member="not-zipinfo", parts=("x.txt",), is_dir=False, size=4, mode=0o644)
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(UnsafeArchiveError, match="Invalid ZIP member metadata"):
            _extract_validated_entries(archive, [entry], root, 1000)


def _make_tar(tmp_path: Path) -> Path:
    tar_path = tmp_path / "a.tar"
    src = tmp_path / "payload.txt"
    src.write_text("data")
    with tarfile.open(tar_path, "w") as tf:
        tf.add(src, arcname="payload.txt")
    return tar_path


def test_extract_entries_rejects_wrong_tar_member_metadata(tmp_path):
    tar_path = _make_tar(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    entry = _ArchiveEntry(member="not-tarinfo", parts=("payload.txt",), is_dir=False, size=4, mode=0o644)
    with tarfile.open(tar_path) as archive:
        with pytest.raises(UnsafeArchiveError, match="Invalid TAR member metadata"):
            _extract_validated_entries(archive, [entry], root, 1000)


def test_extract_entries_unreadable_tar_member(tmp_path, monkeypatch):
    tar_path = _make_tar(tmp_path)
    root = tmp_path / "root"
    root.mkdir()
    with tarfile.open(tar_path) as archive:
        member = archive.getmembers()[0]
        entry = _ArchiveEntry(member=member, parts=("payload.txt",), is_dir=False, size=4, mode=0o644)
        monkeypatch.setattr(archive, "extractfile", lambda _m: None)
        with pytest.raises(UnsafeArchiveError, match="Cannot read archive member"):
            _extract_validated_entries(archive, [entry], root, 1000)


# ---------- _safe_extract guards (1022, 1037) ----------


def test_safe_extract_rejects_symlink_parent(tmp_path):
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("x.txt", "data")
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(real_parent)
    with pytest.raises(UnsafeArchiveError, match="symbolic link"):
        _safe_extract(zip_path, link_parent / "target", "zip", max_files=10, max_bytes=1000, expected_top_level=None)


def test_safe_extract_missing_expected_top_level_dir(tmp_path):
    zip_path = tmp_path / "a.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("app", "a file, not a directory")
    with pytest.raises(UnsafeArchiveError, match="missing top-level directory"):
        _safe_extract(zip_path, tmp_path / "out", "zip", max_files=10, max_bytes=1000, expected_top_level="app")


# ---------- ArchiveExtractor (1151, 1167) ----------


def test_extractor_rejects_target_created_during_staging(tmp_path, monkeypatch):
    extractor = ArchiveExtractor()
    archive = tmp_path / "app.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("app/x.txt", "data")
    target = tmp_path / "out"

    def fake_safe_extract(_archive, payload, **_kwargs):
        Path(payload).mkdir(parents=True)
        target.mkdir()  # simulate a race creating the target mid-staging
        return Path(payload)

    monkeypatch.setattr(utils_module, "safe_extract_archive", fake_safe_extract)
    monkeypatch.setattr(extractor, "_find_product_dir", lambda payload, _n: payload)
    monkeypatch.setattr(extractor, "_set_permissions", lambda _p: None)
    with pytest.raises(FileExistsError, match="already exists"):
        extractor.extract(archive, target)


def test_extractor_set_permissions_skips_directories(tmp_path, monkeypatch):
    extractor = ArchiveExtractor()
    product = tmp_path / "product"
    (product / "subdir").mkdir(parents=True)
    (product / "config.yml").write_text("a: 1")
    (product / "run.sh").write_text("#!/bin/sh")
    (product / "notes.txt").write_text("hello")
    monkeypatch.setattr(utils_module.subprocess, "run", mock.MagicMock())
    extractor._set_permissions(product)
    assert (product / "config.yml").stat().st_mode & 0o777 == 0o600
    assert (product / "run.sh").stat().st_mode & 0o777 == 0o750
    assert (product / "notes.txt").stat().st_mode & 0o777 == 0o640
