"""Additional branch-coverage tests for config.py."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import config as config_module
from config import Config


class TestFindAppConfig:
    def test_returns_none_when_no_config_present(self, tmp_path: Path):
        assert Config.find_app_config(tmp_path) is None


class TestIsPortAvailable:
    def test_port_out_of_range(self):
        assert Config.is_port_available(0) is False
        assert Config.is_port_available(70000) is False

    def test_bindable_port_returns_true(self):
        with patch.object(config_module.socket, "socket") as socket_factory:
            sock = MagicMock()
            socket_factory.return_value.__enter__.return_value = sock
            assert Config.is_port_available(8080) is True
            sock.bind.assert_called_once_with(("127.0.0.1", 8080))

    def test_ipv6_host_uses_inet6_family(self):
        with patch.object(config_module.socket, "socket") as socket_factory:
            sock = MagicMock()
            socket_factory.return_value.__enter__.return_value = sock
            assert Config.is_port_available(8080, host="::1") is True
            socket_factory.assert_called_once_with(config_module.socket.AF_INET6, config_module.socket.SOCK_STREAM)

    def test_bind_failure_returns_false(self):
        with patch.object(config_module.socket, "socket") as socket_factory:
            sock = MagicMock()
            sock.bind.side_effect = OSError("in use")
            socket_factory.return_value.__enter__.return_value = sock
            assert Config.is_port_available(8080) is False


class TestPersistAppPort:
    def test_invalid_port_rejected(self, tmp_path: Path):
        with pytest.raises(ValueError, match="between 1 and 65535"):
            Config().persist_app_port(tmp_path, 0)

    def test_missing_config_rejected(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            Config().persist_app_port(tmp_path, 3000)

    def test_json_non_object_rejected(self, tmp_path: Path):
        (tmp_path / "config.json").write_text("[1, 2]", encoding="utf-8")
        with pytest.raises(ValueError, match="must contain an object"):
            Config().persist_app_port(tmp_path, 3000)

    def test_yaml_non_mapping_rejected(self, tmp_path: Path):
        (tmp_path / "config.yml").write_text("- a\n- b\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must contain a mapping"):
            Config().persist_app_port(tmp_path, 3000)

    def test_yaml_without_port_key_appended(self, tmp_path: Path):
        target = tmp_path / "config.yml"
        target.write_text("Name: demo", encoding="utf-8")
        Config().persist_app_port(tmp_path, 4321)
        assert target.read_text(encoding="utf-8") == "Name: demo\nPort: 4321\n"

    def test_empty_yaml_gets_port_key(self, tmp_path: Path):
        target = tmp_path / "config.yml"
        target.write_text("", encoding="utf-8")
        Config().persist_app_port(tmp_path, 4321)
        assert target.read_text(encoding="utf-8") == "Port: 4321\n"

    def test_yaml_patched_without_pyyaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config_module, "yaml", None)
        target = tmp_path / "config.yml"
        target.write_text("Port: 3000\nName: demo\n", encoding="utf-8")
        Config().persist_app_port(tmp_path, 4444)
        assert target.read_text(encoding="utf-8") == "Port: 4444\nName: demo\n"
