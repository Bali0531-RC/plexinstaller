# PlexInstaller — Windows Experimental Edition

> **Experimental:** This branch is an unofficial, Windows-only port. It can create services, firewall rules, databases, proxy configuration, and files under `C:\ProgramData`. Use it only on a disposable system or after taking backups, and review every prompt before accepting it.

PlexInstaller installs and manages licensed PlexDevelopment and Drako products on Windows. New installs use PlexTickets, PlexStaff, DrakoStatus, DrakoStore, DrakoForms, DrakoLinks, DrakoPaste, and DrakoTracker. Existing legacy `plexstatus`, `plexstore`, `plexforms`, `plexlinks`, `plexpaste`, and `plextracker` installations remain discoverable and manageable without being renamed.

The installer handles local archive discovery and extraction, Node.js dependencies, MongoDB users, nginx configuration, firewall rules, backups, optional diagnostics, and post-install management. Product archives and licenses are not included.

## Support boundary

- Supported runtime: Windows 10/11 and Windows Server 2019 or newer.
- Required Python: 3.10 or newer.
- Administrator privileges are required for installation and system changes.
- [NSSM](https://nssm.cc/) is required for product services. A plain `sc.exe create` service is not a supported fallback for Node.js products.
- `winget` or Chocolatey is required for automated dependency installation.
- Windows CI exercises Python 3.10, 3.11, and 3.12. Full installation still requires manual validation on a clean Windows VM because CI cannot safely exercise Administrator elevation, real NSSM services, firewall changes, MongoDB provisioning, DNS, nginx, or certificate issuance.

There is no Linux runtime or Linux bootstrap path in this branch.

## Source installation

Open an elevated PowerShell window:

```powershell
git clone --branch windows-experimental https://github.com/Bali0531-RC/plexinstaller.git
Set-Location plexinstaller
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python .\installer.py
```

Install NSSM first and ensure `nssm.exe` is on `PATH`. The installer may install other prerequisites through `winget` or Chocolatey, but service creation is supported only through NSSM.

After installation, the generated commands include:

```text
plex list
plex status <product>
plex start <product>
plex stop <product>
plex restart <product>
plex logs <product>
plex config <product>
plex health
```

Service names use `plex-<instance>`, for example `plex-plextickets`. Use the `plex` commands or NSSM to manage them.

## Update channel and signature trust

Windows builds follow the `windows-experimental` update channel. The updater accepts `version.json`, `version.json.sig`, `release-key.gpg`, and managed file URLs from that branch. Managed downloads require manifest SHA-256 checksums. When GPG verification is available, the bundled release key must have fingerprint:

```text
431E 869D 5BB5 19AF F7B0  2837 9B0D FA4B F863 07BD
```

Do not substitute manifests, signatures, or keys from `main`: that channel targets a different platform. If a checkout still reports `main` as its update source, disable auto-update and update the Windows source before using it.

## Diagnostics and privacy

On first interactive launch, the installer asks whether to enable diagnostics. If enabled, it can send the product and instance names, installation steps and details, status, errors, timestamps, and generated installer log to the configured remote endpoint. Common secret patterns are redacted on a best-effort basis, but paths, domains, ports, or unrecognized sensitive values may remain; do not treat the payload as anonymous.

The preference is stored at `C:\ProgramData\plex\telemetry_pref`. Write `disabled` to that file to opt out of future collection. Local diagnostic logs are stored under `C:\ProgramData\plexinstaller\telemetry\logs`. This repository contains only the diagnostics client; it does not include or operate the remote telemetry server.

## Windows paths

| Path | Purpose |
| --- | --- |
| `C:\ProgramData\plex\apps\<instance>` | Installed product instance |
| `C:\ProgramData\plex\apps\backups` | Product backups |
| `C:\ProgramData\plex\nginx\sites-available\<domain>.conf` | Generated nginx configuration |
| `C:\ProgramData\plex\nginx\sites-enabled\<domain>.conf` | Enabled nginx configuration |
| `C:\ProgramData\plex\mongodb_credentials` | Generated MongoDB credentials |
| `C:\ProgramData\plex\telemetry_pref` | Diagnostics preference |
| `C:\ProgramData\plexinstaller` | Installed manager modules and command wrappers |
| `C:\ProgramData\plexinstaller\telemetry\logs` | Local diagnostic logs |
| `C:\ProgramData\plexinstaller\plexinstaller.lock` | Single-process runtime lock |

## Development

Use a regular, non-elevated PowerShell window for source checks:

```powershell
git clone --branch windows-experimental https://github.com/Bali0531-RC/plexinstaller.git
Set-Location plexinstaller
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
ruff check addon_manager.py backup_manager.py config.py health_checker.py installer.py mongodb_manager.py plex_cli.py release_windows.py shared.py telemetry_client.py utils.py
ruff format --check addon_manager.py backup_manager.py config.py health_checker.py installer.py mongodb_manager.py plex_cli.py release_windows.py shared.py telemetry_client.py utils.py
mypy addon_manager.py backup_manager.py config.py health_checker.py installer.py mongodb_manager.py plex_cli.py release_windows.py shared.py telemetry_client.py utils.py
pytest tests -v --tb=short --cov --cov-branch --cov-report=term-missing --cov-fail-under=40
```

The coverage gate measures every production Python module. Runtime-only dependencies are also listed in `requirements.txt` for tooling that does not install the project metadata. Contributors should use the `dev` extra. Open pull requests against `windows-experimental`, and report which Windows version and Python version were used for manual validation.

Prepare branch release metadata with `python release_windows.py --version X.Y.Z --entry "..."`. The preparer synchronizes the installer and package versions, regenerates Windows-channel URLs and hashes, exports the pinned public key, signs `version.json`, and verifies the result before replacing existing artifacts.

## Repository layout

| Path | Purpose |
| --- | --- |
| `installer.py` | Interactive installer and manager |
| `plex_cli.py` | Post-install product management CLI |
| `config.py` | Windows paths and product metadata |
| `utils.py` | Windows services, firewall, nginx, SSL, archive, and logging helpers |
| `shared.py` | Update, signature, and command-wrapper utilities |
| `mongodb_manager.py` | MongoDB installation and credential management |
| `backup_manager.py` | Product backup and restore |
| `health_checker.py` | Installation and system health checks |
| `addon_manager.py` | Supported product add-on management |
| `telemetry_client.py` | Optional diagnostics client and local session log |
| `tests` | Automated Python tests |
