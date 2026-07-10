"""
Backup creation, listing, restoration, and deletion for installed products.

Extracted from PlexInstaller to keep domain logic isolated and testable.
"""

import json
import os
import pwd
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from utils import ColorPrinter, SystemdManager, safe_extract_tar, validate_path_component


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
            os.system("clear" if os.name != "nt" else "cls")
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
        self.backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"{product}_backup_{timestamp}.tar.gz"

        self.printer.step(f"Creating backup of {product}...")

        service_name = f"plex-{product}"
        was_running = self.systemd.get_status(service_name).strip().lower() == "active"

        if was_running:
            self.printer.step("Stopping service...")
            self.systemd.stop(service_name)

        try:
            fd = os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as backup_stream:
                with tarfile.open(fileobj=backup_stream, mode="w:gz") as tar:
                    tar.add(install_path, arcname=product)

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
            self.backup_dir.glob("*.tar.gz"),
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
            mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)
            date_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
            product = self._product_from_backup_name(backup_file)
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
            self.backup_dir.glob("*.tar.gz"),
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
                product = self._product_from_backup_name(selected_backup)

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
        """Safely stage and transactionally restore a specific product backup."""
        validate_path_component(product, label="product name")
        backup_file = Path(backup_file)
        install_path = self.install_dir / product
        service_name = f"plex-{product}"
        was_running = self.systemd.get_status(service_name).strip().lower() == "active"
        rollback_path: Path | None = None
        old_install_moved = False
        new_install_published = False
        service_stop_attempted = False

        self.install_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.printer.step(f"Restoring from {backup_file.name}...")
            with tempfile.TemporaryDirectory(prefix=f".{product}.restore-", dir=self.install_dir) as temp_dir:
                extraction_root = Path(temp_dir) / "archive"
                safe_extract_tar(backup_file, extraction_root, expected_top_level=product)
                staged_product = extraction_root / product

                self.printer.step("Setting permissions...")
                self._set_permissions(staged_product)

                if was_running:
                    self.printer.step("Stopping service...")
                    service_stop_attempted = True
                    self.systemd.stop(service_name)
                    if self.systemd.get_status(service_name).strip().lower() == "active":
                        raise RuntimeError(f"Service {service_name} did not stop; restore aborted")

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
                if install_path.exists() or install_path.is_symlink():
                    try:
                        if install_path.is_dir() and not install_path.is_symlink():
                            shutil.rmtree(install_path)
                        else:
                            install_path.unlink()
                    except OSError as cleanup_error:
                        self.printer.error(f"Could not clear failed restore target: {cleanup_error}")
                if not (install_path.exists() or install_path.is_symlink()):
                    rollback_path.rename(install_path)
                else:
                    self.printer.error(f"Previous installation remains preserved at {rollback_path}")
            elif new_install_published and (install_path.exists() or install_path.is_symlink()):
                if install_path.is_dir() and not install_path.is_symlink():
                    shutil.rmtree(install_path)
                else:
                    install_path.unlink()
        finally:
            if service_stop_attempted:
                self.printer.step("Starting service...")
                self.systemd.start(service_name)

    @staticmethod
    def _product_from_backup_name(backup_file: Path) -> str:
        basename = backup_file.name.removesuffix(".tar.gz")
        product, separator, _timestamp = basename.rpartition("_backup_")
        if not separator:
            raise ValueError(f"Invalid backup filename: {backup_file.name}")
        return validate_path_component(product, label="product name")

    @staticmethod
    def _set_permissions(install_path: Path) -> None:
        owner = "root"
        manifest = install_path / ".plexinstaller-resources.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            expected = SystemdManager.service_user_name(install_path.name)
            user = data.get("service_user")
            if data.get("service_isolated") is True and user == expected:
                pwd.getpwnam(user)
                owner = user
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            pass
        subprocess.run(["chown", "-R", f"{owner}:{owner}", str(install_path)], check=True)
        subprocess.run(
            ["find", str(install_path), "-type", "d", "-exec", "chmod", "750", "{}", ";"],
            check=True,
        )
        for path in install_path.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            sensitive = path.name.lower() in {
                "config.yml",
                "config.yaml",
                "config.json",
                ".env",
            } or path.name.lower().endswith((".key", ".pem"))
            executable = bool(path.stat().st_mode & 0o111) or path.suffix.lower() in {".sh", ".py"}
            os.chmod(path, 0o600 if sensitive else 0o750 if executable else 0o640)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_backup(self):
        """Interactive backup deletion."""
        if not self.backup_dir.exists():
            self.printer.warning("No backups directory found")
            return

        backups = sorted(
            self.backup_dir.glob("*.tar.gz"),
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
