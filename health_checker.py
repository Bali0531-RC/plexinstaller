"""
System health checks and post-install self-test diagnostics.

Extracted from PlexInstaller to keep diagnostic logic isolated and testable.
"""

import http.client
import logging
import os
import socket
import ssl
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from utils import ColorPrinter, SystemdManager

logger = logging.getLogger("plexinstaller.health")


@dataclass
class SelfTestResult:
    """Result of a single diagnostic test."""

    name: str
    status: str  # "pass" | "fail" | "warn"
    detail: str = ""
    hint: str = ""


class HealthChecker:
    """Post-install self-tests and system-wide health diagnostics."""

    def __init__(
        self,
        printer: ColorPrinter,
        systemd: SystemdManager,
        install_dir: Path,
        node_min_version: int,
        nginx_available: Path,
        nginx_enabled: Path,
    ):
        self.printer = printer
        self.systemd = systemd
        self.install_dir = install_dir
        self.node_min_version = node_min_version
        self.nginx_available = nginx_available
        self.nginx_enabled = nginx_enabled

    # ------------------------------------------------------------------
    # Network / runtime probes
    # ------------------------------------------------------------------

    @staticmethod
    def wait_for_tcp_port(host: str, port: int, timeout_seconds: int = 30) -> bool:
        """Wait until a TCP port accepts connections."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=2):
                    return True
            except OSError:
                time.sleep(1)
        return False

    @staticmethod
    def probe_http(host: str, port: int, path: str = "/", timeout: int = 3) -> tuple[bool, str]:
        """Probe an HTTP endpoint; returns (ok, detail)."""
        try:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            conn.request("GET", path)
            resp = conn.getresponse()
            detail = f"HTTP {resp.status} {resp.reason}"
            return True, detail
        except Exception as exc:
            return False, str(exc)

    def check_node_version(self) -> tuple[bool, str]:
        """Verify node is installed and meets the minimum version."""
        try:
            result = subprocess.run(["node", "-v"], capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return False, (result.stderr or result.stdout or "node -v failed").strip()
            version = (result.stdout or "").strip().lstrip("v")
            major = int(version.split(".")[0])
            if major < self.node_min_version:
                return False, (f"Node.js v{version} (needs >= {self.node_min_version})")
            return True, f"Node.js v{version}"
        except Exception as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Post-install self-tests
    # ------------------------------------------------------------------

    def run_post_install_self_tests(
        self,
        context,
        mongo_creds: dict | None,
        config=None,
        mongo_manager=None,
    ) -> list[SelfTestResult]:
        """Run a comprehensive self-test suite after product installation.

        Parameters
        ----------
        context:
            An ``InstallationContext`` instance.
        mongo_creds:
            MongoDB credentials dict, or None if MongoDB was skipped.
        config:
            The global ``Config`` object (used only for ``get_product``).
        mongo_manager:
            A ``MongoDBManager`` instance for URI validation / shell calls.
        """
        results: list[SelfTestResult] = []

        # Node runtime
        ok, detail = self.check_node_version()
        results.append(
            SelfTestResult(
                name="Node.js version",
                status="pass" if ok else "fail",
                detail=detail,
                hint="Install/upgrade Node.js and re-run installer" if not ok else "",
            )
        )

        # Install integrity
        package_json = context.install_path / "package.json"
        results.append(
            SelfTestResult(
                name="package.json present",
                status="pass" if package_json.exists() else "fail",
                detail=str(package_json) if package_json.exists() else "missing",
                hint=("Ensure the archive contains a Node app with package.json" if not package_json.exists() else ""),
            )
        )

        node_modules = context.install_path / "node_modules"
        results.append(
            SelfTestResult(
                name="node_modules present",
                status="pass" if node_modules.exists() else "warn",
                detail=str(node_modules) if node_modules.exists() else "missing",
                hint=(
                    "If the app fails to start, re-run npm install in the install directory"
                    if not node_modules.exists()
                    else ""
                ),
            )
        )

        # Config file existence
        config_files = list(context.install_path.glob("config.y*ml")) + list(context.install_path.glob("config.json"))
        if config_files:
            cfg_detail = config_files[0].name
            cfg_hint = (
                "Fill in the required values (tokens, secrets, etc.) in "
                f"{config_files[0]} before the service will run correctly"
            )
            cfg_status = "warn"
        else:
            cfg_detail = "no config.yml/config.json found"
            cfg_hint = "You may need to create/configure the app config manually"
            cfg_status = "warn"
        results.append(
            SelfTestResult(
                name="Config file present",
                status=cfg_status,
                detail=cfg_detail,
                hint=cfg_hint,
            )
        )

        service_name = f"plex-{context.instance_name}"
        if context.service_created:
            is_active = False
            for _ in range(20):
                status = self.systemd.get_status(service_name)
                if status.strip() == "active":
                    is_active = True
                    break
                time.sleep(1)

            results.append(
                SelfTestResult(
                    name="systemd service active",
                    status="pass" if is_active else "warn",
                    detail=f"{service_name} is {self.systemd.get_status(service_name)}",
                    hint=(
                        f"The service may have crashed because config.yml is not yet filled in. "
                        f"Edit the config, then: systemctl restart {service_name}"
                        if not is_active
                        else ""
                    ),
                )
            )
        else:
            results.append(
                SelfTestResult(
                    name="systemd auto-start",
                    status="warn",
                    detail="not configured",
                    hint=f"Enable it later with: systemctl enable --now {service_name}",
                )
            )

        # App port checks — only meaningful when a dashboard/web UI is installed.
        # Without a dashboard the product is a headless bot; nothing listens on the port.
        if context.service_created and getattr(context, "has_dashboard", False):
            port_ready = self.wait_for_tcp_port("127.0.0.1", context.port, timeout_seconds=45)
            results.append(
                SelfTestResult(
                    name="Local TCP port reachable",
                    status="pass" if port_ready else "fail",
                    detail=f"127.0.0.1:{context.port}",
                    hint=(
                        f"Check the service logs: journalctl -u {service_name} -n 200 --no-pager"
                        if not port_ready
                        else ""
                    ),
                )
            )

            if port_ready:
                http_ok, http_detail = self.probe_http("127.0.0.1", context.port)
                results.append(
                    SelfTestResult(
                        name="Local HTTP responds",
                        status="pass" if http_ok else "warn",
                        detail=http_detail,
                        hint=("The app may not expose /; verify the configured bind/port" if not http_ok else ""),
                    )
                )
        elif context.service_created and not getattr(context, "has_dashboard", False):
            results.append(
                SelfTestResult(
                    name="Local TCP port check",
                    status="warn",
                    detail=f"skipped — no dashboard installed (port {context.port} unused)",
                    hint="Install with a dashboard if you need a web UI on this port",
                )
            )

        # Mongo validation
        if mongo_creds and mongo_creds.get("uri"):
            uri = mongo_creds["uri"]
            ok = mongo_manager.validate_uri(uri) if mongo_manager else False
            results.append(
                SelfTestResult(
                    name="MongoDB auth via generated URI",
                    status="pass" if ok else "fail",
                    detail="ping ok" if ok else "authentication/ping failed",
                    hint=(
                        "Re-run MongoDB setup or create the DB/user manually and update the app config"
                        if not ok
                        else ""
                    ),
                )
            )

            if ok and mongo_manager:
                script = (
                    "(function() {\n"
                    "  try {\n"
                    "    const c = db.getCollection('__plexinstaller_selftest');\n"
                    "    const doc = { ok: true, ts: new Date() };\n"
                    "    c.insertOne(doc);\n"
                    "    const found = c.findOne({ ok: true });\n"
                    "    if (!found) throw new Error('readback failed');\n"
                    "    print('__PLEXINSTALLER_OK__');\n"
                    "  } catch (e) {\n"
                    "    print('__PLEXINSTALLER_ERROR__ ' + e); quit(2);\n"
                    "  }\n"
                    "})();"
                )
                try:
                    result = mongo_manager.run_shell([uri, "--quiet", "--eval", script], timeout=20)
                    combined = (result.stdout or "") + "\n" + (result.stderr or "")
                    rw_ok = result.returncode == 0 and "__PLEXINSTALLER_OK__" in combined
                except Exception:
                    rw_ok = False
                results.append(
                    SelfTestResult(
                        name="MongoDB read/write",
                        status="pass" if rw_ok else "warn",
                        detail="ok" if rw_ok else "could not verify insert/read",
                        hint="Check MongoDB logs and permissions" if not rw_ok else "",
                    )
                )
        else:
            product_cfg = config.get_product(context.product) if config and hasattr(config, "get_product") else None
            requires = bool(getattr(product_cfg, "requires_mongodb", False))
            if requires:
                results.append(
                    SelfTestResult(
                        name="MongoDB configured",
                        status="warn",
                        detail="no MongoDB credentials generated",
                        hint="This product requires MongoDB; set mongoURI in the config and restart the service",
                    )
                )

        # Nginx + SSL checks
        if context.domain:
            self._check_nginx_ssl(context, results)

        self.print_summary(results)
        return results

    # ------------------------------------------------------------------
    # System-wide health check
    # ------------------------------------------------------------------

    def system_health_check(self):
        """Comprehensive system health check (disk, services, nginx, mongo, SSL, mem, load)."""
        os.system("clear" if os.name != "nt" else "cls")
        self.printer.header("System Health Check")

        # Disk space
        disk_path = self.install_dir if self.install_dir.exists() else Path("/")
        stat = os.statvfs(disk_path)
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
        used_percent = ((total_gb - free_gb) / total_gb) * 100

        logger.info("=== Disk Space ===")
        logger.info("Location: %s", self.install_dir)
        logger.info("Total: %.1f GB", total_gb)
        logger.info("Free: %.1f GB", free_gb)
        logger.info("Used: %.1f%%", used_percent)

        if used_percent > 90:
            self.printer.error("⚠ WARNING: Disk usage above 90%!")
        elif used_percent > 80:
            self.printer.warning("⚠ Disk usage above 80%")
        else:
            self.printer.success("✓ Disk space healthy")

        # Services
        logger.info("=== Services Status ===")
        if self.install_dir.exists():
            all_running = True
            for product_dir in self.install_dir.iterdir():
                if product_dir.is_dir() and product_dir.name != "backups":
                    service_name = f"plex-{product_dir.name}"
                    status = self.systemd.get_status(service_name)

                    normalized = status.strip().lower()
                    if normalized == "active":
                        logger.info("  ✓ %s: Running", product_dir.name)
                    elif normalized == "inactive":
                        logger.warning("  ○ %s: Stopped", product_dir.name)
                        all_running = False
                    else:
                        logger.error("  ✗ %s: Not Found", product_dir.name)
                        all_running = False

            if all_running:
                self.printer.success("\n✓ All services are running")
            else:
                self.printer.warning("\n⚠ Some services are not running")
        else:
            self.printer.warning("No installations found")

        # Nginx
        logger.info("=== Web Server Status ===")
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "nginx"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "active":
                self.printer.success("✓ Nginx is running")
            else:
                self.printer.error("✗ Nginx is not running")
        except Exception:
            self.printer.warning("⚠ Could not check Nginx status")

        # MongoDB
        logger.info("=== Database Status ===")
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "mongod"],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip() == "active":
                self.printer.success("✓ MongoDB is running")
            else:
                self.printer.warning("○ MongoDB is not running")
        except Exception:
            self.printer.step("ℹ MongoDB not installed or not using systemd")

        # SSL certificates
        logger.info("=== SSL Certificates ===")
        certbot_installed = subprocess.run(["which", "certbot"], capture_output=True).returncode == 0
        if certbot_installed:
            try:
                result = subprocess.run(["certbot", "certificates"], capture_output=True, text=True)
                if "No certificates found" in result.stdout:
                    self.printer.step("ℹ No SSL certificates found")
                else:
                    cert_count = result.stdout.count("Certificate Name:")
                    self.printer.success(f"✓ Found {cert_count} SSL certificate(s)")
            except Exception:
                self.printer.warning("⚠ Could not check SSL certificates")
        else:
            self.printer.step("ℹ Certbot not installed")

        # Memory
        logger.info("=== Memory Usage ===")
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
                mem_total = int([line for line in lines if "MemTotal" in line][0].split()[1]) / 1024
                mem_available = int([line for line in lines if "MemAvailable" in line][0].split()[1]) / 1024
                mem_used = mem_total - mem_available
                mem_percent = (mem_used / mem_total) * 100

                logger.info("Total: %.0f MB", mem_total)
                logger.info("Used: %.0f MB (%.1f%%)", mem_used, mem_percent)
                logger.info("Available: %.0f MB", mem_available)

                if mem_percent > 90:
                    self.printer.error("⚠ WARNING: Memory usage above 90%!")
                elif mem_percent > 80:
                    self.printer.warning("⚠ Memory usage above 80%")
                else:
                    self.printer.success("✓ Memory usage healthy")
        except Exception:
            self.printer.warning("⚠ Could not check memory usage")

        # System load
        logger.info("=== System Load ===")
        try:
            load1, load5, load15 = os.getloadavg()
            cpu_count = os.cpu_count() or 1
            logger.info("1 min: %.2f", load1)
            logger.info("5 min: %.2f", load5)
            logger.info("15 min: %.2f", load15)
            logger.info("CPU cores: %d", cpu_count)

            if load5 > cpu_count * 2:
                self.printer.error("⚠ WARNING: High system load!")
            elif load5 > cpu_count:
                self.printer.warning("⚠ System load is elevated")
            else:
                self.printer.success("✓ System load normal")
        except Exception:
            self.printer.warning("⚠ Could not check system load")

    # ------------------------------------------------------------------
    # Summary printer
    # ------------------------------------------------------------------

    def print_summary(self, results: list[SelfTestResult]):
        """Pretty-print self-test results."""
        self.printer.header("Post-Install Self-Tests")
        failures = 0
        warnings = 0

        for r in results:
            if r.status == "pass":
                self.printer.success(f"{r.name}: {r.detail}".rstrip())
            elif r.status == "warn":
                warnings += 1
                self.printer.warning(f"{r.name}: {r.detail}".rstrip())
                if r.hint:
                    self.printer.step(r.hint)
            else:
                failures += 1
                self.printer.error(f"{r.name}: {r.detail}".rstrip())
                if r.hint:
                    self.printer.step(r.hint)

        if failures:
            self.printer.error(f"Self-tests completed with {failures} failure(s) and {warnings} warning(s)")
        elif warnings:
            self.printer.warning(f"Self-tests completed with {warnings} warning(s)")
        else:
            self.printer.success("All self-tests passed")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_nginx_ssl(self, context, results: list[SelfTestResult]):
        """Append nginx/SSL/DNS/HTTPS self-test results."""
        try:
            nginx_active = subprocess.run(
                ["systemctl", "is-active", "nginx"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            results.append(
                SelfTestResult(
                    name="nginx service active",
                    status="pass" if nginx_active.stdout.strip() == "active" else "fail",
                    detail=nginx_active.stdout.strip() or nginx_active.stderr.strip(),
                    hint=("Run: systemctl status nginx --no-pager" if nginx_active.stdout.strip() != "active" else ""),
                )
            )
        except Exception as exc:
            results.append(
                SelfTestResult(
                    name="nginx service active",
                    status="warn",
                    detail=str(exc),
                    hint="Ensure nginx is installed and running",
                )
            )

        config_file = self.nginx_available / f"{context.domain}.conf"
        enabled_link = self.nginx_enabled / f"{context.domain}.conf"
        results.append(
            SelfTestResult(
                name="nginx site config present",
                status="pass" if config_file.exists() else "fail",
                detail=str(config_file) if config_file.exists() else "missing",
                hint="Re-run web setup or recreate the nginx config",
            )
        )
        results.append(
            SelfTestResult(
                name="nginx site enabled",
                status="pass" if (enabled_link.exists() or enabled_link.is_symlink()) else "fail",
                detail=(str(enabled_link) if (enabled_link.exists() or enabled_link.is_symlink()) else "missing"),
                hint="Create symlink in sites-enabled and reload nginx",
            )
        )

        try:
            t = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=15)
            results.append(
                SelfTestResult(
                    name="nginx config test",
                    status="pass" if t.returncode == 0 else "fail",
                    detail=(t.stdout or t.stderr or "").strip()[-200:],
                    hint=("Fix nginx errors then reload: systemctl reload nginx" if t.returncode != 0 else ""),
                )
            )
        except Exception as exc:
            results.append(
                SelfTestResult(
                    name="nginx config test",
                    status="warn",
                    detail=str(exc),
                    hint="Install nginx and run nginx -t",
                )
            )

        cert_path = Path(f"/etc/letsencrypt/live/{context.domain}/fullchain.pem")
        results.append(
            SelfTestResult(
                name="SSL certificate present",
                status="pass" if cert_path.exists() else "warn",
                detail=str(cert_path) if cert_path.exists() else "not found",
                hint=("Re-run SSL setup or run certbot manually" if not cert_path.exists() else ""),
            )
        )

        try:
            resolved = socket.gethostbyname(context.domain)
            results.append(SelfTestResult(name="DNS resolves", status="pass", detail=resolved))
        except Exception as exc:
            results.append(
                SelfTestResult(
                    name="DNS resolves",
                    status="warn",
                    detail=str(exc),
                    hint="Ensure your A/AAAA records point to this server",
                )
            )

        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((context.domain, 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=context.domain) as ssock:
                    ssock.getpeercert()
            results.append(SelfTestResult(name="HTTPS handshake", status="pass", detail="ok"))
        except Exception as exc:
            results.append(
                SelfTestResult(
                    name="HTTPS handshake",
                    status="warn",
                    detail=str(exc),
                    hint="Public HTTPS may fail until DNS/ports 443 are correct",
                )
            )
