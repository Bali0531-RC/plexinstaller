#!/usr/bin/env python3
"""
Addon Manager for PlexDevelopment Products
Handles addon installation, removal, configuration, and backup for PlexTickets/PlexStaff
"""

import json
import os
import pwd
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from utils import ColorPrinter, SystemdManager, install_staged_directory, safe_extract_archive, validate_path_component


class AddonManager:
    """Manages addons for PlexTickets and PlexStaff products"""

    def __init__(self):
        self.printer = ColorPrinter()

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
        Install an addon from a ZIP or TAR archive.

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
                extracted_root = Path(temp_dir) / "extracted"
                safe_extract_archive(archive_path, extracted_root)
                addon_name, staged_addon = self._prepare_staged_addon(extracted_root, archive_path)
                validate_path_component(addon_name, label="addon name")

                final_path = addons_path / addon_name
                if final_path.exists() or final_path.is_symlink():
                    raise FileExistsError(
                        f"Addon '{addon_name}' already exists. Remove it first or use a different archive name."
                    )

                self._set_permissions(staged_addon, product_path=product_path)
                addons_path.mkdir(parents=True, exist_ok=True)
                if final_path.exists() or final_path.is_symlink():
                    raise FileExistsError(
                        f"Addon '{addon_name}' already exists. Remove it first or use a different archive name."
                    )
                install_staged_directory(staged_addon, final_path)

            config_path = self._find_addon_config(final_path)
            config_msg = f" (config: {config_path.name})" if config_path else " (no config file found)"
            return True, f"Addon '{addon_name}' installed successfully{config_msg}", addon_name
        except Exception as e:
            return False, f"Installation failed: {e}", None

    def _prepare_staged_addon(self, extracted_root: Path, archive_path: Path) -> tuple[str, Path]:
        """Normalize extracted contents inside the private staging directory."""
        items = list(extracted_root.iterdir())
        if len(items) == 1 and items[0].is_dir():
            return items[0].name, items[0]

        addon_name = archive_path.name
        while True:
            suffix = Path(addon_name).suffix.lower()
            if suffix not in {".zip", ".tar", ".gz", ".bz2", ".xz", ".tgz", ".tbz2", ".txz"}:
                break
            addon_name = addon_name[: -len(suffix)]
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
    def _service_owner(product_path: Path | None) -> str:
        """Return the verified isolated owner recorded for a product."""
        if product_path is None:
            return "root"
        manifest = product_path / ".plexinstaller-resources.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            expected = SystemdManager.service_user_name(product_path.name)
            user = data.get("service_user")
            if data.get("service_isolated") is True and isinstance(user, str) and user == expected:
                pwd.getpwnam(user)
                return user
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass
        return "root"

    def _set_permissions(self, addon_path: Path, *, product_path: Path | None = None):
        """Set proper permissions on addon files"""
        import subprocess

        owner = self._service_owner(product_path)
        subprocess.run(["chown", "-R", f"{owner}:{owner}", str(addon_path)], check=True, timeout=60)
        subprocess.run(
            ["find", str(addon_path), "-type", "d", "-exec", "chmod", "750", "{}", ";"],
            check=True,
            timeout=60,
        )
        for path in addon_path.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            sensitive = path.name.lower() in {"config.yml", "config.yaml", "config.json", ".env"}
            executable = bool(path.stat().st_mode & 0o111) or path.suffix.lower() in {".sh", ".py"}
            os.chmod(path, 0o600 if sensitive else 0o750 if executable else 0o640)

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
        if search_dirs is None:
            search_dirs = [Path.home(), Path("/root"), Path("/tmp"), Path("/var/tmp"), Path.cwd()]

        archives = []
        seen_paths = set()
        patterns = ["*.zip", "*.tar", "*.tar.gz", "*.tgz", "*.tar.bz2", "*.tbz2", "*.tar.xz", "*.txz"]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            for pattern in patterns:
                for archive in search_dir.rglob(pattern):
                    resolved = archive.resolve()
                    if str(resolved) in seen_paths:
                        continue
                    seen_paths.add(str(resolved))
                    archives.append(resolved)

        return sorted(archives, key=lambda x: x.name.lower())

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
                # Parse filename: product_addonname_addon_timestamp.tar.gz
                basename = backup_file.name.removesuffix(".tar.gz")
                marker = "_addon_"
                prefix, separator, timestamp_str = basename.rpartition(marker)
                if separator:
                    # Extract addon name (remove product prefix)
                    addon_name = prefix.removeprefix(f"{product_name}_")

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
