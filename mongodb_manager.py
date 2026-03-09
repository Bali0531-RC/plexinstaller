"""
MongoDB installation, user provisioning, and configuration management.

Extracted from PlexInstaller to keep domain logic isolated and testable.
"""

import json
import os
import re
import secrets
import shutil
import string
import subprocess
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
        mongodb_repo_version_bookworm: str,
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

            self.save_credentials(instance_name, mongo_creds)
            self.update_config(install_path, mongo_creds)

            if not self.validate_uri(mongo_creds["uri"]):
                raise RuntimeError(
                    "MongoDB credentials were created but authentication failed when validating the generated URI"
                )

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
        """Install MongoDB for the detected distro."""
        self.printer.step("Installing MongoDB...")
        distro = (self.system.distribution or "").lower()
        try:
            if "ubuntu" in distro or "debian" in distro:
                return self._install_debian()
            elif "centos" in distro or "rhel" in distro or "fedora" in distro:
                return self._install_rhel()
            elif "arch" in distro:
                return self._install_arch()
            else:
                self.printer.error(f"Unsupported distribution for automatic MongoDB install: {distro}")
                self.printer.step("Please install MongoDB manually: https://docs.mongodb.com/manual/installation/")
                return False
        except Exception as e:
            self.printer.error(f"MongoDB installation failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Service management
    # ------------------------------------------------------------------

    def ensure_running(self) -> str:
        """Ensure MongoDB service is running; returns the detected service name."""
        for service in ("mongod", "mongodb"):
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.stdout.strip() == "active":
                    return service

                subprocess.run(["systemctl", "start", service], check=True, timeout=60)
                result2 = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result2.stdout.strip() == "active":
                    return service
            except Exception:
                continue

        raise RuntimeError("Could not start MongoDB service (tried 'mongod' and 'mongodb')")

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

    def create_user(self, instance_name: str) -> dict | None:
        """Create a MongoDB database and user for *instance_name*."""
        alphabet = string.ascii_letters + string.digits
        random_suffix = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(5))
        db_name = f"{instance_name}_{random_suffix}"
        username = f"{instance_name}_user"
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
                        "uri": (f"mongodb://{username}:{password}@localhost:27017/{db_name}?authSource={db_name}"),
                    }

                last_error = combined.strip()[-800:]
            except Exception as exc:
                last_error = str(exc)

            self.printer.warning(f"MongoDB user creation attempt {attempt}/5 failed; retrying...")
            time.sleep(2)

        if "not authorized" in last_error.lower() or "unauthorized" in last_error.lower():
            self.printer.error("MongoDB appears to have authentication enabled already.")
            self.printer.step("This installer can only auto-provision users on a local MongoDB without prior auth.")
            self.printer.step(
                "Workaround: temporarily disable auth or create the DB/user manually, "
                "then paste the URI into your app config."
            )

        self.printer.error(f"Failed to create MongoDB user after retries. Last error: {last_error}")
        return None

    # ------------------------------------------------------------------
    # Credentials persistence
    # ------------------------------------------------------------------

    def save_credentials(self, instance_name: str, creds: dict):
        """Append credentials to /etc/plex/mongodb_credentials."""
        creds_dir = Path("/etc/plex")
        creds_dir.mkdir(parents=True, exist_ok=True)

        creds_file = creds_dir / "mongodb_credentials"

        # Open with restrictive permissions from the start (O_CREAT|O_APPEND|O_WRONLY, mode 0600)
        fd = os.open(str(creds_file), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            f = os.fdopen(fd, "a")
        except Exception:
            os.close(fd)
            raise

        with f:
            f.write(f"\n# {instance_name}\n")
            f.write(f"DATABASE={creds['database']}\n")
            f.write(f"USERNAME={creds['username']}\n")
            f.write(f"PASSWORD={creds['password']}\n")
            f.write(f"URI={creds['uri']}\n")
        self.printer.success(f"Credentials saved to {creds_file}")

    # ------------------------------------------------------------------
    # Config patching
    # ------------------------------------------------------------------

    def update_config(self, install_path: Path, creds: dict):
        """Patch product config file with MongoDB connection string."""
        config_files = list(install_path.glob("config.y*ml")) + list(install_path.glob("config.json"))

        if not config_files:
            self.printer.warning("No config file found to update with MongoDB settings")
            self.printer.step(f"MongoDB URI: {creds['uri']}")
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
                config_file.write_text(json.dumps(data, indent=2) + "\n")
                self.printer.success(f"Updated MongoDB URI in {config_file.name} ({set_key})")
                return
            except Exception as e:
                self.printer.warning(f"Could not auto-update JSON config: {e}")
                self.printer.step(f"MongoDB URI: {mongo_uri}")
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
                config_file.write_text(content)
                self.printer.success(f"Updated MongoDB URI in {config_file.name}")
            else:
                self.printer.warning(f"Could not find MongoDB URI field in {config_file.name}")
                self.printer.step(f"Please manually add MongoDB URI: {mongo_uri}")
        except Exception as e:
            self.printer.warning(f"Could not auto-update config: {e}")
            self.printer.step(f"MongoDB URI: {mongo_uri}")

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

    def _install_debian(self) -> bool:
        """Install MongoDB on Debian/Ubuntu."""
        try:
            self.printer.step("Cleaning up old MongoDB repositories...")
            old_repo_files = [
                "/etc/apt/sources.list.d/mongodb-org-7.0.list",
                "/etc/apt/sources.list.d/mongodb-org-6.0.list",
                "/etc/apt/sources.list.d/mongodb-org-5.0.list",
                "/etc/apt/sources.list.d/mongodb-org-4.4.list",
            ]
            old_gpg_keys = [
                "/usr/share/keyrings/mongodb-server-7.0.gpg",
                "/usr/share/keyrings/mongodb-server-6.0.gpg",
                "/usr/share/keyrings/mongodb-server-5.0.gpg",
                "/usr/share/keyrings/mongodb-server-4.4.gpg",
            ]

            for repo_file in old_repo_files:
                if Path(repo_file).exists():
                    Path(repo_file).unlink()
            for gpg_key in old_gpg_keys:
                if Path(gpg_key).exists():
                    Path(gpg_key).unlink()

            self.printer.step("Installing prerequisites (gnupg, curl)...")
            subprocess.run(
                ["apt-get", "install", "-y", "gnupg", "curl"],
                check=True,
                capture_output=True,
                timeout=120,
            )

            mongo_ver = self.mongodb_version
            mongo_ver_bookworm = self.mongodb_repo_version_bookworm
            self.printer.step("Adding MongoDB repository...")
            curl_process = subprocess.Popen(
                [
                    "curl",
                    "-fsSL",
                    f"https://www.mongodb.org/static/pgp/server-{mongo_ver}.asc",
                ],
                stdout=subprocess.PIPE,
            )
            subprocess.run(
                [
                    "gpg",
                    "-o",
                    f"/usr/share/keyrings/mongodb-server-{mongo_ver}.gpg",
                    "--dearmor",
                ],
                stdin=curl_process.stdout,
                check=True,
                timeout=30,
            )
            curl_process.wait()

            distro = (self.system.distribution or "").lower()
            distro_codename = subprocess.run(
                ["lsb_release", "-cs"],
                capture_output=True,
                text=True,
                check=True,
                timeout=10,
            ).stdout.strip()

            if "ubuntu" in distro:
                repo_line = (
                    f"deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/"
                    f"mongodb-server-{mongo_ver}.gpg ] "
                    f"http://repo.mongodb.org/apt/ubuntu "
                    f"{distro_codename}/mongodb-org/{mongo_ver} multiverse\n"
                )
            elif "debian" in distro:
                if distro_codename == "bullseye":
                    repo_line = (
                        f"deb [ signed-by=/usr/share/keyrings/"
                        f"mongodb-server-{mongo_ver}.gpg ] "
                        f"http://repo.mongodb.org/apt/debian "
                        f"bullseye/mongodb-org/{mongo_ver} main\n"
                    )
                else:
                    # Bookworm and newer (trixie, etc.) use the bookworm repo
                    repo_line = (
                        f"deb [ signed-by=/usr/share/keyrings/"
                        f"mongodb-server-{mongo_ver}.gpg ] "
                        f"http://repo.mongodb.org/apt/debian "
                        f"bookworm/mongodb-org/{mongo_ver_bookworm} main\n"
                    )
            else:
                repo_line = (
                    f"deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/"
                    f"mongodb-server-{mongo_ver}.gpg ] "
                    f"http://repo.mongodb.org/apt/ubuntu "
                    f"focal/mongodb-org/{mongo_ver} multiverse\n"
                )

            with open(f"/etc/apt/sources.list.d/mongodb-org-{mongo_ver}.list", "w") as f:
                f.write(repo_line)

            self.printer.step("Updating package database...")
            subprocess.run(["apt-get", "update"], check=True, timeout=120)

            self.printer.step("Installing MongoDB packages...")
            subprocess.run(["apt-get", "install", "-y", "mongodb-org"], check=True, timeout=300)

            self.printer.step("Starting MongoDB service...")
            subprocess.run(["systemctl", "start", "mongod"], check=True, timeout=60)
            subprocess.run(["systemctl", "enable", "mongod"], check=True, timeout=30)

            self.printer.success("MongoDB installed successfully")
            return True

        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False

    def _install_rhel(self) -> bool:
        """Install MongoDB on RHEL/CentOS/Fedora."""
        try:
            mongo_ver = self.mongodb_version
            repo_content = (
                f"[mongodb-org-{mongo_ver}]\n"
                f"name=MongoDB Repository\n"
                f"baseurl=https://repo.mongodb.org/yum/redhat/"
                f"$releasever/mongodb-org/{mongo_ver}/x86_64/\n"
                f"gpgcheck=1\n"
                f"enabled=1\n"
                f"gpgkey=https://www.mongodb.org/static/pgp/server-{mongo_ver}.asc\n"
            )
            with open(f"/etc/yum.repos.d/mongodb-org-{mongo_ver}.repo", "w") as f:
                f.write(repo_content)

            if "fedora" in (self.system.distribution or "").lower():
                subprocess.run(["dnf", "install", "-y", "mongodb-org"], check=True, timeout=300)
            else:
                subprocess.run(["yum", "install", "-y", "mongodb-org"], check=True, timeout=300)

            subprocess.run(["systemctl", "start", "mongod"], check=True, timeout=60)
            subprocess.run(["systemctl", "enable", "mongod"], check=True, timeout=30)

            self.printer.success("MongoDB installed successfully")
            return True

        except Exception as e:
            self.printer.error(f"Failed to install MongoDB: {e}")
            return False

    def _install_arch(self) -> bool:
        """Install MongoDB on Arch Linux via AUR helper."""
        # mongodb-bin is an AUR package; stock pacman cannot install it.
        aur_helper = None
        for helper in ("yay", "paru"):
            if shutil.which(helper):
                aur_helper = helper
                break

        if aur_helper is None:
            self.printer.error(
                "mongodb-bin is an AUR package. Install an AUR helper (yay or paru) first, then re-run the installer."
            )
            return False

        try:
            subprocess.run(
                [aur_helper, "-S", "--noconfirm", "mongodb-bin"],
                check=True,
                timeout=300,
            )
            subprocess.run(["systemctl", "start", "mongodb"], check=True, timeout=60)
            subprocess.run(["systemctl", "enable", "mongodb"], check=True, timeout=30)

            self.printer.success("MongoDB installed successfully")
            return True

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
