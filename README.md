# PlexInstaller (Python)

PlexInstaller is the unified Python-based unofficial installer and management tool for PlexTickets, PlexStaff, and the renamed Drako product line (Status, Store, Forms, Links, Paste, and Tracker). New deployments use `drako*` instance names; existing `plex*` installations remain fully supported. It handles archive discovery, extraction, dependency installation, MongoDB/user provisioning, nginx + SSL wiring, firewall rules, telemetry, and post-install management from a single TUI-like workflow.

## Highlights
- **Single-command bootstrap** via `setup.sh` that installs bootstrap prerequisites, downloads the installer bundle, verifies release metadata where possible, installs Python requirements, and creates command links.
- **Product-aware flows** covering MongoDB provisioning, port/domain validation, custom 502 page generation, dashboard add-ons, and backup/restore tooling.
- **System services & SSL** with automated nginx site generation, Certbot flows, and optional systemd registration per instance.
- **Root-compatible by default**, with an optional isolated service identity (`PLEX_ISOLATE_SERVICES=1`) that automatically falls back to the legacy root service if user creation or hardening fails.
- **Opt-in telemetry pipeline** (client + FastAPI server) capturing product/instance identifiers, install steps and details, outcomes, errors, timestamps, and generated installer logs with best-effort secret redaction.
- **Multi-instance ready** with automatic instance naming, unique Mongo credentials, and per-service firewall openings.

## Quick Start
1. **Bootstrap** the installer on a fresh host:
   ```sh
   curl -fsSL https://plexdev.xyz/setup.sh | sudo bash
   ```
   `setup.sh` only installs the tooling. It asks whether to launch the separate interactive installer at the end and defaults to no when no terminal is available.
2. **Run** the interactive installer if it was not launched by the bootstrap:
   ```sh
   sudo plexinstaller
   ```
3. **Select** the product to deploy and follow the interactive prompts for archives, domains, SSL email, and MongoDB configuration.

### Product naming compatibility

New installs use `drakostatus`, `drakostore`, `drakoforms`, `drakolinks`, `drakopaste`, and `drakotracker`. Existing `plexstatus`, `plexstore`, `plexforms`, `plexlinks`, `plexpaste`, and `plextracker` directories and services keep their original names. CLI commands accept either brand name and resolve to the installation that actually exists.

> **Telemetry & privacy:** On first interactive launch, the installer asks whether to send diagnostics. If enabled, completed attempts can send product and instance names, step details (including paths/domain/port choices), status, errors, timestamps, and the generated installer log. Common secret patterns are redacted on a best-effort basis, but do not assume logs are anonymous. The choice is stored in `/etc/plex/telemetry_pref`; write `disabled` to opt out of future collection. The website separately uses Google Analytics and Google AdSense. See the website privacy page for details.

## Telemetry Snapshot
These badges hit `https://plexdev.xyz/tel/stats` live, so the README always reflects fresh telemetry without manual edits.
Success rate is calculated from completed installs only — uncompleted sessions (user cancellations, interruptions) are excluded. Completion rate shows what fraction of all attempts reached a completed state.

![Total installs](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.total&label=Install%20attempts&style=for-the-badge)
![Successes](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.success&label=Successful&color=4caf50&style=for-the-badge)
![Failures](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.failure&label=Failed&color=ef5350&style=for-the-badge)
![Uncompleted](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.uncompleted&label=Uncompleted&color=ff9800&style=for-the-badge)
![Success rate](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.success_rate&suffix=%25&label=Success%20rate&color=2196f3&style=for-the-badge)
![Completion rate](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.completion_rate&suffix=%25&label=Completion%20rate&color=9c27b0&style=for-the-badge)

Aggregate statistics are public. Raw events and logs require the telemetry server API key:
```sh
curl -s https://plexdev.xyz/tel/stats | jq
```

The FastAPI telemetry service stores bounded raw events and logs, aggregates public counts, rotates event archives, and prunes logs by configurable age/count/size limits. Raw diagnostic endpoints require authentication.

## Repository Layout
| Path | Purpose |
| --- | --- |
| `installer.py` | Main interactive installer/manager with telemetry instrumentation and product workflows. |
| `config.py` | Shared configuration (paths, telemetry endpoints, product metadata). |
| `telemetry_client.py` | Client that logs steps locally and POSTs payloads to the telemetry API (respects opt-out). |
| `telemetry/server.py` | FastAPI telemetry collector, JSONL archival, stats aggregation, and log retrieval endpoints. |
| `web2/` | Vite/React marketing + docs site for plexdev.xyz (including changelog, docs, guide, and setup script). |
| `web2/public/setup.sh` | Distribution script that installs Python dependencies, pulls the installer files, and ensures telemetry client parity. |
| `utils.py` | Helper classes for colorized output, archive extraction, nginx/systemd management, DNS checks, and firewall operations. |

## Development Notes
- Requires Python 3.10+ and root access for the interactive installer. Ubuntu and Debian are the primary tested targets; package-manager and MongoDB paths for other distributions are best-effort.
- Telemetry server dependencies are listed in `telemetry/requirements.txt`; run `uvicorn telemetry.server:app --reload` locally for testing.
- Frontend (`web2/`) uses Node 20+ with Vite. Use `npm ci`, then `npm run lint`, `npm run typecheck`, and `npm run build`; use `npm run dev` while iterating.
- Python development dependencies, typing stubs, and test tooling are installed with `python -m pip install -e ".[dev,telemetry-server]"`.
- Release manifests and signed Git commits use `431E869D5BB519AFF7B028379B0DFA4BF86307BD` (`developer@bali0531.hu`). The APT repository uses the separate key `C1D43E70EF36AB0B47151196B669DC325581C77B` (`apt@plexdev.xyz`).
- Do not hand-edit release hashes, release changelog entries, or detached signatures. Use `release.sh`; `--prepare-only` regenerates and verifies `version.json`, the matching website changelog entry, checksums, exported public key, and signature without committing or pushing.

## Contributing
1. Fork and clone the repository.
2. Create a feature branch (`git checkout -b feature/my-change`).
3. Make your changes (ensure Python formatting/typing and frontend linting pass).
4. Push and open a pull request describing the change, telemetry impact, and test coverage.

Please open an issue for installer regressions, telemetry anomalies, or product-specific installation guides.
