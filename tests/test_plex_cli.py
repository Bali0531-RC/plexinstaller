"""Windows CLI safety and compatibility contracts."""

from pathlib import Path
from unittest import mock

import plex_cli


def _app(root: Path, name: str, config: str = "Port: 3000\n") -> Path:
    app = root / name
    app.mkdir(parents=True)
    (app / "package.json").write_text("{}")
    (app / "config.yml").write_text(config)
    return app


def test_resolve_current_and_legacy_drako_aliases(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    _app(tmp_path, "plexstore_prod")
    assert plex_cli.resolve_app_instance("drakostore_prod") == "plexstore_prod"
    assert plex_cli.resolve_app_instance("plexstore_prod") == "plexstore_prod"


def test_debug_redaction_handles_midline_and_uri_credentials():
    source = "broken { token: abc123\nconnect=https://user:pass@example.com/path\nAuthorization: Bearer xyz"
    redacted = plex_cli.redact_debug_text(source)
    assert "abc123" not in redacted
    assert "user:pass" not in redacted
    assert "Bearer xyz" not in redacted
    assert plex_cli.debug_bundle_is_safe(redacted) is True
    assert plex_cli.debug_bundle_is_safe("prefix { token: leaked") is False


def test_debug_upload_requires_explicit_consent(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    _app(tmp_path, "plextickets", "Token: secret\n")
    fake_requests = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "requests", fake_requests)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    assert plex_cli.debug_app("plextickets") == 0
    fake_requests.post.assert_not_called()


def test_info_and_success_use_stdout(capsys):
    plex_cli.print_info("info")
    plex_cli.print_success("ok")
    plex_cli.print_error("bad")
    captured = capsys.readouterr()
    assert "info" in captured.out and "ok" in captured.out
    assert "bad" in captured.err


def test_setupdomain_reprompts_persists_and_rolls_back_on_ssl_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(plex_cli, "INSTALL_DIR", tmp_path)
    _app(tmp_path, "drakostore", "Port: 3003\n")
    monkeypatch.setattr(plex_cli, "_is_admin", lambda: True)
    answers = iter(["70000", "3103", "store.example.com", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    config = mock.MagicMock()
    monkeypatch.setattr(plex_cli, "Config", mock.MagicMock(return_value=config))
    dns = mock.MagicMock()
    dns.check.return_value = True
    firewall = mock.MagicMock()
    firewall.open_port.return_value = True
    nginx = mock.MagicMock()
    ssl = mock.MagicMock()
    ssl.setup.side_effect = RuntimeError("certificate failed")

    with (
        mock.patch("utils.DNSChecker", return_value=dns),
        mock.patch("utils.FirewallManager", return_value=firewall),
        mock.patch("utils.NginxManager", return_value=nginx),
        mock.patch("utils.SSLManager", return_value=ssl),
    ):
        assert plex_cli.tool_setupdomain("drakostore") == 1

    config.persist_app_port.assert_called_once_with(tmp_path / "drakostore", 3103)
    firewall.open_port.assert_called_once_with(3103, "drakostore")
    nginx.remove.assert_called_once_with("store.example.com")
    firewall.close_port.assert_called_once_with(3103, "drakostore")
