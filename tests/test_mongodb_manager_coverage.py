"""Additional coverage tests for mongodb_manager.py.

Targets: setup flow, install dispatch, ensure_running, run_shell fallback,
create_user retries, validate_uri, credential removal edge cases,
cleanup_identity failures, config patching branches, distro installers,
and the default TCP wait helper.  Everything system-facing is mocked.
"""

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from mongodb_manager import MongoDBManager
from utils import ColorPrinter, SystemDetector


def _make_manager(distro: str = "ubuntu") -> MongoDBManager:
    system = SystemDetector()
    system.distribution = distro
    return MongoDBManager(
        printer=ColorPrinter(),
        system=system,
        mongodb_version="8.0",
        mongodb_repo_version_bookworm="8.2",
    )


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_declined_returns_none(self):
        mgr = _make_manager()
        with mock.patch("builtins.input", return_value="n"):
            assert mgr.setup("inst", Path("/tmp")) is None

    def test_declined_required_prints_warning(self, capsys):
        mgr = _make_manager()
        with mock.patch("builtins.input", return_value="n"):
            assert mgr.setup("inst", Path("/tmp"), required=True) is None
        assert "requires MongoDB" in capsys.readouterr().err

    def test_required_empty_input_defaults_to_yes(self, tmp_path: Path):
        mgr = _make_manager()
        creds = {"uri": "mongodb://u:p@localhost:27017/db"}
        with (
            mock.patch("builtins.input", return_value=""),
            mock.patch.object(mgr, "check_installed", return_value=True),
            mock.patch.object(mgr, "ensure_running", return_value="mongod"),
            mock.patch.object(mgr, "create_user", return_value=creds),
            mock.patch.object(mgr, "save_credentials"),
            mock.patch.object(mgr, "update_config"),
            mock.patch.object(mgr, "validate_uri", return_value=True),
        ):
            result = mgr.setup("inst", tmp_path, required=True, wait_for_tcp_port=lambda *a: True)
        assert result == creds

    def test_install_failure_returns_none(self):
        mgr = _make_manager()
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(mgr, "check_installed", return_value=False),
            mock.patch.object(mgr, "install", return_value=False),
        ):
            assert mgr.setup("inst", Path("/tmp")) is None

    def test_installs_when_not_installed(self, tmp_path: Path):
        mgr = _make_manager()
        creds = {"uri": "mongodb://u:p@localhost:27017/db"}
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(mgr, "check_installed", return_value=False),
            mock.patch.object(mgr, "install", return_value=True) as install,
            mock.patch.object(mgr, "ensure_running", return_value="mongod"),
            mock.patch.object(mgr, "create_user", return_value=creds),
            mock.patch.object(mgr, "save_credentials"),
            mock.patch.object(mgr, "update_config"),
            mock.patch.object(mgr, "validate_uri", return_value=True),
        ):
            assert mgr.setup("inst", tmp_path, wait_for_tcp_port=lambda *a: True) == creds
        install.assert_called_once()

    def test_port_never_ready_raises(self):
        mgr = _make_manager()
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(mgr, "check_installed", return_value=True),
            mock.patch.object(mgr, "ensure_running", return_value="mongod"),
            pytest.raises(RuntimeError, match="did not become ready"),
        ):
            mgr.setup("inst", Path("/tmp"), wait_for_tcp_port=lambda *a: False)

    def test_create_user_failure_raises(self):
        mgr = _make_manager()
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(mgr, "check_installed", return_value=True),
            mock.patch.object(mgr, "ensure_running", return_value="mongod"),
            mock.patch.object(mgr, "create_user", return_value=None),
            pytest.raises(RuntimeError, match="Failed to create"),
        ):
            mgr.setup("inst", Path("/tmp"), wait_for_tcp_port=lambda *a: True)

    def test_validate_failure_raises(self, tmp_path: Path):
        mgr = _make_manager()
        creds = {"uri": "mongodb://u:p@localhost:27017/db"}
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(mgr, "check_installed", return_value=True),
            mock.patch.object(mgr, "ensure_running", return_value="mongod"),
            mock.patch.object(mgr, "create_user", return_value=creds),
            mock.patch.object(mgr, "save_credentials"),
            mock.patch.object(mgr, "update_config"),
            mock.patch.object(mgr, "validate_uri", return_value=False),
            pytest.raises(RuntimeError, match="authentication failed"),
        ):
            mgr.setup("inst", tmp_path, wait_for_tcp_port=lambda *a: True)


