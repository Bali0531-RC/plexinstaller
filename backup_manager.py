"""
Backup creation, listing, restoration, and deletion for installed products.

Extracted from PlexInstaller to keep domain logic isolated and testable.
"""

import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from utils import (
    ColorPrinter,
    SystemdManager,
    clear_terminal,
    make_path_private,
    safe_extract_tar,
    validate_path_component,
)

_BACKUP_NAME_RE = re.compile(r"^(?P<product>[^/\\]+)_backup_(?P<timestamp>\d{8}_\d{6})\.tar\.gz$")


class BackupManager:
    """Create, list, restore, and delete product backups."""

    def __init__(
        self,
        printer: ColorPrinter,
        systemd: SystemdManager,
        install_dir: Path,
    ):
        self.printer = printer
        self.systemd = systemd
        self.install_dir = install_dir
        self.backup_dir = install_dir / "backups"

    # ------------------------------------------------------------------
    # Menu entry-point
    # ------------------------------------------------------------------

    def menu(self):
        """Interactive backup management menu."""
        while True:
            clear_terminal()
            self.printer.header("Backup Management")
            print(f"Backup Location: {self.backup_dir}")
            print("---")

            print("\n1) Create backup of a product")
            print("2) List available backups")
            print("3) Restore product from backup")
            print("4) Delete backup")
            print("0) Return to Main Menu")

            choice = input("\nEnter your choice: ").strip()

            if choice == "0":
                break
            elif choice == "1":
                self.create_backup()
            elif choice == "2":
                self.list_backups()
            elif choice == "3":
                self.restore_backup()
            elif choice == "4":
                self.delete_backup()
            else:
                self.printer.error("Invalid choice")

            if choice != "0":
                input("\nPress Enter to continue...")

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_backup(self):
        """Prompt for product selection and create a backup."""
        products = [d for d in self.install_dir.iterdir() if d.is_dir() and d.name != "backups"]

        if not products:
            self.printer.warning("No installed products found to back up")
            return

        print("\nSelect product to backup:")
        for i, product_dir in enumerate(products, 1):
            print(f"{i}) {product_dir.name}")

        choice = input(f"\nEnter choice (1-{len(products)}): ").strip()

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(products):
                self.backup_product(products[idx].name)
            else:
                self.printer.error("Invalid choice")
        except ValueError:
            self.printer.error("Invalid choice")

    def backup_product(self, product: str):
        """Backup a specific product (stop → tar.gz → restart)."""
        validate_path_component(product, label="product name")
        install_path = self.install_dir / product
        if not install_path.is_dir() or install_path.is_symlink():
            self.printer.error(f"Product installation not found: {product}")
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"{product}_backup_{timestamp}.tar.gz"

        self.printer.step(f"Creating backup of {product}...")

        service_name = f"plex-{product}"
        initial_status = self.systemd.get_status(service_name)
        was_running = self._service_status_is_running(initial_status)
        if not was_running and not self._service_status_is_stopped(initial_status):
            self.printer.error(f"Cannot determine service state for {service_name}; backup aborted")
            return

        if was_running:
            self.printer.step("Stopping service...")
            self.systemd.stop(service_name)
            stopped_status = self.systemd.get_status(service_name)
            if not self._service_status_is_stopped(stopped_status):
                self.printer.error(f"Service {service_name} did not stop; backup aborted")
                if not self._service_status_is_running(stopped_status):
                    self.systemd.start(service_name)
                return

        try:
            fd = os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as backup_stream:
                with tarfile.open(fileobj=backup_stream, mode="w:gz") as tar:
                    tar.add(install_path, arcname=product)
            make_path_private(backup_file, directory=False)

            size_mb = backup_file.stat().st_size / (1024 * 1024)
            self.printer.success(f"Backup created: {backup_file.name}")
            self.printer.step(f"Size: {size_mb:.2f} MB")

        except Exception as e:
            backup_file.unlink(missing_ok=True)
            self.printer.error(f"Backup failed: {e}")
        finally:
            if was_running:
                self.printer.step("Restarting service...")
                self.systemd.start(service_name)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_backups(self) -> list[Path]:
        """List available backups and return the sorted list."""
        if not self.backup_dir.exists():
            self.printer.warning("No backups directory found")
            return []

        backups = sorted(
            (path for path in self.backup_dir.glob("*.tar.gz") if self._try_parse_backup_name(path) is not None),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        if not backups:
            self.printer.warning("No backups found")
            return []

        print("\nAvailable Backups:")
        print(f"{'ID':<4} {'Product':<15} {'Date':<20} {'Size':<10}")
        print("-" * 60)

        for i, backup_file in enumerate(backups, 1):
            size_mb = backup_file.stat().st_size / (1024 * 1024)
            product, timestamp = self._parse_backup_name(backup_file)
            date_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            print(f"{i:<4} {product:<15} {date_str:<20} {size_mb:>8.2f} MB")

        return backups

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore_backup(self):
        """Interactive restore: list → select → confirm → restore."""
        if not self.backup_dir.exists():
            self.printer.warning("No backups directory found")
            return

        backups = sorted(
            (path for path in self.backup_dir.glob("*.tar.gz") if self._try_parse_backup_name(path) is not None),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        if not backups:
            self.printer.warning("No backups found")
            return

        self.list_backups()

        choice = input(f"\nSelect backup ID to restore (1-{len(backups)}): ").strip()

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                selected_backup = backups[idx]
                product, _timestamp = self._parse_backup_name(selected_backup)

                self.printer.warning(f"This will restore {product} from backup.")
                self.printer.warning("Current installation will be replaced!")

                confirm = input("Continue? (y/n): ").strip().lower()
                if confirm == "y":
                    self.restore_from_backup(selected_backup, product)
                else:
                    self.printer.step("Restore cancelled")
            else:
                self.printer.error("Invalid backup ID")
        except ValueError:
            self.printer.error("Invalid input")

    def restore_from_backup(self, backup_file: Path, product: str):
        """Stage, validate, and transactionally restore a product backup."""
        validate_path_component(product, label="product name")
        backup_file = Path(backup_file)
        try:
            backup_product, _timestamp = self._parse_backup_name(backup_file)
        except ValueError as exc:
            self.printer.error(f"Restore failed: {exc}")
            return
        if backup_product != product:
            self.printer.error(f"Restore failed: backup is for '{backup_product}', not '{product}'")
            return

        install_path = self.install_dir / product
        service_name = f"plex-{product}"
        initial_status = self.systemd.get_status(service_name)
        was_running = self._service_status_is_running(initial_status)
        if not was_running and not self._service_status_is_stopped(initial_status):
            self.printer.error(f"Restore failed: cannot determine service state for {service_name}")
            return
        rollback_path: Path | None = None
        old_install_moved = False
        new_install_published = False
        service_stopped = False

        self.install_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.printer.step(f"Restoring from {backup_file.name}...")
            with tempfile.TemporaryDirectory(prefix=f".{product}.restore-", dir=self.install_dir) as temp_dir:
                stage_root = Path(temp_dir)
                make_path_private(stage_root, directory=True)
                extraction_root = stage_root / "archive"
                safe_extract_tar(backup_file, extraction_root, expected_top_level=product)
                staged_product = extraction_root / product
                self._validate_staged_product(staged_product)

                if was_running:
                    self.printer.step("Stopping service...")
                    self.systemd.stop(service_name)
                    stopped_status = self.systemd.get_status(service_name)
                    if not self._service_status_is_stopped(stopped_status):
                        raise RuntimeError(f"Service {service_name} did not stop; restore aborted")
                    service_stopped = True

                if install_path.exists() or install_path.is_symlink():
                    self.printer.step("Preserving current installation for rollback...")
                    rollback_path = Path(tempfile.mkdtemp(prefix=f".{product}.rollback-", dir=self.install_dir))
                    rollback_path.rmdir()
                    install_path.rename(rollback_path)
                    old_install_moved = True

                if install_path.exists() or install_path.is_symlink():
                    raise FileExistsError(f"Restore target already exists: {install_path}")
                staged_product.rename(install_path)
                new_install_published = True

            if rollback_path is not None:
                try:
                    shutil.rmtree(rollback_path)
                except OSError as exc:
                    self.printer.warning(f"Could not remove rollback copy {rollback_path}: {exc}")
            self.printer.success(f"Restore of {product} complete")

        except Exception as e:
            self.printer.error(f"Restore failed: {e}")

            if old_install_moved and rollback_path is not None and rollback_path.exists():
                self.printer.warning("Attempting to restore previous installation...")
                self._remove_path(install_path)
                if not (install_path.exists() or install_path.is_symlink()):
                    rollback_path.rename(install_path)
                else:
                    self.printer.error(f"Previous installation remains preserved at {rollback_path}")
            elif new_install_published:
                self._remove_path(install_path)
        finally:
            if service_stopped:
                self.printer.step("Starting service...")
                self.systemd.start(service_name)

    @staticmethod
    def _service_status_is_running(status: str) -> bool:
        return status.strip().casefold() in {"active", "running"}

    @staticmethod
    def _service_status_is_stopped(status: str) -> bool:
        return status.strip().casefold() in {"inactive", "stopped"}

    @staticmethod
    def _parse_backup_name(backup_file: Path) -> tuple[str, datetime]:
        match = _BACKUP_NAME_RE.fullmatch(Path(backup_file).name)
        if match is None:
            raise ValueError(f"Invalid backup filename: {Path(backup_file).name}")
        product = validate_path_component(match.group("product"), label="product name")
        try:
            timestamp = datetime.strptime(match.group("timestamp"), "%Y%m%d_%H%M%S")
        except ValueError as exc:
            raise ValueError(f"Invalid backup timestamp: {Path(backup_file).name}") from exc
        return product, timestamp

    @classmethod
    def _try_parse_backup_name(cls, backup_file: Path) -> tuple[str, datetime] | None:
        try:
            return cls._parse_backup_name(backup_file)
        except ValueError:
            return None

    @staticmethod
    def _validate_staged_product(product_path: Path) -> None:
        if product_path.is_symlink() or not product_path.is_dir():
            raise ValueError("Backup top-level product is not a safe directory")
        for path in product_path.rglob("*"):
            metadata = path.lstat()
            if path.is_symlink():
                raise ValueError(f"Backup links are not allowed: {path.name}")
            if not (path.is_dir() or path.is_file()) or (path.is_file() and metadata.st_nlink != 1):
                raise ValueError(f"Backup special files or hardlinks are not allowed: {path.name}")

    @staticmethod
    def _remove_path(path: Path) -> None:
        if not (path.exists() or path.is_symlink()):
            return
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_backup(self):
        """Interactive backup deletion."""
        if not self.backup_dir.exists():
            self.printer.warning("No backups directory found")
            return

        backups = sorted(
            (path for path in self.backup_dir.glob("*.tar.gz") if self._try_parse_backup_name(path) is not None),
            key=lambda x: x.stat().st_mtime,
            reverse=True,
        )

        if not backups:
            self.printer.warning("No backups found")
            return

        self.list_backups()

        choice = input(f"\nSelect backup ID to DELETE (1-{len(backups)}): ").strip()

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(backups):
                selected_backup = backups[idx]

                self.printer.warning(f"You are about to permanently delete: {selected_backup.name}")
                confirm = input("Are you absolutely sure? (y/n): ").strip().lower()

                if confirm == "y":
                    selected_backup.unlink()
                    self.printer.success("Backup deleted successfully")
                else:
                    self.printer.step("Deletion cancelled")
            else:
                self.printer.error("Invalid backup ID")
        except ValueError:
            self.printer.error("Invalid input")
