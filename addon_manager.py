#!/usr/bin/env python3
"""
Addon Manager for PlexDevelopment Products
Handles addon installation, removal, configuration, and backup for PlexTickets/PlexStaff
"""

import os
import shutil
import tarfile
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Tuple

import yaml

from utils import ColorPrinter, ArchiveExtractor


class AddonManager:
    """Manages addons for PlexTickets and PlexStaff products"""
    
    def __init__(self):
        self.printer = ColorPrinter()
        self.extractor = ArchiveExtractor()
    
    def get_addons_path(self, product_path: Path) -> Path:
        """Get the addons directory path for a product"""
        return product_path / "addons"
    
    def list_addons(self, product_path: Path) -> List[Dict]:
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
            if item.is_dir():
                config_path = self._find_addon_config(item)
                addons.append({
                    'name': item.name,
                    'path': item,
                    'has_config': config_path is not None,
                    'config_path': config_path
                })
        
        return addons
    
    def _find_addon_config(self, addon_path: Path) -> Optional[Path]:
        """Find config.yml or config.yaml in addon folder"""
        for config_name in ['config.yml', 'config.yaml']:
            config_file = addon_path / config_name
            if config_file.exists():
                return config_file
        return None
    
    def install_addon(self, archive_path: Path, product_path: Path) -> Tuple[bool, str, Optional[str]]:
        """
        Install an addon from a zip/rar archive.
        
        Uses smart extraction to handle both correctly and incorrectly packaged addons:
        - Correct: Archive contains a single folder with addon contents
        - Incorrect: Archive contains loose files without a parent folder
        
        Returns: (success, message, addon_name or None)
        """
        addons_path = self.get_addons_path(product_path)
        addons_path.mkdir(parents=True, exist_ok=True)
        
        # Snapshot before extraction
        before_items = set(addons_path.iterdir()) if addons_path.exists() else set()
        
        try:
            # Extract directly to addons folder
            self.printer.step(f"Extracting {archive_path.name}...")
            self._extract_archive_to(archive_path, addons_path)
            
            # Snapshot after extraction
            after_items = set(addons_path.iterdir())
            new_items = after_items - before_items
            
            if not new_items:
                return False, "No files were extracted from the archive", None
            
            # Analyze what was extracted
            addon_name, final_path = self._handle_extracted_items(
                new_items, addons_path, archive_path
            )
            
            if addon_name is None:
                return False, "Failed to determine addon name from archive", None
            
            # Check for collision (addon already exists)
            # This check is already done implicitly if the folder existed
            
            # Set proper permissions
            self._set_permissions(final_path)
            
            # Check for config file
            config_path = self._find_addon_config(final_path)
            config_msg = f" (config: {config_path.name})" if config_path else " (no config file found)"
            
            return True, f"Addon '{addon_name}' installed successfully{config_msg}", addon_name
            
        except FileExistsError as e:
            return False, str(e), None
        except Exception as e:
            # Clean up any partially extracted files
            self._cleanup_new_items(addons_path, before_items)
            return False, f"Installation failed: {e}", None
    
    def _extract_archive_to(self, archive_path: Path, target_dir: Path):
        """Extract archive contents to target directory"""
        import zipfile
        import subprocess
        
        if archive_path.suffix.lower() == '.zip':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Path traversal protection
                for member in zip_ref.namelist():
                    member_path = (target_dir / member).resolve()
                    if not str(member_path).startswith(str(target_dir.resolve())):
                        raise ValueError(f"Path traversal attempt detected: {member}")
                zip_ref.extractall(target_dir)
        elif archive_path.suffix.lower() == '.rar':
            if not shutil.which('unrar'):
                raise FileNotFoundError("unrar command not found. Install it with: apt install unrar")
            subprocess.run([
                'unrar', 'x', '-o+', str(archive_path), str(target_dir) + '/'
            ], check=True, timeout=300)
        else:
            raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
    
    def _handle_extracted_items(
        self, 
        new_items: set, 
        addons_path: Path, 
        archive_path: Path
    ) -> Tuple[Optional[str], Optional[Path]]:
        """
        Handle extracted items and determine the final addon folder.
        
        Returns: (addon_name, final_addon_path)
        """
        new_items_list = list(new_items)
        
        # Case 1: Single folder extracted - this is a correctly packaged addon
        if len(new_items_list) == 1 and new_items_list[0].is_dir():
            addon_folder = new_items_list[0]
            addon_name = addon_folder.name
            
            # Check if this addon already existed (collision)
            # Since we're extracting to addons_path, if it exists, the extraction would have
            # created or overwritten it. We need to check if there was already a folder
            # with this name that we're replacing.
            return addon_name, addon_folder
        
        # Case 2: Multiple items or loose files - incorrectly packaged addon
        # Create a folder based on archive name
        addon_name = archive_path.stem  # e.g., "TicketStats" from "TicketStats.zip"
        # Remove common suffixes that might be in the name
        for suffix in ['-main', '-master', '-addon', '-v1', '-v2']:
            if addon_name.lower().endswith(suffix):
                addon_name = addon_name[:-len(suffix)]
        
        target_folder = addons_path / addon_name
        
        # Check for collision
        if target_folder.exists() and target_folder not in new_items:
            raise FileExistsError(
                f"Addon '{addon_name}' already exists. Remove it first or use a different archive name."
            )
        
        # Create the target folder if it doesn't exist
        target_folder.mkdir(exist_ok=True)
        
        # Move all new items into the target folder
        for item in new_items_list:
            if item == target_folder:
                continue  # Skip if it's our target folder
            dest = target_folder / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
        
        self.printer.warning(f"Archive was not properly packaged - reorganized into '{addon_name}/' folder")
        
        return addon_name, target_folder
    
    def _cleanup_new_items(self, addons_path: Path, before_items: set):
        """Clean up any items created during a failed extraction"""
        try:
            current_items = set(addons_path.iterdir()) if addons_path.exists() else set()
            new_items = current_items - before_items
            for item in new_items:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
        except Exception:
            pass  # Best effort cleanup
    
    def _set_permissions(self, addon_path: Path):
        """Set proper permissions on addon files"""
        import subprocess
        try:
            subprocess.run(['chown', '-R', 'root:root', str(addon_path)], timeout=60)
            subprocess.run(['find', str(addon_path), '-type', 'd', '-exec', 'chmod', '755', '{}', ';'], timeout=60)
            subprocess.run(['find', str(addon_path), '-type', 'f', '-exec', 'chmod', '644', '{}', ';'], timeout=60)
        except Exception:
            pass  # Best effort
    
    def addon_exists(self, addon_name: str, product_path: Path) -> bool:
        """Check if an addon with the given name already exists"""
        addons_path = self.get_addons_path(product_path)
        addon_folder = addons_path / addon_name
        return addon_folder.exists() and addon_folder.is_dir()
    
    def backup_addon(self, addon_name: str, product_path: Path) -> Tuple[bool, str, Optional[Path]]:
        """
        Create a backup of an addon before removal.
        
        Returns: (success, message, backup_path or None)
        """
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name
        
        if not addon_path.exists():
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
            
            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(addon_path, arcname=addon_name)
            
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            return True, f"Backup created: {backup_file.name} ({size_mb:.2f} MB)", backup_file
            
        except Exception as e:
            return False, f"Backup failed: {e}", None
    
    def remove_addon(self, addon_name: str, product_path: Path, backup_first: bool = True) -> Tuple[bool, str]:
        """
        Remove an addon from a product.
        
        Args:
            addon_name: Name of the addon folder to remove
            product_path: Path to the product installation
            backup_first: Whether to create a backup before removal
            
        Returns: (success, message)
        """
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name
        
        if not addon_path.exists():
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
    
    def validate_yaml(self, config_path: Path) -> Tuple[bool, Optional[str]]:
        """
        Validate YAML syntax of a config file.
        
        Returns: (is_valid, error_message or None)
        """
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            return True, None
        except yaml.YAMLError as e:
            # Extract line number if available
            error_msg = str(e)
            if hasattr(e, 'problem_mark'):
                mark = e.problem_mark
                error_msg = f"Line {mark.line + 1}, column {mark.column + 1}: {e.problem}"
            return False, error_msg
        except Exception as e:
            return False, str(e)
    
    def get_addon_config_path(self, addon_name: str, product_path: Path) -> Optional[Path]:
        """Get the config file path for an addon"""
        addons_path = self.get_addons_path(product_path)
        addon_path = addons_path / addon_name
        
        if not addon_path.exists():
            return None
        
        return self._find_addon_config(addon_path)
    
    def find_addon_archive(self, search_dirs: List[Path] = None) -> List[Path]:
        """
        Find addon archives in common directories.
        
        Returns list of found archive paths.
        """
        if search_dirs is None:
            search_dirs = [
                Path.home(),
                Path("/root"),
                Path("/tmp"),
                Path("/var/tmp"),
                Path.cwd()
            ]
        
        archives = []
        seen_paths = set()
        patterns = ["*.zip", "*.rar"]
        
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
    
    def list_addon_backups(self, product_path: Path) -> List[Dict]:
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
        
        for backup_file in sorted(backup_dir.glob(f"{product_name}_*_addon_*.tar.gz"), 
                                  key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                # Parse filename: product_addonname_addon_timestamp.tar.gz
                parts = backup_file.stem.split('_addon_')
                if len(parts) >= 2:
                    prefix = parts[0]
                    timestamp_str = parts[1]
                    
                    # Extract addon name (remove product prefix)
                    addon_name = prefix.replace(f"{product_name}_", "", 1)
                    
                    # Parse timestamp
                    try:
                        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    except ValueError:
                        timestamp = datetime.fromtimestamp(backup_file.stat().st_mtime)
                    
                    size_mb = backup_file.stat().st_size / (1024 * 1024)
                    
                    backups.append({
                        'path': backup_file,
                        'addon_name': addon_name,
                        'timestamp': timestamp,
                        'size_mb': size_mb
                    })
            except Exception:
                continue
        
        return backups