# ---------------------------------------------------------------------------
# install dispatch
# ---------------------------------------------------------------------------


class TestInstallDispatch:
    @pytest.mark.parametrize(
        ("distro", "method"),
        [
            ("ubuntu", "_install_debian"),
            ("debian", "_install_debian"),
            ("centos", "_install_rhel"),
            ("rhel", "_install_rhel"),
            ("fedora", "_install_rhel"),
            ("arch", "_install_arch"),
        ],
    )
    def test_dispatches_by_distro(self, distro: str, method: str):
        mgr = _make_manager(distro=distro)
        with mock.patch.object(mgr, method, return_value=True) as impl:
            assert mgr.install() is True
        impl.assert_called_once()

    def test_unsupported_distro_returns_false(self, capsys):
        mgr = _make_manager(distro="gentoo")
        assert mgr.install() is False
        assert "Unsupported distribution" in capsys.readouterr().err

    def test_none_distribution_returns_false(self):
        mgr = _make_manager(distro="ubuntu")
        mgr.system.distribution = None
        assert mgr.install() is False

    def test_exception_in_installer_returns_false(self):
        mgr = _make_manager(distro="ubuntu")
        with mock.patch.object(mgr, "_install_debian", side_effect=OSError("boom")):
            assert mgr.install() is False


# ---------------------------------------------------------------------------
# ensure_running
# ---------------------------------------------------------------------------


class TestEnsureRunning:
    def test_already_active(self):
        mgr = _make_manager()
        with mock.patch("mongodb_manager.subprocess.run", return_value=_ok("active\n")):
            assert mgr.ensure_running() == "mongod"

    def test_starts_inactive_service(self):
        mgr = _make_manager()
        calls = []

        def side_effect(cmd, **kw):
            calls.append(cmd)
            if cmd[:2] == ["systemctl", "is-active"]:
                return _ok("active\n" if len(calls) > 2 else "inactive\n")
            return _ok()

        with mock.patch("mongodb_manager.subprocess.run", side_effect=side_effect):
            assert mgr.ensure_running() == "mongod"
        assert ["systemctl", "start", "mongod"] in calls

    def test_falls_back_to_mongodb_service(self):
        mgr = _make_manager()

        def side_effect(cmd, **kw):
            service = cmd[-1]
            if service == "mongod":
                raise subprocess.CalledProcessError(1, cmd)
            return _ok("active\n")

        with mock.patch("mongodb_manager.subprocess.run", side_effect=side_effect):
            assert mgr.ensure_running() == "mongodb"

    def test_raises_when_nothing_starts(self):
        mgr = _make_manager()
        with (
            mock.patch("mongodb_manager.subprocess.run", return_value=_ok("failed\n")),
            pytest.raises(RuntimeError, match="Could not start MongoDB"),
        ):
            mgr.ensure_running()


# ---------------------------------------------------------------------------
# run_shell
# ---------------------------------------------------------------------------


class TestRunShell:
    def test_prefers_mongosh(self):
        mgr = _make_manager()
        with mock.patch("mongodb_manager.subprocess.run", return_value=_ok()) as run:
            mgr.run_shell(["--eval", "1"])
        assert run.call_args.args[0][0] == "mongosh"

    def test_falls_back_to_mongo(self):
        mgr = _make_manager()

        def side_effect(cmd, **kw):
            if cmd[0] == "mongosh":
                raise FileNotFoundError("mongosh")
            return _ok("ok")

        with mock.patch("mongodb_manager.subprocess.run", side_effect=side_effect):
            result = mgr.run_shell(["--eval", "1"])
        assert result.stdout == "ok"


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------


