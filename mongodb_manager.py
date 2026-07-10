"""
MongoDB installation, user provisioning, and configuration management.

Extracted from PlexInstaller to keep domain logic isolated and testable.
"""

import json
import os
import re
import secrets
import string
import subprocess
import tempfile
import time
from pathlib import Path

from utils import ColorPrinter, SystemDetector


class MongoDBManager:
    """Handles MongoDB installation, user creation, and config patching."""

    def __init__(
        self,
        printer: ColorPrinter,
        system: SystemDetector,
        mongodb_version: str,
        mongodb_repo_version_bookworm: str = "8.2",
    ):
        self.printer = printer
        self.system = system
        self.mongodb_version = mongodb_version
        self.mongodb_repo_version_bookworm = mongodb_repo_version_bookworm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup(
        self,
        instance_name: str,
        install_path: Path,
        required: bool = False,
        wait_for_tcp_port=None,
    ) -> dict | None:
        """Interactive MongoDB setup: install -> start -> create user -> save -> update config -> validate.

        Parameters
        ----------
        wait_for_tcp_port:
            Callable(host, port, timeout_seconds) -> bool.  Injected so the
            caller can share the generic network-wait utility without coupling.
        """
        prompt = (
            "Install and configure MongoDB locally? (Y/n): "
            if required
            else "Install and configure MongoDB locally? (y/n): "
        )
        choice = input(prompt).strip().lower()

        if required and choice in {"", "y", "yes"}:
            choice = "y"

        if choice not in {"y", "yes"}:
            if required:
                self.printer.warning("This product requires MongoDB.")
                self.printer.step("If you are using a remote MongoDB, update your config with its URI.")
            return None

        try:
            if not self.check_installed():
                self.printer.step("MongoDB not found. Installing...")
                if not self.install():
                    self.printer.error("MongoDB installation failed")
                    return None
            else:
                self.printer.success("MongoDB already installed")

            service_name = self.ensure_running()

            _wait = wait_for_tcp_port or self._default_wait_for_tcp_port
            if not _wait("127.0.0.1", 27017, 60):
                raise RuntimeError(f"MongoDB service '{service_name}' did not become ready on 27017")

            mongo_creds = self.create_user(instance_name)
            if not mongo_creds:
                raise RuntimeError("Failed to create MongoDB database/user")

            if not self.validate_uri(mongo_creds["uri"]):
                raise RuntimeError(
                    "MongoDB credentials were created but authentication failed when validating the generated URI"
                )

            self.save_credentials(instance_name, mongo_creds)
            self.update_config(install_path, mongo_creds)

            return mongo_creds

        except Exception as e:
            self.printer.error(f"MongoDB setup failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def check_installed(self) -> bool:
        """Return True if mongosh or mongo is on PATH."""
        for shell in ("mongosh", "mongo"):
            try:
                result = subprocess.run(
                    [shell, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    return True
            except FileNotFoundError:
                continue
            except subprocess.TimeoutExpired:
                continue
        return False

    def install(self) -> bool:
        """Install MongoDB on Windows via winget or manual download."""
        self.printer.step("Installing MongoDB...")
        try:
            return self._install_windows()
        except Exception as e:
            self.printer.error(f"MongoDB installation failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Service management
    # ------------------------------------------------------------------

    def ensure_running(self) -> str:
        """Ensure MongoDB service is running; returns the detected service name."""
        for service in ("MongoDB", "mongod"):
            try:
                result = subprocess.run(
                    ["sc", "query", service],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if "RUNNING" in result.stdout:
                    return service

                subprocess.run(["sc", "start", service], check=True, capture_output=True, timeout=60)
                time.sleep(3)
                result2 = subprocess.run(
                    ["sc", "query", service],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if "RUNNING" in result2.stdout:
                    return service
            except Exception:
                continue

        raise RuntimeError("Could not start MongoDB service (tried 'MongoDB' and 'mongod')")

    # ------------------------------------------------------------------
    # Shell helper
    # ------------------------------------------------------------------

    def run_shell(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """Run mongosh/mongo with *args*; prefers mongosh."""
        try:
            return subprocess.run(
                ["mongosh"] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return subprocess.run(
                ["mongo"] + args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

    # ------------------------------------------------------------------
    # User / database provisioning
    # ------------------------------------------------------------------

    @staticmethod
    def _is_permanent_auth_error(message: str) -> bool:
        """Return whether an error clearly indicates existing authentication."""
        normalized = message.casefold()
        return any(
            marker in normalized
            for marker in (
                "not authorized",
                "unauthorized",
                "requires authentication",
                "requires authorization",
                "authentication is required",
                "authorization is required",
                "authentication required",
                "authorization required",
                "authenticationfailed",
                "authentication failed",
            )
        )

    def create_user(self, instance_name: str) -> dict | None:
        """Create a MongoDB database and user for *instance_name*."""
        alphabet = string.ascii_letters + string.digits
        random_suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(5))
        db_name = f"{instance_name}_{random_suffix}"
        username = f"{instance_name}_{random_suffix}_user"
        password = "".join(secrets.choice(alphabet) for _ in range(24))

        self.printer.step(f"Creating MongoDB database: {db_name}")

        create_user_script = (
            "(function() {\n"
            f"  const dbName = {json.dumps(db_name)};\n"
            f"  const username = {json.dumps(username)};\n"
            f"  const password = {json.dumps(password)};\n"
            "  const roles = [{ role: 'readWrite', db: dbName }];\n"
            "  try {\n"
            "    const target = db.getSiblingDB(dbName);\n"
            "    const existing = target.getUser(username);\n"
            "    if (existing) {\n"
            "      target.updateUser(username, { pwd: password, roles: roles });\n"
            "    } else {\n"
            "      target.createUser({ user: username, pwd: password, roles: roles });\n"
            "    }\n"
            "    const ping = target.runCommand({ ping: 1 });\n"
            "    if (!ping || ping.ok !== 1) { throw new Error('ping failed'); }\n"
            "    print('__PLEXINSTALLER_OK__');\n"
            "  } catch (e) {\n"
            "    print('__PLEXINSTALLER_ERROR__ ' + e);\n"
            "    quit(2);\n"
            "  }\n"
            "})();"
        )

        last_error = ""
        permanent_auth_error = False
        for attempt in range(1, 6):
            try:
                result = self.run_shell(["--quiet", "--eval", create_user_script], timeout=30)
                combined = (result.stdout or "") + "\n" + (result.stderr or "")

                if result.returncode == 0 and "__PLEXINSTALLER_OK__" in combined:
                    self.printer.success(f"Database '{db_name}' ready with user '{username}'")
                    return {
                        "database": db_name,
                        "username": username,
                        "password": password,
                        "host": "localhost",
                        "port": 27017,
                        "uri": f"mongodb://{username}:{password}@localhost:27017/{db_name}?authSource={db_name}",
                    }

                last_error = combined.strip()[-800:]
            except Exception as exc:
                last_error = str(exc)

            if self._is_permanent_auth_error(last_error):
                permanent_auth_error = True
                break

            if attempt < 5:
                self.printer.warning(f"MongoDB user creation attempt {attempt}/5 failed; retrying...")
                time.sleep(2)

        if permanent_auth_error:
            self.printer.error("MongoDB appears to have authentication enabled already.")
            self.printer.step("This installer can only auto-provision users on a local MongoDB without prior auth.")
            self.printer.step(
                "Workaround: temporarily disable auth or create the DB/user manually, "
                "then paste the URI into your app config."
            )
            self.printer.error("Failed to create MongoDB user due to an authorization error.")
            return None

        self.printer.error(f"Failed to create MongoDB user after 5 attempts. Last error: {last_error}")
        return None

    # ------------------------------------------------------------------
    # Credentials persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
        """Atomically replace a sensitive text file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temporary, mode)
            except OSError:
                pass
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _restrict_credentials_acl(path: Path) -> None:
        """Best-effort restrictive permissions for Windows and test hosts."""
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if os.name != "nt":
            return
        principal = os.environ.get("USERNAME")
        command = ["icacls", str(path), "/inheritance:r"]
        if principal:
            command.extend(["/grant:r", f"{principal}:(R,W)"])
        command.extend(["/grant:r", "SYSTEM:(F)", "Administrators:(F)"])
        try:
            subprocess.run(command, check=False, capture_output=True, timeout=30)
        except OSError:
            pass

    def save_credentials(self, instance_name: str, creds: dict) -> Path:
        """Atomically persist credentials under ProgramData with restrictive ACLs."""
        creds_dir = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "plex"
        creds_dir.mkdir(parents=True, exist_ok=True)

        creds_file = creds_dir / "mongodb_credentials"

        original = creds_file.read_text(encoding="utf-8", errors="replace") if creds_file.exists() else ""
        block = (
            f"\n# {instance_name}\n"
            f"DATABASE={creds['database']}\n"
            f"USERNAME={creds['username']}\n"
            f"PASSWORD={creds['password']}\n"
            f"URI={creds['uri']}\n"
        )
        self._atomic_write(creds_file, original.rstrip("\n") + block)
        self._restrict_credentials_acl(creds_file)

        self.printer.success(f"Credentials saved to {creds_file}")
        return creds_file

    @staticmethod
    def _credential_block_pattern(instance_name: str) -> re.Pattern[str]:
        escaped = re.escape(instance_name)
        return re.compile(
            rf"(?m)^# {escaped}\n"
            r"DATABASE=[^\n]*\nUSERNAME=[^\n]*\nPASSWORD=[^\n]*\nURI=[^\n]*(?:\n|$)"
        )

    def remove_saved_credentials(self, instance_name: str, credentials_file: Path | None = None) -> bool:
        """Remove only one instance's block from the shared credential file."""
        default = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "plex" / "mongodb_credentials"
        creds_file = credentials_file or default
        if not creds_file.exists():
            return False
        original = creds_file.read_text(encoding="utf-8", errors="replace")
        updated, count = self._credential_block_pattern(instance_name).subn("", original, count=1)
        if count == 0:
            return False
        updated = re.sub(r"\n{3,}", "\n\n", updated).lstrip("\n")
        if updated.strip():
            self._atomic_write(creds_file, updated)
            self._restrict_credentials_acl(creds_file)
        else:
            creds_file.unlink(missing_ok=True)
        return True

    def cleanup_identity(self, database: str, username: str, *, drop_database: bool = False) -> bool:
        """Remove an instance's MongoDB user and optionally its data."""
        if not database or not username:
            return False
        script = (
            "(function() {\n"
            f"  const dbName = {json.dumps(database)};\n"
            f"  const username = {json.dumps(username)};\n"
            "  try {\n"
            "    const target = db.getSiblingDB(dbName);\n"
            "    if (target.getUser(username)) target.dropUser(username);\n"
            + ("    target.dropDatabase();\n" if drop_database else "")
            + "    print('__PLEXINSTALLER_OK__');\n"
            "  } catch (e) { print('__PLEXINSTALLER_ERROR__ ' + e); quit(2); }\n"
            "})();"
        )
        try:
            result = self.run_shell(["--quiet", "--eval", script], timeout=30)
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            return result.returncode == 0 and "__PLEXINSTALLER_OK__" in combined
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Config patching
    # ------------------------------------------------------------------

    def update_config(self, install_path: Path, creds: dict):
        """Patch product config file with MongoDB connection string."""
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))

        if not config_files:
            self.printer.warning("No config file found to update with MongoDB settings")
            self.printer.step("Add the generated MongoDB URI from the protected credentials file manually.")
            return

        config_file = config_files[0]
        mongo_uri = creds["uri"]

        if config_file.suffix.lower() == ".json":
            try:
                data = json.loads(config_file.read_text(encoding="utf-8", errors="replace"))
                candidate_keys = [
                    "mongoURI",
                    "mongodb_uri",
                    "database_url",
                    "MongoURI",
                    "MONGO_URI",
                    "MONGODB_URI",
                ]
                set_key = None
                for key in candidate_keys:
                    if key in data:
                        set_key = key
                        break
                if not set_key:
                    set_key = "mongoURI"
                data[set_key] = mongo_uri
                if not isinstance(data, dict):
                    raise ValueError("JSON config must contain an object")
                self._atomic_write(config_file, json.dumps(data, indent=2) + "\n", mode=0o600)
                self.printer.success(f"Updated MongoDB URI in {config_file.name} ({set_key})")
                return
            except Exception as e:
                self.printer.warning(f"Could not auto-update JSON config: {e}")
                self.printer.step("Use the protected credentials file to update the config manually.")
                return

        # YAML-ish config update via regex
        try:
            content = config_file.read_text(encoding="utf-8", errors="replace")
            escaped_uri = mongo_uri.replace("\\", "\\\\").replace('"', '\\"')
            patterns = [
                (
                    r'^(\s*mongoURI\s*:\s*)["\']?.*?["\']?\s*$',
                    r'\1"' + escaped_uri + '"',
                ),
                (
                    r'^(\s*mongodb_uri\s*:\s*)["\']?.*?["\']?\s*$',
                    r'\1"' + escaped_uri + '"',
                ),
                (
                    r'^(\s*database_url\s*:\s*)["\']?.*?["\']?\s*$',
                    r'\1"' + escaped_uri + '"',
                ),
                (
                    r'^(\s*MongoURI\s*:\s*)["\']?.*?["\']?\s*$',
                    r'\1"' + escaped_uri + '"',
                ),
            ]
            updated = False
            for pattern, replacement in patterns:
                if re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE):
                    content = re.sub(pattern, replacement, content, flags=re.IGNORECASE | re.MULTILINE)
                    updated = True
                    break

            if updated:
                mode = config_file.stat().st_mode & 0o777
                self._atomic_write(config_file, content, mode=mode)
                self.printer.success(f"Updated MongoDB URI in {config_file.name}")
            else:
                self.printer.warning(f"Could not find MongoDB URI field in {config_file.name}")
                self.printer.step("Use the protected credentials file to add the MongoDB URI manually.")
        except Exception as e:
            self.printer.warning(f"Could not auto-update config: {e}")
            self.printer.step("Use the protected credentials file to update the config manually.")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_uri(self, uri: str) -> bool:
        """Validate that a MongoDB URI can authenticate and run a ping."""
        script = (
            "(function() {\n"
            "  try {\n"
            "    const res = db.runCommand({ ping: 1 });\n"
            "    if (res && res.ok === 1) { print('__PLEXINSTALLER_OK__'); quit(0); }\n"
            "    print('__PLEXINSTALLER_ERROR__ ping not ok'); quit(2);\n"
            "  } catch (e) {\n"
            "    print('__PLEXINSTALLER_ERROR__ ' + e); quit(2);\n"
            "  }\n"
            "})();"
        )

        try:
            result = self.run_shell([uri, "--quiet", "--eval", script], timeout=20)
            combined = (result.stdout or "") + "\n" + (result.stderr or "")
            return result.returncode == 0 and "__PLEXINSTALLER_OK__" in combined
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private: distro-specific installers
    # ------------------------------------------------------------------

    def _install_windows(self) -> bool:
        """Install MongoDB on Windows via winget or choco."""
        try:
            # Try winget first
            try:
                result = subprocess.run(
                    ["winget", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    self.printer.step("Installing MongoDB via winget...")
                    subprocess.run(
                        [
                            "winget",
                            "install",
                            "--id",
                            "MongoDB.Server",
                            "--accept-package-agreements",
                            "--accept-source-agreements",
                        ],
                        check=True,
                        timeout=600,
                    )
                    self.printer.success("MongoDB installed successfully via winget")
                    return True
            except FileNotFoundError:
                pass

            # Try chocolatey
            try:
                result = subprocess.run(
                    ["choco", "--version"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    self.printer.step("Installing MongoDB via Chocolatey...")
                    subprocess.run(
                        ["choco", "install", "mongodb", "-y"],
                        check=True,
                        timeout=600,
                    )
                    self.printer.success("MongoDB installed successfully via Chocolatey")
                    return True
            except FileNotFoundError:
                pass

            self.printer.error("Neither winget nor Chocolatey found.")
            self.printer.step("Please install MongoDB manually: https://www.mongodb.com/try/download/community")
            return False

        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_wait_for_tcp_port(host: str, port: int, timeout_seconds: int = 30) -> bool:
        import socket

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        return False
