"""Minimal FastAPI server for PlexInstaller telemetry collection."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
STATS_FILE = DATA_DIR / "stats.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"

for path in (DATA_DIR, LOG_DIR):
    path.mkdir(parents=True, exist_ok=True)


def _load_stats() -> Dict[str, Any]:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text())
    return {
        "success": 0,
        "failure": 0,
        "other": 0,
        "failures_by_step": {},
        "most_recent": [],
    }


def _save_stats(stats: Dict[str, Any]):
    STATS_FILE.write_text(json.dumps(stats, indent=2))


def _derive_stats(stats: Dict[str, Any]) -> Dict[str, Any]:
    success = stats.get("success", 0)
    failure = stats.get("failure", 0)
    other = stats.get("other", 0)
    total = success + failure + other
    stats["total"] = total
    stats["success_rate"] = round((success / total) * 100, 2) if total else 0.0
    return stats


class TelemetryPayload(BaseModel):
    session_id: str
    product: str
    instance: Optional[str]
    status: str
    failure_step: Optional[str] = None
    error: Optional[str] = None
    events: List[Dict[str, str]] = []
    log: Optional[str] = None
    timestamp: str


app = FastAPI(title="PlexInstaller Telemetry", version="1.0.0")


@app.post("/events")
async def add_event(payload: TelemetryPayload):
    stats = _load_stats()

    if payload.status.lower() == "success":
        stats["success"] = stats.get("success", 0) + 1
    elif payload.status.lower() == "failure":
        stats["failure"] = stats.get("failure", 0) + 1
        if payload.failure_step:
            failures = stats.setdefault("failures_by_step", {})
            failures[payload.failure_step] = failures.get(payload.failure_step, 0) + 1
    else:
        stats.setdefault("other", 0)
        stats["other"] += 1

    recent = stats.setdefault("most_recent", [])
    recent.insert(0, {
        "session_id": payload.session_id,
        "product": payload.product,
        "status": payload.status,
        "timestamp": payload.timestamp,
        "failure_step": payload.failure_step,
    })
    stats["most_recent"] = recent[:20]

    _save_stats(stats)

    # Append JSONL event log
    with EVENTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(payload.model_dump_json() + "\n")

    if payload.log:
        log_target = LOG_DIR / f"{payload.session_id}.log"
        log_target.write_text(payload.log)

    return {"ok": True}


@app.get("/stats")
async def get_stats():
    stats = _derive_stats(_load_stats())
    return stats


@app.get("/events")
async def list_events(limit: int = 50):
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text().strip().splitlines()
    lines = lines[-limit:]
    return [json.loads(line) for line in lines]


@app.get("/logs")
async def list_logs():
    return [log.name for log in LOG_DIR.glob("*.log")]


@app.get("/logs/{session_id}")
async def get_log(session_id: str):
    target = LOG_DIR / f"{session_id}.log"
    if not target.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return {"session_id": session_id, "log": target.read_text()}