class TestCreateUser:
    def test_success_first_try(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", return_value=_ok("__PLEXINSTALLER_OK__\n")):
            creds = mgr.create_user("myapp")
        assert creds is not None
        assert creds["database"].startswith("myapp_")
        assert creds["username"].endswith("_user")
        assert creds["host"] == "localhost"
        assert creds["port"] == 27017
        assert creds["password"] in creds["uri"]
        assert f"authSource={creds['database']}" in creds["uri"]

    def test_retries_then_succeeds(self):
        mgr = _make_manager()
        results = [_ok("__PLEXINSTALLER_ERROR__ x", returncode=2), _ok("__PLEXINSTALLER_OK__")]
        with (
            mock.patch.object(mgr, "run_shell", side_effect=results),
            mock.patch("mongodb_manager.time.sleep"),
        ):
            assert mgr.create_user("myapp") is not None

    def test_all_retries_fail_returns_none(self, capsys):
        mgr = _make_manager()
        with (
            mock.patch.object(mgr, "run_shell", return_value=_ok("__PLEXINSTALLER_ERROR__ nope", returncode=2)),
            mock.patch("mongodb_manager.time.sleep"),
        ):
            assert mgr.create_user("myapp") is None
        assert "Failed to create MongoDB user" in capsys.readouterr().err

    def test_unauthorized_prints_auth_hint(self, capsys):
        mgr = _make_manager()
        with (
            mock.patch.object(mgr, "run_shell", return_value=_ok("not authorized on admin", returncode=1)),
            mock.patch("mongodb_manager.time.sleep"),
        ):
            assert mgr.create_user("myapp") is None
        assert "authentication enabled" in capsys.readouterr().err

    def test_exception_in_shell_is_retried(self):
        mgr = _make_manager()
        with (
            mock.patch.object(mgr, "run_shell", side_effect=subprocess.TimeoutExpired("mongosh", 30)),
            mock.patch("mongodb_manager.time.sleep"),
        ):
            assert mgr.create_user("myapp") is None


# ---------------------------------------------------------------------------
# validate_uri
# ---------------------------------------------------------------------------


class TestValidateUri:
    def test_success(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", return_value=_ok("__PLEXINSTALLER_OK__")):
            assert mgr.validate_uri("mongodb://u:p@localhost/db") is True

    def test_failure_returncode(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", return_value=_ok("__PLEXINSTALLER_ERROR__", returncode=2)):
            assert mgr.validate_uri("mongodb://u:p@localhost/db") is False

    def test_exception_returns_false(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", side_effect=OSError("boom")):
            assert mgr.validate_uri("mongodb://u:p@localhost/db") is False


# ---------------------------------------------------------------------------
# remove_saved_credentials edge cases
# ---------------------------------------------------------------------------


class TestRemoveSavedCredentials:
    def test_missing_file_returns_false(self, tmp_path: Path):
        mgr = _make_manager()
        assert mgr.remove_saved_credentials("x", tmp_path / "nope") is False

    def test_instance_not_found_returns_false(self, tmp_path: Path):
        mgr = _make_manager()
        f = tmp_path / "creds"
        f.write_text("# other\nDATABASE=db\nUSERNAME=u\nPASSWORD=p\nURI=uri\n")
        assert mgr.remove_saved_credentials("missing", f) is False
        assert "DATABASE=db" in f.read_text()

    def test_removing_last_block_deletes_file(self, tmp_path: Path):
        mgr = _make_manager()
        f = tmp_path / "creds"
        f.write_text("# only\nDATABASE=db\nUSERNAME=u\nPASSWORD=p\nURI=uri\n")
        assert mgr.remove_saved_credentials("only", f) is True
        assert not f.exists()

    def test_preserves_file_mode(self, tmp_path: Path):
        mgr = _make_manager()
        f = tmp_path / "creds"
        f.write_text(
            "# a\nDATABASE=d1\nUSERNAME=u1\nPASSWORD=p1\nURI=uri1\n\n"
            "# b\nDATABASE=d2\nUSERNAME=u2\nPASSWORD=p2\nURI=uri2\n"
        )
        f.chmod(0o600)
        assert mgr.remove_saved_credentials("a", f) is True
        assert (f.stat().st_mode & 0o777) == 0o600
        assert "DATABASE=d2" in f.read_text()


# ---------------------------------------------------------------------------
# cleanup_identity
# ---------------------------------------------------------------------------


class TestCleanupIdentity:
    def test_empty_args_return_false(self):
        mgr = _make_manager()
        assert mgr.cleanup_identity("", "user") is False
        assert mgr.cleanup_identity("db", "") is False

    def test_drop_database_included_when_requested(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", return_value=_ok("__PLEXINSTALLER_OK__")) as shell:
            assert mgr.cleanup_identity("db", "user", drop_database=True) is True
        assert "dropDatabase" in shell.call_args.args[0][-1]

    def test_shell_failure_returns_false(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", return_value=_ok("err", returncode=2)):
            assert mgr.cleanup_identity("db", "user") is False

    def test_exception_returns_false(self):
        mgr = _make_manager()
        with mock.patch.object(mgr, "run_shell", side_effect=OSError("boom")):
            assert mgr.cleanup_identity("db", "user") is False


# ---------------------------------------------------------------------------
# update_config branches
# ---------------------------------------------------------------------------


class TestUpdateConfigBranches:
    def test_json_without_known_key_adds_mongouri(self, tmp_path: Path):
        mgr = _make_manager()
        cfg = tmp_path / "config.json"
        cfg.write_text('{"port": 3000}')
        mgr.update_config(tmp_path, {"uri": "mongodb://u:p@h/db"})
        assert json.loads(cfg.read_text())["mongoURI"] == "mongodb://u:p@h/db"

    def test_invalid_json_warns(self, tmp_path: Path, capsys):
        mgr = _make_manager()
        (tmp_path / "config.json").write_text("{not json")
        mgr.update_config(tmp_path, {"uri": "mongodb://u:p@h/db"})
        assert "Could not auto-update JSON config" in capsys.readouterr().err

    def test_yaml_without_uri_field_warns(self, tmp_path: Path, capsys):
        mgr = _make_manager()
        (tmp_path / "config.yml").write_text("Port: 3000\n")
        mgr.update_config(tmp_path, {"uri": "mongodb://u:p@h/db"})
        err = capsys.readouterr().err
        assert "Could not find MongoDB URI field" in err

    def test_yaml_mongouri_capitalized_variant(self, tmp_path: Path):
        mgr = _make_manager()
        cfg = tmp_path / "config.yaml"
        cfg.write_text('MongoURI: "old"\n')
        mgr.update_config(tmp_path, {"uri": "mongodb://u:p@h/db"})
        assert "mongodb://u:p@h/db" in cfg.read_text()

    def test_yaml_read_error_warns(self, tmp_path: Path, capsys):
        mgr = _make_manager()
        cfg = tmp_path / "config.yml"
        cfg.write_text("mongoURI: x\n")
        with mock.patch.object(Path, "read_text", side_effect=OSError("denied")):
            mgr.update_config(tmp_path, {"uri": "mongodb://u:p@h/db"})
        assert "Could not auto-update config" in capsys.readouterr().err

    def test_uri_with_quotes_is_escaped(self, tmp_path: Path):
        mgr = _make_manager()
        cfg = tmp_path / "config.yml"
        cfg.write_text('mongoURI: ""\n')
        mgr.update_config(tmp_path, {"uri": 'mongodb://u:p"x@h/db'})
        assert '\\"' in cfg.read_text()


# ---------------------------------------------------------------------------
# _install_debian / _install_rhel
# ---------------------------------------------------------------------------


class TestInstallDebian:
    def _run(self, mgr, codename="jammy"):
        """Run _install_debian with everything mocked; return list of run() cmds and written repo lines."""
        written = {}

        def fake_open(path, mode="r", *a, **kw):
            handle = mock.mock_open()(path, mode)
            handle.write.side_effect = lambda data: written.setdefault(path, []).append(data)
            return handle

        def run_side_effect(cmd, **kw):
            if cmd[:1] == ["lsb_release"]:
                return _ok(f"{codename}\n")
            return _ok()

        popen = mock.MagicMock()
        popen.stdout = mock.MagicMock()
        with (
            mock.patch("mongodb_manager.Path") as path_cls,
            mock.patch("builtins.open", side_effect=fake_open),
            mock.patch("mongodb_manager.subprocess.run", side_effect=run_side_effect) as run,
            mock.patch("mongodb_manager.subprocess.Popen", return_value=popen),
        ):
            path_cls.return_value.exists.return_value = False
            result = mgr._install_debian()
        return result, run, written

    def test_ubuntu_repo_line(self):
        mgr = _make_manager(distro="ubuntu")
        result, run, written = self._run(mgr)
        assert result is True
        repo_lines = [line for lines in written.values() for line in lines]
        assert any("repo.mongodb.org/apt/ubuntu" in line and "jammy" in line for line in repo_lines)

    def test_debian_bullseye_repo_line(self):
        mgr = _make_manager(distro="debian")
        result, _, written = self._run(mgr, codename="bullseye")
        assert result is True
        repo_lines = [line for lines in written.values() for line in lines]
        assert any("bullseye/mongodb-org/8.0" in line for line in repo_lines)

    def test_debian_bookworm_uses_bookworm_repo_version(self):
        mgr = _make_manager(distro="debian")
        result, _, written = self._run(mgr, codename="bookworm")
        assert result is True
        repo_lines = [line for lines in written.values() for line in lines]
        assert any("bookworm/mongodb-org/8.2" in line for line in repo_lines)

    def test_unknown_distro_falls_back_to_focal(self):
        mgr = _make_manager(distro="mint")
        result, _, written = self._run(mgr)
        assert result is True
        repo_lines = [line for lines in written.values() for line in lines]
        assert any("focal/mongodb-org/8.0" in line for line in repo_lines)

    def test_cleans_old_repo_files(self):
        mgr = _make_manager(distro="ubuntu")
        with (
            mock.patch("mongodb_manager.Path") as path_cls,
            mock.patch("builtins.open", mock.mock_open()),
            mock.patch("mongodb_manager.subprocess.run", return_value=_ok("jammy\n")),
            mock.patch("mongodb_manager.subprocess.Popen", return_value=mock.MagicMock()),
        ):
            path_cls.return_value.exists.return_value = True
            assert mgr._install_debian() is True
        assert path_cls.return_value.unlink.call_count == 8

    def test_apt_failure_returns_false(self, capsys):
        mgr = _make_manager(distro="ubuntu")
        with mock.patch(
            "mongodb_manager.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["apt-get"]),
        ):
            with mock.patch("mongodb_manager.Path") as path_cls:
                path_cls.return_value.exists.return_value = False
                assert mgr._install_debian() is False
        assert "Failed to install MongoDB" in capsys.readouterr().err


class TestInstallRhel:
    def test_centos_uses_yum(self):
        mgr = _make_manager(distro="centos")
        with (
            mock.patch("builtins.open", mock.mock_open()) as opened,
            mock.patch("mongodb_manager.subprocess.run", return_value=_ok()) as run,
        ):
            assert mgr._install_rhel() is True
        assert opened.call_args.args[0] == "/etc/yum.repos.d/mongodb-org-8.0.repo"
        assert run.call_args_list[0].args[0][0] == "yum"

    def test_fedora_uses_dnf(self):
        mgr = _make_manager(distro="fedora")
        with (
            mock.patch("builtins.open", mock.mock_open()),
            mock.patch("mongodb_manager.subprocess.run", return_value=_ok()) as run,
        ):
            assert mgr._install_rhel() is True
        assert run.call_args_list[0].args[0][0] == "dnf"

    def test_failure_returns_false(self):
        mgr = _make_manager(distro="centos")
        with (
            mock.patch("builtins.open", mock.mock_open()),
            mock.patch(
                "mongodb_manager.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["yum"]),
            ),
        ):
            assert mgr._install_rhel() is False


class TestInstallArchFailure:
    def test_pacman_failure_returns_false(self):
        mgr = _make_manager(distro="arch")
        with (
            mock.patch("mongodb_manager.shutil.which", return_value="/usr/bin/yay"),
            mock.patch(
                "mongodb_manager.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["yay"]),
            ),
        ):
            assert mgr._install_arch() is False


# ---------------------------------------------------------------------------
# _default_wait_for_tcp_port
# ---------------------------------------------------------------------------


class TestDefaultWaitForTcpPort:
    def test_success(self):
        conn = mock.MagicMock()
        with mock.patch("socket.create_connection", return_value=conn):
            assert MongoDBManager._default_wait_for_tcp_port("127.0.0.1", 27017, 5) is True

    def test_timeout_returns_false(self):
        with (
            mock.patch("socket.create_connection", side_effect=OSError("refused")),
            mock.patch("mongodb_manager.time.sleep"),
        ):
            assert MongoDBManager._default_wait_for_tcp_port("127.0.0.1", 27017, 0) is False
