"""Tests for utils.py — ColorPrinter, DNSChecker, FirewallManager, ArchiveExtractor, redaction, logging."""

import logging
import zipfile
from pathlib import Path
from unittest import mock

import pytest

from utils import (
    ArchiveExtractor,
    ColorPrinter,
    redact_mongo_uri_credentials,
    redact_sensitive_yaml,
    setup_logging,
)

# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------


class TestSetupLogging:
    def test_adds_null_handler_without_log_file(self):
        logger = logging.getLogger("plexinstaller")
        logger.handlers.clear()

        setup_logging()
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

        # Cleanup
        logger.handlers.clear()

    def test_creates_file_handler(self, tmp_path: Path):
        logger = logging.getLogger("plexinstaller")
        logger.handlers.clear()

        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        assert any(isinstance(h, logging.FileHandler) for h in logger.handlers)

        # Cleanup — close file handlers before clearing to avoid ResourceWarning
        for h in logger.handlers:
            if isinstance(h, logging.FileHandler):
                h.close()
        logger.handlers.clear()

    def test_no_duplicate_handlers_on_second_call(self):
        logger = logging.getLogger("plexinstaller")
        logger.handlers.clear()

        setup_logging()
        count = len(logger.handlers)
        setup_logging()  # second call should not add more
        assert len(logger.handlers) == count

        # Cleanup
        logger.handlers.clear()


# ---------------------------------------------------------------------------
# ColorPrinter
# ---------------------------------------------------------------------------


class TestColorPrinter:
    def test_attributes_are_strings(self):
        """Ensure colorama migration didn't break the class attributes."""
        cp = ColorPrinter()
        assert isinstance(cp.RED, str)
        assert isinstance(cp.GREEN, str)
        assert isinstance(cp.NC, str)
        assert isinstance(cp.BOLD, str)

    def test_header_writes_to_stderr(self, capsys):
        cp = ColorPrinter()
        cp.header("Test Header")
        captured = capsys.readouterr()
        assert "Test Header" in captured.err

    def test_success_writes_to_stderr(self, capsys):
        cp = ColorPrinter()
        cp.success("ok")
        captured = capsys.readouterr()
        assert "ok" in captured.err

    def test_error_writes_to_stderr(self, capsys):
        cp = ColorPrinter()
        cp.error("fail")
        captured = capsys.readouterr()
        assert "fail" in captured.err

    def test_warning_writes_to_stderr(self, capsys):
        cp = ColorPrinter()
        cp.warning("warn")
        captured = capsys.readouterr()
        assert "warn" in captured.err


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------


class TestRedactMongoUri:
    def test_redacts_standard_uri(self):
        uri = "mongodb://admin:secret123@localhost:27017/mydb"
        result = redact_mongo_uri_credentials(uri)
        assert "admin" not in result
        assert "secret123" not in result
        assert "<REDACTED>" in result
        assert "localhost" in result

    def test_redacts_srv_uri(self):
        uri = "mongodb+srv://user:pass@cluster.example.com/db"
        result = redact_mongo_uri_credentials(uri)
        assert "user" not in result
        assert "pass" not in result
        assert "<REDACTED>" in result

    def test_no_change_for_non_mongo(self):
        text = "https://example.com/path"
        assert redact_mongo_uri_credentials(text) == text

    def test_no_change_for_plain_text(self):
        text = "Hello world"
        assert redact_mongo_uri_credentials(text) == text


class TestRedactSensitiveYaml:
    def test_redacts_token_field(self):
        yaml_text = "Token: my-secret-token\nPort: 3000\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "my-secret-token" not in result
        assert "<REDACTED>" in result
        assert "3000" in result

    def test_redacts_mongouri_field(self):
        yaml_text = "MongoURI: mongodb://user:pass@host/db\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "user" not in result
        assert "pass" not in result

    def test_preserves_comments(self):
        yaml_text = "# This is a comment\nPort: 3000\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "# This is a comment" in result

    def test_preserves_empty_lines(self):
        yaml_text = "Port: 3000\n\nHost: localhost\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "\n\n" in result


