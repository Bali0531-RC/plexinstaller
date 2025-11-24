# PlexInstaller Telemetry Server

A lightweight FastAPI application that tracks installer outcomes (success, failure, failure step counts) and stores per-session logs submitted by the PlexInstaller telemetry client.

## Running Locally

```bash
cd telemetry
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 9000
```

## API Surface

| Method | Path          | Description                                      |
|--------|---------------|--------------------------------------------------|
| POST   | `/events`     | Accepts telemetry payloads from the installer.   |
| GET    | `/stats`      | Returns aggregate success/failure statistics.    |
| GET    | `/events`     | Lists recent telemetry events (JSONL backed).    |
| GET    | `/logs`       | Lists stored log filenames.                      |
| GET    | `/logs/{id}`  | Returns the saved log contents for a session.    |

All telemetry data and logs are written to `telemetry/data/` by default.
