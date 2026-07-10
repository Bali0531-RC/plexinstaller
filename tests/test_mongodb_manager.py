"""Windows MongoDB manager contracts."""

import json
import os
import subprocess
from pathlib import Path
from unittest import mock

from mongodb_manager import MongoDBManager
from utils import ColorPrinter, SystemDetector


def _manager() -> MongoDBManager:
    return MongoDBManager(ColorPrinter(), SystemDetector(), "8.0")


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def test_check_installed_prefers_mongosh_and_falls_back_to_mongo():
    manager = _manager()
    with mock.patch("mongodb_manager.subprocess.run", return_value=_completed(stdout="2.1")) as run:
        assert manager.check_installed() is True
    assert run.call_args.args[0][0] == "mongosh"

    def fallback(command, **_kwargs):
        if command[0] == "mongosh":
            raise FileNotFoundError
        return _completed(stdout="5.0")

    with mock.patch("mongodb_manager.subprocess.run", side_effect=fallback):
        assert manager.check_installed() is True


def test_check_installed_handles_missing_and_timeout():
    manager = _manager()
    with mock.patch("mongodb_manager.subprocess.run", side_effect=FileNotFoundError):
        assert manager.check_installed() is False
    with mock.patch("mongodb_manager.subprocess.run", side_effect=subprocess.TimeoutExpired("mongosh", 10)):
        assert manager.check_installed() is False


def test_save_credentials_is_atomic_and_restricts_file(monkeypatch, tmp_path: Path):
    manager = _manager()
    monkeypatch.setenv("ProgramData", str(tmp_path))
    restrict = mock.MagicMock()
    monkeypatch.setattr(manager, "_restrict_credentials_acl", restrict)
    credentials = {
        "database": "tickets_a",
        "username": "tickets_a_user",
        "password": "secret",
        "uri": "mongodb://tickets_a_user:secret@localhost/tickets_a",
    }
    path = manager.save_credentials("tickets", credentials)
    assert path == tmp_path / "plex" / "mongodb_credentials"
    assert "PASSWORD=secret" in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    restrict.assert_called_once_with(path)


def test_save_credentials_preserves_other_instance(monkeypatch, tmp_path: Path):
    manager = _manager()
    monkeypatch.setenv("ProgramData", str(tmp_path))
    monkeypatch.setattr(manager, "_restrict_credentials_acl", mock.MagicMock())
    first = {"database": "a", "username": "ua", "password": "pa", "uri": "mongodb://ua:pa@host/a"}
    second = {"database": "b", "username": "ub", "password": "pb", "uri": "mongodb://ub:pb@host/b"}
    path = manager.save_credentials("first", first)
    manager.save_credentials("second", second)
    content = path.read_text()
    assert "# first" in content and "# second" in content
    assert manager.remove_saved_credentials("first", path) is True
    assert "# first" not in path.read_text()
    assert "# second" in path.read_text()


def test_update_config_patches_yaml_and_json(tmp_path: Path):
    manager = _manager()
    yaml_dir = tmp_path / "yaml"
    yaml_dir.mkdir()
    yaml_config = yaml_dir / "config.yml"
    yaml_config.write_text('# mongoURI: old\nmongoURI: ""\nPort: 3000\n')
    manager.update_config(yaml_dir, {"uri": "mongodb://u:p@host/db"})
    assert yaml_config.read_text().splitlines()[0] == "# mongoURI: old"
    assert "mongodb://u:p@host/db" in yaml_config.read_text()

    json_dir = tmp_path / "json"
    json_dir.mkdir()
    json_config = json_dir / "config.json"
    json_config.write_text('{"port": 3000}')
    manager.update_config(json_dir, {"uri": "mongodb://u:p@host/db"})
    assert json.loads(json_config.read_text())["mongoURI"] == "mongodb://u:p@host/db"


def test_create_user_stops_on_permanent_auth_error():
    manager = _manager()
    with (
        mock.patch.object(manager, "run_shell", return_value=_completed(1, "not authorized")) as shell,
        mock.patch("mongodb_manager.time.sleep") as sleep,
    ):
        assert manager.create_user("tickets") is None
    shell.assert_called_once()
    sleep.assert_not_called()


def test_create_user_retries_transient_errors_without_final_sleep():
    manager = _manager()
    with (
        mock.patch.object(manager, "run_shell", return_value=_completed(2, "temporary")) as shell,
        mock.patch("mongodb_manager.time.sleep") as sleep,
    ):
        assert manager.create_user("tickets") is None
    assert shell.call_count == 5
    assert sleep.call_count == 4


def test_install_windows_prefers_winget_then_choco():
    manager = _manager()

    def winget(command, **_kwargs):
        return _completed() if command[0] == "winget" else _completed(1)

    with mock.patch("mongodb_manager.subprocess.run", side_effect=winget) as run:
        assert manager._install_windows() is True
    assert any(call.args[0][:4] == ["winget", "install", "--id", "MongoDB.Server"] for call in run.call_args_list)

    def choco(command, **_kwargs):
        if command[0] == "winget":
            raise FileNotFoundError
        return _completed()

    with mock.patch("mongodb_manager.subprocess.run", side_effect=choco) as run:
        assert manager._install_windows() is True
    assert any(call.args[0][:3] == ["choco", "install", "mongodb"] for call in run.call_args_list)


def test_acl_command_is_best_effort_on_windows(monkeypatch, tmp_path: Path):
    path = tmp_path / "credentials"
    path.write_text("secret")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setenv("USERNAME", "Alice")
    with mock.patch("mongodb_manager.subprocess.run") as run:
        MongoDBManager._restrict_credentials_acl(path)
    command = run.call_args.args[0]
    assert command[:3] == ["icacls", str(path), "/inheritance:r"]
    assert "Alice:(R,W)" in command