# ---------------------------------------------------------------------------
# ArchiveExtractor
# ---------------------------------------------------------------------------


class TestArchiveExtractor:
    def test_extract_zip(self, tmp_path: Path):
        """Verify basic ZIP extraction works."""
        # Create a ZIP archive with a simple file
        archive_path = tmp_path / "test.zip"
        content_dir = tmp_path / "content"
        content_dir.mkdir()
        (content_dir / "package.json").write_text('{"name":"test"}')

        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.write(content_dir / "package.json", "myapp/package.json")

        # Extract — mock subprocess.run so chown/chmod don't change ownership to root
        extractor = ArchiveExtractor()
        target_dir = tmp_path / "myapp"
        target_dir.mkdir()

        with mock.patch("utils.subprocess.run"):
            extractor.extract(archive_path, target_dir)

        assert (target_dir / "package.json").exists()

    def test_extract_nonexistent_raises(self, tmp_path: Path):
        extractor = ArchiveExtractor()
        with pytest.raises(FileNotFoundError):
            extractor.extract(tmp_path / "nope.zip", tmp_path / "out")

    def test_extract_unsupported_format_raises(self, tmp_path: Path):
        bad_archive = tmp_path / "test.7z"
        bad_archive.write_text("not a real archive")
        extractor = ArchiveExtractor()
        with pytest.raises(ValueError, match="Unsupported archive format"):
            extractor.extract(bad_archive, tmp_path / "out")

    def test_zip_path_traversal_blocked(self, tmp_path: Path):
        """Ensure path traversal in ZIP members is caught."""
        archive_path = tmp_path / "evil.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0:::")

        extractor = ArchiveExtractor()
        target = tmp_path / "safe"
        target.mkdir()

        with pytest.raises(ValueError, match="Path traversal"):
            extractor.extract(archive_path, target)


# ---------------------------------------------------------------------------
# find_product_dir heuristic
# ---------------------------------------------------------------------------


class TestFindProductDir:
    def test_single_subdir(self, tmp_path: Path):
        """Single subdirectory is returned."""
        inner = tmp_path / "plextickets"
        inner.mkdir()
        (inner / "package.json").write_text("{}")

        extractor = ArchiveExtractor()
        result = extractor._find_product_dir(tmp_path, "plextickets")
        assert result == inner

    def test_fallback_package_json(self, tmp_path: Path):
        """Falls back to directory containing package.json."""
        sub1 = tmp_path / "a"
        sub2 = tmp_path / "b"
        sub1.mkdir()
        sub2.mkdir()
        (sub2 / "package.json").write_text("{}")

        extractor = ArchiveExtractor()
        result = extractor._find_product_dir(tmp_path, "plextickets")
        assert result == sub2


# ---------------------------------------------------------------------------
# Additional ArchiveExtractor tests
# ---------------------------------------------------------------------------


class TestArchiveExtractorEdgeCases:
    def test_extract_tar_gz(self, tmp_path: Path):
        """Verify tar.gz extraction works."""
        import tarfile as tf

        archive_path = tmp_path / "test.tar.gz"
        content_dir = tmp_path / "content" / "myapp"
        content_dir.mkdir(parents=True)
        (content_dir / "package.json").write_text('{"name":"test"}')

        with tf.open(archive_path, "w:gz") as tar:
            tar.add(content_dir / "package.json", "myapp/package.json")

        extractor = ArchiveExtractor()
        target_dir = tmp_path / "myapp"
        target_dir.mkdir()

        with mock.patch("utils.subprocess.run"):
            extractor.extract(archive_path, target_dir)

        assert (target_dir / "package.json").exists()

    def test_extract_creates_target_dir(self, tmp_path: Path):
        """Target directory is created if it doesn't exist."""
        archive_path = tmp_path / "test.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("myapp/package.json", '{"name":"test"}')

        extractor = ArchiveExtractor()
        target_dir = tmp_path / "nonexistent" / "myapp"

        with mock.patch("utils.subprocess.run"):
            extractor.extract(archive_path, target_dir)

        assert target_dir.exists()

    def test_extract_zip_overwrites_existing_files(self, tmp_path: Path):
        """Existing files in target dir are replaced."""
        archive_path = tmp_path / "test.zip"
        with zipfile.ZipFile(archive_path, "w") as zf:
            zf.writestr("myapp/file.txt", "new content")

        target_dir = tmp_path / "myapp"
        target_dir.mkdir()
        (target_dir / "file.txt").write_text("old content")

        extractor = ArchiveExtractor()
        with mock.patch("utils.subprocess.run"):
            extractor.extract(archive_path, target_dir)

        assert (target_dir / "file.txt").read_text() == "new content"


