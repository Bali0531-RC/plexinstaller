"""
Backup creation, listing, restoration, and deletion for installed products.

Extracted from PlexInstaller to keep domain logic isolated and testable.
"""

import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from pathlib import Path

from utils import ColorPrinter, SystemdManager


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
        install_path = self.install_dir / product
        self.backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"{product}_backup_{timestamp}.tar.gz"

        self.printer.step(f"Creating backup of {product}...")

        service_name = f"plex-{product}"
        was_running = "active" in self.systemd.get_status(service_name).lower()

        if was_running:
            self.printer.step("Stopping service...")
            self.systemd.stop(service_name)

        try:
            with tarfile.open(backup_file, "w:gz") as tar:
                tar.add(install_path, arcname=product)

            size_mb = backup_file.stat().st_size / (1024 * 1024)
            self.printer.success(f"Backup created: {backup_file.name}")
            self.printer.step(f"Size: {size_mb:.2f} MB")

        except Exception as e:
            self.printer.error(f"Backup failed: {e}")

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
            product = backup_file.stem.replace("_backup_", " ").split()[0]
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
                product = selected_backup.stem.replace("_backup_", " ").split()[0]

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
        """Restore from a specific backup file."""
        install_path = self.install_dir / product
        service_name = f"plex-{product}"

        self.printer.step("Stopping service...")
        self.systemd.stop(service_name)

        temp_backup: Path | None = None
        if install_path.exists():
            self.printer.step("Backing up current installation...")
            temp_backup = install_path.parent / f"{product}.backup.tmp"
            if temp_backup.exists():
                shutil.rmtree(temp_backup)
            shutil.move(str(install_path), str(temp_backup))

        try:
            self.printer.step(f"Restoring from {backup_file.name}...")

            with tarfile.open(backup_file, "r:gz") as tar:
                tar.extractall(self.install_dir)

            self.printer.step("Setting permissions...")
            subprocess.run(["chown", "-R", "root:root", str(install_path)])
            subprocess.run(
                [
                    "find",
                    str(install_path),
                    "-type",
                    "d",
                    "-exec",
                    "chmod",
                    "755",
                    "{}",
                    ";",
                ]
            )
            subprocess.run(
                [
                    "find",
                    str(install_path),
                    "-type",
                    "f",
                    "-exec",
                    "chmod",
                    "644",
                    "{}",
                    ";",
                ]
            )

            # Remove temp backup on success
            temp_backup2 = install_path.parent / f"{product}.backup.tmp"
            if temp_backup2.exists():
                shutil.rmtree(temp_backup2)

            self.printer.success(f"Restore of {product} complete")

            self.printer.step("Starting service...")
            self.systemd.start(service_name)

        except Exception as e:
            self.printer.error(f"Restore failed: {e}")

            rollback = install_path.parent / f"{product}.backup.tmp"
            if rollback.exists():
                self.printer.warning("Attempting to restore previous installation...")
                if install_path.exists():
                    shutil.rmtree(install_path)
                shutil.move(str(rollback), str(install_path))

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
