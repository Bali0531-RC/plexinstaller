# PlexInstaller (Python)

PlexInstaller is the unified Python-based installer and management tool for the PlexDevelopment product line (Tickets, Staff, Status, Store, Forms, Links, Paste, Tracker, and supporting dashboards). It handles archive discovery, extraction, dependency installation, MongoDB/user provisioning, nginx + SSL wiring, firewall rules, telemetry, and post-install management from a single TUI-like workflow.

## Highlights
- **Single-command bootstrap** via `setup.sh` that downloads the latest signed installer bundle and telemetry client.
- **Product-aware flows** covering MongoDB provisioning, port/domain validation, custom 502 page generation, dashboard add-ons, and backup/restore tooling.
- **System services & SSL** with automated nginx site generation, Certbot flows, and optional systemd registration per instance.
- **Telemetry pipeline** (client + FastAPI server + nginx proxy) capturing anonymized install steps, failures, and installer health while respecting user opt-out.
- **Multi-instance ready** with automatic instance naming, unique Mongo credentials, and per-service firewall openings.

## Quick Start
1. **Bootstrap** the installer on a fresh host:
   ```sh
   curl -fsSL https://plexdev.xyz/setup.sh | sudo bash
   ```
2. **Run** the installer:
   ```sh
   sudo plexinstaller
   ```
3. **Select** the product to deploy and follow the interactive prompts for archives, domains, SSL email, and MongoDB configuration.

> **Telemetry & privacy:** On first launch the installer asks whether you want to share anonymous diagnostics (step names, success/failure state, and the sanitized log). Your choice is stored in `/etc/plex/telemetry_pref` and can be toggled manually at any time.

## Telemetry Snapshot
These badges hit `https://plexdev.xyz/tel/stats` live, so the README always reflects fresh telemetry without manual edits:

![Total installs](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.total&label=Install%20attempts&style=for-the-badge)
![Successes](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.success&label=Successful&color=4caf50&style=for-the-badge)
![Failures](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.failure&label=Failed&color=ef5350&style=for-the-badge)
![Success rate](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fplexdev.xyz%2Ftel%2Fstats&query=%24.success_rate&suffix=%25&label=Success%20rate&color=2196f3&style=for-the-badge)

Need to dig deeper? Grab the structured stats and recent sessions straight from the API:
```sh
curl -s https://plexdev.xyz/tel/stats | jq
curl -s https://plexdev.xyz/tel/events | jq '.[-5:]'
```

The FastAPI telemetry service stores raw events in `telemetry/data/events.jsonl`, aggregates counts into `telemetry/data/stats.json`, and exposes logs via `/tel/logs/{session_id}`. nginx proxies `/tel/` to this service in production.

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
- Requires Python 3.10+ plus system package managers (`apt`, `yum`, etc.) for product dependencies.
- Telemetry server dependencies are listed in `telemetry/requirements.txt`; run `uvicorn telemetry.server:app --reload` locally for testing.
- Frontend (`web2/`) uses Node 20+ with Vite. Run `npm install && npm run dev` while iterating on docs/UI.

## Contributing
1. Fork and clone the repository.
2. Create a feature branch (`git checkout -b feature/my-change`).
3. Make your changes (ensure Python formatting/typing and frontend linting pass).
4. Push and open a pull request describing the change, telemetry impact, and test coverage.

Please open an issue for installer regressions, telemetry anomalies, or product-specific installation guides.
