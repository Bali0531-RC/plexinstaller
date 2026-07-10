#!/usr/bin/env python3
"""
Addon Manager for PlexDevelopment Products
Handles addon installation, removal, configuration, and backup for PlexTickets/PlexStaff
"""

import os
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from utils import (
    ArchiveExtractor,
    ColorPrinter,
    install_staged_directory,
    make_path_private,
    safe_extract_archive,
    validate_path_component,
)

_ARCHIVE_SUFFIXES = (".zip", ".rar", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2", ".tar.xz", ".txz")
_DEFAULT_ARCHIVE_RESULT_LIMIT = 250


def _automatic_temp_roots() -> tuple[Path, ...]:
    """Return existing TEMP roots that automatic discovery must avoid."""
    candidates = [Path(tempfile.gettempdir())]
    candidates.extend(Path(value) for key in ("TEMP", "TMP") if (value := os.environ.get(key)))
    roots: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except (OSError, RuntimeError):
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            seen.add(key)
            roots.append(resolved)
    return tuple(roots)


class AddonManager:
    """Manages addons for PlexTickets and PlexStaff products"""

    def __init__(self):
        self.printer = ColorPrinter()
        # Kept for callers that customize limits through the historical attribute.
        self.extractor = ArchiveExtractor()

    def get_addons_path(self, product_path: Path) -> Path:
        """Get the addons directory path for a product"""
        return product_path / "addons"

    def list_addons(self, product_path: Path) -> list[dict]:
        """
        List all installed addons for a product.

        Returns list of dicts with keys:
        - name: addon folder name
        - path: full path to addon folder
        - has_config: whether config.yml/yaml exists
        - config_path: path to config file (or None)
        """
        addons_path = self.get_addons_path(product_path)

        if not addons_path.exists():
            return []

        addons = []
        for item in sorted(addons_path.iterdir()):
            if item.is_dir() and not item.is_symlink():
                config_path = self._find_addon_config(item)
                addons.append(
                    {"name": item.name, "path": item, "has_config": config_path is not None, "config_path": config_path}
                )

        return addons

    def _find_addon_config(self, addon_path: Path) -> Path | None:
        """Find config.yml or config.yaml in addon folder"""
        for config_name in ["config.yml", "config.yaml"]:
            config_file = addon_path / config_name
            if config_file.exists():
                return config_file
        return None

    def install_addon(self, archive_path: Path, product_path: Path) -> tuple[bool, str, str | None]:
        """
        Install an addon from a ZIP, TAR, or safely validated RAR archive.

        Uses smart extraction to handle both correctly and incorrectly packaged addons:
        - Correct: Archive contains a single folder with addon contents
        - Incorrect: Archive contains loose files without a parent folder

        Returns: (success, message, addon_name or None)
        """
        archive_path = Path(archive_path)
        addons_path = self.get_addons_path(product_path)
        try:
            self.printer.step(f"Extracting {archive_path.name}...")
            addons_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".addon-staging-", dir=addons_path.parent) as temp_dir:
                stage_root = Path(temp_dir)
                make_path_private(stage_root, directory=True)
                extracted_root = stage_root / "extracted"
                safe_extract_archive(
                    archive_path,
                    extracted_root,
                    max_files=self.extractor.max_files,
                    max_bytes=self.extractor.max_bytes,
                )
                addon_name, staged_addon = self._prepare_staged_addon(extracted_root, archive_path)
                validate_path_component(addon_name, label="addon name")
                self._validate_staged_addon(staged_addon)

                final_path = addons_path / addon_name
                self._set_permissions(staged_addon)
                addons_path.mkdir(parents=True, exist_ok=True)
                try:
                    install_staged_directory(staged_addon, final_path)
                except FileExistsError as exc:
                    raise FileExistsError(
                        f"Addon '{addon_name}' already exists. Remove it first or use a different archive name."
                    ) from exc

            config_path = self._find_addon_config(final_path)
            config_msg = f" (config: {config_path.name})" if config_path else " (no config file found)"
            return True, f"Addon '{addon_name}' installed successfully{config_msg}", addon_name
        except Exception as e:
            return False, f"Installation failed: {e}", None

    def _prepare_staged_addon(self, extracted_root: Path, archive_path: Path) -> tuple[str, Path]:
        """Determine the addon root and normalize loose files inside staging."""
        items = list(extracted_root.iterdir())
        if len(items) == 1 and items[0].is_dir() and not items[0].is_symlink():
            validate_path_component(items[0].name, label="addon name")
            return items[0].name, items[0]

        addon_name = archive_path.name
        for suffix in sorted(_ARCHIVE_SUFFIXES, key=len, reverse=True):
            if addon_name.casefold().endswith(suffix):
                addon_name = addon_name[: -len(suffix)]
                break
        for suffix in ["-main", "-master", "-addon", "-v1", "-v2"]:
            if addon_name.lower().endswith(suffix):
                addon_name = addon_name[: -len(suffix)]
        validate_path_component(addon_name, label="addon name")

        target_folder = extracted_root.parent / "normalized"
        target_folder.mkdir()
        for item in items:
            item.rename(target_folder / item.name)
        self.printer.warning(f"Archive was not properly packaged - reorganized into '{addon_name}/' folder")
        return addon_name, target_folder

    @staticmethod
    def _validate_staged_addon(addon_path: Path) -> None:
        """Reject links, special files, and unsafe path components in staging."""
        if addon_path.is_symlink() or not addon_path.is_dir():
            raise ValueError("Addon archive did not contain a safe addon directory")
        for path in addon_path.rglob("*"):
            for part in path.relative_to(addon_path).parts:
                validate_path_component(part, label="addon path component")
            metadata = path.lstat()
            if path.is_symlink():
                raise ValueError(f"Addon links are not allowed: {path.name}")
            if not (path.is_dir() or path.is_file()) or (path.is_file() and metadata.st_nlink != 1):
                raise ValueError(f"Addon special files or hardlinks are not allowed: {path.name}")

    def _set_permissions(self, addon_path: Path):
        """No-op on Windows (permissions handled by NTFS ACLs)"""
        pass

    def addon_exists(self, addon_name: str, product_path: Path) -> bool:
        """Check if an addon with the given name already exists"""
        validate_path_component(addon_name, label="addon name")
        addons_path = self.get_addons_path(product_path)
        addon_folder = addons_path / addon_name
        return addon_folder.exists() and addon_folder.is_dir()

    def backup_addon(self, addon_name: str, product_path: Path) -> tuple[bool, str, Path | None]:
        """
        Create a backup of an addon before removal.

        Returns: (success, message, backup_path or None)
        """
        validate_path_component(addon_name, label="addon name")
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name

        if not addon_path.exists() or addon_path.is_symlink():
            return False, f"Addon '{addon_name}' not found", None

        # Create backup directory
        backup_dir = product_path.parent / "backups" / "addons"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        product_name = product_path.name
        backup_file = backup_dir / f"{product_name}_{addon_name}_addon_{timestamp}.tar.gz"

        try:
            self.printer.step(f"Creating backup of addon '{addon_name}'...")

            fd = os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as backup_stream:
                with tarfile.open(fileobj=backup_stream, mode="w:gz") as tar:
                    tar.add(addon_path, arcname=addon_name)
            make_path_private(backup_file, directory=False)

            size_mb = backup_file.stat().st_size / (1024 * 1024)
            return True, f"Backup created: {backup_file.name} ({size_mb:.2f} MB)", backup_file

        except Exception as e:
            backup_file.unlink(missing_ok=True)
            return False, f"Backup failed: {e}", None

    def remove_addon(self, addon_name: str, product_path: Path, backup_first: bool = True) -> tuple[bool, str]:
        """
        Remove an addon from a product.

        Args:
            addon_name: Name of the addon folder to remove
            product_path: Path to the product installation
            backup_first: Whether to create a backup before removal

        Returns: (success, message)
        """
        validate_path_component(addon_name, label="addon name")
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name

        if not addon_path.exists() or addon_path.is_symlink():
            return False, f"Addon '{addon_name}' not found"

        # Create backup if requested
        if backup_first:
            success, msg, backup_path = self.backup_addon(addon_name, product_path)
            if not success:
                return False, f"Could not create backup: {msg}"
            self.printer.success(msg)

        try:
            shutil.rmtree(addon_path)
            return True, f"Addon '{addon_name}' removed successfully"
        except Exception as e:
            return False, f"Failed to remove addon: {e}"

    def validate_yaml(self, config_path: Path) -> tuple[bool, str | None]:
        """
        Validate YAML syntax of a config file.

        Returns: (is_valid, error_message or None)
        """
        try:
            with open(config_path, encoding="utf-8") as f:
                yaml.safe_load(f)
            return True, None
        except yaml.YAMLError as e:
            # Extract line number if available
            error_msg = str(e)
            if hasattr(e, "problem_mark"):
                mark = e.problem_mark
                problem = getattr(e, "problem", "")
                error_msg = f"Line {mark.line + 1}, column {mark.column + 1}: {problem}"
            return False, error_msg
        except Exception as e:
            return False, str(e)

    def get_addon_config_path(self, addon_name: str, product_path: Path) -> Path | None:
        """Get the config file path for an addon"""
        validate_path_component(addon_name, label="addon name")
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name

        if not addon_path.exists() or addon_path.is_symlink():
            return None

        return self._find_addon_config(addon_path)

    def find_addon_archive(self, search_dirs: list[Path] | None = None) -> list[Path]:
        """
        Find addon archives in common directories.

        Returns list of found archive paths.
        """
        automatic_search = search_dirs is None
        roots = (
            [Path.home() / "Downloads", Path.home() / "Desktop", Path.cwd()] if automatic_search else search_dirs or []
        )

        archives: list[Path] = []
        seen_paths: set[str] = set()
        seen_roots: set[str] = set()
        temp_roots = _automatic_temp_roots() if automatic_search else ()
        for search_dir in roots:
            try:
                resolved_root = Path(search_dir).resolve()
            except (OSError, RuntimeError):
                continue
            root_key = os.path.normcase(str(resolved_root))
            if (
                root_key in seen_roots
                or not resolved_root.is_dir()
                or any(resolved_root == temp_root or temp_root in resolved_root.parents for temp_root in temp_roots)
            ):
                continue
            seen_roots.add(root_key)

            candidates = resolved_root.iterdir() if automatic_search else resolved_root.rglob("*")
            for archive in candidates:
                if not archive.is_file() or not archive.name.casefold().endswith(_ARCHIVE_SUFFIXES):
                    continue
                try:
                    resolved = archive.resolve()
                except (OSError, RuntimeError):
                    continue
                path_key = os.path.normcase(str(resolved))
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                archives.append(resolved)
                if len(archives) >= _DEFAULT_ARCHIVE_RESULT_LIMIT:
                    return sorted(archives, key=lambda path: path.name.casefold())

        return sorted(archives, key=lambda path: path.name.casefold())

    def list_addon_backups(self, product_path: Path) -> list[dict]:
        """
        List all addon backups for a product.

        Returns list of dicts with keys:
        - path: backup file path
        - addon_name: name of the addon
        - timestamp: backup timestamp
        - size_mb: size in MB
        """
        backup_dir = product_path.parent / "backups" / "addons"

        if not backup_dir.exists():
            return []

        backups = []
        product_name = product_path.name

        for backup_file in sorted(
            backup_dir.glob(f"{product_name}_*_addon_*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True
        ):
            try:
                # Parse the full suffix so .tar.gz and names containing `_addon_` work.
                basename = backup_file.name.removesuffix(".tar.gz")
                prefix, separator, timestamp_str = basename.rpartition("_addon_")
                product_prefix = f"{product_name}_"
                if separator and prefix.startswith(product_prefix):
                    addon_name = prefix[len(product_prefix) :]
                    validate_path_component(addon_name, label="addon name")

                    # Parse timestamp
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    except ValueError:
                        timestamp = datetime.fromtimestamp(backup_file.stat().st_mtime)

                    size_mb = backup_file.stat().st_size / (1024 * 1024)

                    backups.append(
                        {"path": backup_file, "addon_name": addon_name, "timestamp": timestamp, "size_mb": size_mb}
                    )
            except Exception:
                continue

        return backups
