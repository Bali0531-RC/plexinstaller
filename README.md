# PlexInstaller — Windows Edition

> **Branch:** `windows-experimental` — a standalone windows-only port of PlexInstaller. This branch will **not** be merged into `main`; the Linux version lives in the `dev` and `main` branches.

PlexInstaller is the unified Python-based installer and management tool for the PlexDevelopment product line (Tickets, Staff, Status, Store, Forms, Links, Paste, Tracker, and supporting dashboards). This Windows edition handles archive discovery, extraction, dependency installation, MongoDB/user provisioning, nginx configuration, firewall rules, telemetry, and post-install management from a single interactive CLI workflow — all on Windows.

## Highlights
- **Windows-native** — uses NSSM/sc.exe for services, netsh for firewall, winget/choco for packages, and ProgramData for all system paths.
- **Product-aware flows** covering MongoDB provisioning, port/domain validation, custom 502 page generation, dashboard add-ons, and backup/restore tooling.
- **Windows services** with NSSM (Non-Sucking Service Manager) for registering and managing product instances as background services.
- **Telemetry pipeline** (client + remote API) capturing anonymized install steps, failures, and installer health while respecting user opt-out.
- **Multi-instance ready** with automatic instance naming, unique Mongo credentials, and per-service firewall openings.

## Prerequisites
- **Windows 10/11** or **Windows Server 2019+**
- **Python 3.10+** — [python.org](https://www.python.org/downloads/) (make sure to check "Add to PATH" during install)
- **Administrator privileges** — required for service management, firewall rules, and PATH configuration
- **Package manager** — [winget](https://learn.microsoft.com/en-us/windows/package-manager/) (built-in on Win 11) or [Chocolatey](https://chocolatey.org/install)

## Quick Start
1. **Open an elevated Command Prompt or PowerShell** (Run as Administrator).

2. **Clone the repository** (or download the ZIP from the `windows-experimental` branch):
   ```cmd
   git clone -b windows-experimental https://github.com/Bali0531-RC/plexinstaller.git
   cd plexinstaller
   ```

3. **Install Python dependencies:**
   ```cmd
   pip install -r requirements.txt
   ```

4. **Run the installer:**
   ```cmd
   python installer.py
   ```

5. **Select** the product to deploy and follow the interactive prompts for archives, domains, and MongoDB configuration.

> **Telemetry & privacy:** On first launch the installer asks whether you want to share anonymous diagnostics (step names, success/failure state, and the sanitized log). Your choice is stored in `C:\ProgramData\plex\telemetry_pref` and can be toggled manually at any time.

## CLI Tool
After installation, the `plex` CLI is available system-wide:
```cmd
plex status
plex start <product>
plex stop <product>
plex restart <product>
plex logs <product>
plex config <product>
plex health
```

The CLI creates `.cmd` wrapper scripts and adds them to the system PATH via `setx /M`.

## Windows Service Management
Products are registered as Windows services using [NSSM](https://nssm.cc/). Common operations:

| Action | Command |
| --- | --- |
| Start a service | `nssm start <service>` or `plex start <product>` |
| Stop a service | `nssm stop <service>` or `plex stop <product>` |
| Restart a service | `nssm restart <service>` or `plex restart <product>` |
| Query service status | `sc query <service>` or `plex status` |
| Enable auto-start | `sc config <service> start= auto` |
| Disable auto-start | `sc config <service> start= demand` |
| View logs | Check `C:\ProgramData\plex\apps\<product>\logs\` or Windows Event Viewer |

## Key Paths
| Path | Purpose |
| --- | --- |
| `C:\ProgramData\plex\apps\` | Installed product files |
| `C:\ProgramData\plex\nginx\sites-available\` | nginx site configurations |
| `C:\ProgramData\plex\nginx\sites-enabled\` | Active nginx site configurations |
| `C:\ProgramData\plex\mongodb_credentials` | MongoDB credentials file |
| `C:\ProgramData\plex\telemetry_pref` | Telemetry opt-in/out preference |
| `C:\ProgramData\plexinstaller\` | Installer files and telemetry logs |
| `%TEMP%\plexinstaller.lock` | Runtime lock file (prevents concurrent runs) |

## Firewall
The installer uses `netsh advfirewall` to open/close ports:
```cmd
netsh advfirewall firewall add rule name="Plex <product>" dir=in action=allow protocol=TCP localport=<port>
netsh advfirewall firewall delete rule name="Plex <product>"
```

## Repository Layout
| Path | Purpose |
| --- | --- |
| `installer.py` | Main interactive installer/manager with product workflows. |
| `config.py` | Shared configuration — Windows ProgramData paths, winget/choco packages, product metadata. |
| `utils.py` | Helper classes for NSSM/sc services, netsh firewall, nginx-windows, win-acme SSL, archive extraction. |
| `shared.py` | Shared utilities — .cmd entrypoint creation, self-update, admin checks. |
| `plex_cli.py` | CLI tool — service management, logs, config editing via sc/nssm. |
| `health_checker.py` | System health checks — disk, memory (GlobalMemoryStatusEx), CPU, service status. |
| `mongodb_manager.py` | MongoDB install (winget/choco) and credential management. |
| `backup_manager.py` | Product backup and restore. |
| `addon_manager.py` | Addon installation, removal, and configuration for supported products. |
| `telemetry_client.py` | Client that logs steps locally and POSTs payloads to the telemetry API. |
| `linux/` | Original Linux source files preserved for reference (not used at runtime). |

## Differences from the Linux Version
| Area | Linux (`main` branch) | Windows (`windows-experimental`) |
| --- | --- | --- |
| Services | systemd (`systemctl`) | NSSM + sc.exe |
| Packages | apt / yum / pacman | winget / choco |
| Firewall | ufw / firewall-cmd | netsh advfirewall |
| Paths | `/var/www/plex`, `/etc/plex` | `C:\ProgramData\plex\` |
| File perms | `chmod`, `chown` | NTFS ACLs (no explicit management) |
| SSL | Certbot with systemd timers | Certbot / win-acme |
| Nginx | Package manager, symlinks | Portable install, file copy |
| Process lock | `fcntl.flock()` | `msvcrt.locking()` |
| Admin check | `os.geteuid() == 0` | `ctypes.windll.shell32.IsUserAnAdmin()` |
| CLI entrypoints | `/usr/local/bin` symlinks | `.cmd` wrappers + `setx /M PATH` |

## Development Notes
- Requires Python 3.10+ on Windows.
- Install dependencies: `pip install -r requirements.txt`
- The `linux/` folder contains the original Linux source files for reference when porting features.
- This branch is independent and will not be merged into `main`.

## Contributing
1. Fork and clone the repository.
2. Switch to `windows-experimental`: `git checkout windows-experimental`
3. Create a feature branch: `git checkout -b feature/my-windows-change`
4. Make changes and test on a Windows machine.
5. Push and open a pull request targeting `windows-experimental`.

Please open an issue for Windows-specific installer regressions or feature requests.