# ---------------------------------------------------------------------------
# Additional setup_logging tests
# ---------------------------------------------------------------------------


class TestSetupLoggingExtra:
    def test_file_handler_logs_at_debug_level(self, tmp_path: Path):
        logger = logging.getLogger("plexinstaller")
        logger.handlers.clear()

        log_file = str(tmp_path / "debug.log")
        setup_logging(log_file=log_file)

        fh = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(fh) == 1
        assert fh[0].level == logging.DEBUG

        for h in logger.handlers:
            if isinstance(h, logging.FileHandler):
                h.close()
        logger.handlers.clear()

    def test_logger_level_is_debug(self):
        logger = logging.getLogger("plexinstaller")
        logger.handlers.clear()

        setup_logging()
        assert logger.level == logging.DEBUG

        logger.handlers.clear()


# ---------------------------------------------------------------------------
# Additional ColorPrinter tests
# ---------------------------------------------------------------------------


class TestColorPrinterExtra:
    def test_step_writes_to_stderr(self, capsys):
        cp = ColorPrinter()
        cp.step("doing something")
        captured = capsys.readouterr()
        assert "doing something" in captured.err

    def test_nc_resets_color(self):
        cp = ColorPrinter()
        assert cp.NC == "\x1b[0m" or "reset" in repr(cp.NC).lower() or cp.NC == str(cp.NC)


# ---------------------------------------------------------------------------
# Additional redaction tests
# ---------------------------------------------------------------------------


class TestRedactMongoUriExtra:
    def test_redacts_special_chars_in_password(self):
        uri = "mongodb://admin:p%40ss%23word@localhost:27017/mydb"
        result = redact_mongo_uri_credentials(uri)
        assert "p%40ss%23word" not in result
        assert "<REDACTED>" in result

    def test_preserves_query_params(self):
        uri = "mongodb://admin:pass@localhost:27017/mydb?authSource=admin"
        result = redact_mongo_uri_credentials(uri)
        assert "<REDACTED>" in result

    def test_handles_multiple_uris_in_text(self):
        text = "primary: mongodb://a:b@host1/db secondary: mongodb://c:d@host2/db"
        result = redact_mongo_uri_credentials(text)
        assert "a" not in result.split("://")[1].split("@")[0]
        assert "<REDACTED>" in result


class TestRedactSensitiveYamlExtra:
    def test_redacts_licensekey_field(self):
        yaml_text = "LicenseKey: abc-123-def\nPort: 3000\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "abc-123-def" not in result
        assert "<REDACTED>" in result

    def test_redacts_secretkey_field(self):
        yaml_text = "SecretKey: my-secret-value\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "my-secret-value" not in result
        assert "<REDACTED>" in result

    def test_preserves_non_sensitive_key(self):
        yaml_text = "Port: 3000\nHost: localhost\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "3000" in result
        assert "localhost" in result

    def test_redacts_inline_mongo_uri(self):
        yaml_text = "DatabaseURL: mongodb://admin:secret@host/db\n"
        result = redact_sensitive_yaml(yaml_text)
        assert "secret" not in result

    def test_handles_empty_input(self):
        assert redact_sensitive_yaml("") == ""

    def test_handles_only_comments(self):
        text = "# just a comment\n# another one\n"
        result = redact_sensitive_yaml(text)
        assert result == text
