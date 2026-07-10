# PlexInstaller Telemetry Server

A lightweight FastAPI application that receives opt-in product-installation diagnostics from the PlexInstaller telemetry client. It stores complete JSON payloads and submitted per-session logs, and derives aggregate outcome statistics.

The installer asks for telemetry consent on first interactive launch and stores the choice in `/etc/plex/telemetry_pref`. When enabled, a completed attempt can include a generated session ID, product and instance names, status, failure step and error, timestamps, step details, and the generated installer log. Details may contain local paths, domain/port choices, instance names, and error text. The client applies best-effort secret redaction, but operators should treat all collected logs as potentially sensitive.

This service is separate from the plexdev.xyz website's Google Analytics and Google AdSense integrations. Website analytics do not enable installer telemetry, and the installer preference does not control website cookies or advertising.

## Running Locally

```bash
cd telemetry
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
TELEMETRY_API_KEY="replace-me" uvicorn server:app --host 127.0.0.1 --port 9000
```

## API Surface

| Method | Path          | Description                                      |
|--------|---------------|--------------------------------------------------|
| POST   | `/events`     | Accepts telemetry payloads from the installer.   |
| GET    | `/stats`      | Returns aggregate success/failure statistics.    |
| GET    | `/events`     | Lists recent telemetry events (JSONL backed).    |
| GET    | `/logs`       | Lists stored log filenames.                      |
| GET    | `/logs/{id}`  | Returns the saved log contents for a session.    |

All telemetry data and logs are written to `telemetry/data/` by default. The server rotates the event archive and prunes logs by age, count, and total size using the `TELEMETRY_MAX_*` and `TELEMETRY_LOG_RETENTION_DAYS` environment settings. `GET /stats` is public. Raw event/log reads always require a configured `TELEMETRY_API_KEY`. When a key is configured, ingestion requires the same `X-API-Key`; without one, `POST /events` remains public write-only for deployed installer clients. Keep the service behind TLS and reverse-proxy request limits.
