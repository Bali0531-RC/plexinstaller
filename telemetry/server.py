"""Minimal FastAPI server for PlexInstaller telemetry collection."""

from __future__ import annotations

import fcntl
import json
import os
import re
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = DATA_DIR / "logs"
STATS_FILE = DATA_DIR / "stats.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"

for path in (DATA_DIR, LOG_DIR):
    path.mkdir(parents=True, exist_ok=True)

LOCK_FILE = DATA_DIR / ".stats.lock"

# Simple API key for telemetry authentication (set via TELEMETRY_API_KEY env var)
TELEMETRY_API_KEY = os.environ.get("TELEMETRY_API_KEY", "")

# In-memory rate limiter: IP -> list of timestamps
_rate_limit_store: Dict[str, list] = defaultdict(list)
RATE_LIMIT_MAX = 60  # requests per window
RATE_LIMIT_WINDOW = 60  # seconds

# Regex to validate session_id (alphanumeric, hyphens, underscores only)
SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_session_id(session_id: str) -> str:
    """Validate and sanitize session_id to prevent path traversal."""
    if not session_id or not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")
    if len(session_id) > 128:
        raise HTTPException(status_code=400, detail="session_id too long")
    return session_id


def _check_rate_limit(client_ip: str):
    """Simple in-memory rate limiter."""
    now = time.time()
    timestamps = _rate_limit_store[client_ip]
    # Remove old entries outside the window
    _rate_limit_store[client_ip] = [t for t in timestamps if now - t < RATE_LIMIT_WINDOW]
    if len(_rate_limit_store[client_ip]) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    _rate_limit_store[client_ip].append(now)


async def verify_api_key(request: Request):
    """Dependency to verify API key if configured."""
    if not TELEMETRY_API_KEY:
        return  # No key configured, allow all (dev mode)
    key = request.headers.get("X-API-Key", "")
    if key != TELEMETRY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@contextmanager
def _file_lock():
    """Context manager for file-based locking to prevent race conditions."""
    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _load_stats() -> Dict[str, Any]:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except json.JSONDecodeError:
            pass
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


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    try:
        _check_rate_limit(client_ip)
    except HTTPException as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    return await call_next(request)


@app.post("/events", dependencies=[Depends(verify_api_key)])
async def add_event(payload: TelemetryPayload):
    # Validate session_id to prevent path traversal
    _validate_session_id(payload.session_id)

    with _file_lock():
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
        # Verify the resolved path is inside LOG_DIR
        if not log_target.resolve().is_relative_to(LOG_DIR.resolve()):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        log_target.write_text(payload.log)

    return {"ok": True}


@app.get("/stats", dependencies=[Depends(verify_api_key)])
async def get_stats():
    stats = _derive_stats(_load_stats())
    return stats


@app.get("/events", dependencies=[Depends(verify_api_key)])
async def list_events(limit: int = 50):
    if not EVENTS_FILE.exists():
        return []
    lines = EVENTS_FILE.read_text().strip().splitlines()
    lines = lines[-limit:]
    return [json.loads(line) for line in lines]


@app.get("/logs", dependencies=[Depends(verify_api_key)])
async def list_logs():
    return [log.name for log in LOG_DIR.glob("*.log")]


@app.get("/logs/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_log(session_id: str):
    # Validate session_id to prevent path traversal
    _validate_session_id(session_id)

    target = LOG_DIR / f"{session_id}.log"
    # Double-check resolved path is inside LOG_DIR
    if not target.resolve().is_relative_to(LOG_DIR.resolve()):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Log not found")
    return {"session_id": session_id, "log": target.read_text()}
