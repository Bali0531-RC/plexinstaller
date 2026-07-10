"""Hardened FastAPI server for PlexInstaller telemetry collection."""

from __future__ import annotations

import fcntl
import hmac
import json
import os
import re
import tempfile
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("TELEMETRY_DATA_DIR", BASE_DIR / "data"))
LOG_DIR = DATA_DIR / "logs"
STATS_FILE = DATA_DIR / "stats.json"
EVENTS_FILE = DATA_DIR / "events.jsonl"
LOCK_FILE = DATA_DIR / ".stats.lock"

TELEMETRY_API_KEY = os.environ.get("TELEMETRY_API_KEY", "")

RATE_LIMIT_MAX = 60
RATE_LIMIT_WINDOW = 60
MAX_REQUEST_BYTES = int(os.environ.get("TELEMETRY_MAX_REQUEST_BYTES", str(1024 * 1024)))
MAX_EVENTS_FILE_BYTES = int(os.environ.get("TELEMETRY_MAX_EVENTS_BYTES", str(32 * 1024 * 1024)))
MAX_TOTAL_LOG_BYTES = int(os.environ.get("TELEMETRY_MAX_LOG_BYTES", str(128 * 1024 * 1024)))
MAX_LOG_FILES = int(os.environ.get("TELEMETRY_MAX_LOG_FILES", "2000"))
MAX_LOG_AGE_DAYS = int(os.environ.get("TELEMETRY_LOG_RETENTION_DAYS", "30"))
MAX_EVENT_LIST_LIMIT = 200
MAX_RECENT_STATS = 20

SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _ensure_storage() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    DATA_DIR.chmod(0o700)
    LOG_DIR.chmod(0o700)


_ensure_storage()


def _validate_session_id(session_id: str) -> str:
    """Validate a session identifier before using it as a filename."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")
    return session_id


def _check_rate_limit(client_ip: str) -> None:
    """Apply a bounded in-memory per-IP request limit."""
    now = time.monotonic()
    timestamps = [stamp for stamp in _rate_limit_store[client_ip] if now - stamp < RATE_LIMIT_WINDOW]
    if len(timestamps) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    timestamps.append(now)
    _rate_limit_store[client_ip] = timestamps


async def verify_api_key(request: Request) -> None:
    """Require a configured API key and compare it in constant time."""
    if not TELEMETRY_API_KEY:
        raise HTTPException(status_code=503, detail="Raw telemetry API is disabled until an API key is configured")
    supplied_key = request.headers.get("X-API-Key", "")
    if not hmac.compare_digest(supplied_key.encode(), TELEMETRY_API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def verify_ingest_key(request: Request) -> None:
    """Allow write-only ingest without a key, or enforce the configured key."""
    if TELEMETRY_API_KEY:
        await verify_api_key(request)


@contextmanager
def _file_lock() -> Iterator[None]:
    """Serialize stats, event archive, and retention updates across workers."""
    _ensure_storage()
    lock_fd = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT, 0o600)
    with os.fdopen(lock_fd, "w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def _default_stats() -> dict[str, Any]:
    return {
        "success": 0,
        "failure": 0,
        "uncompleted": 0,
        "failures_by_step": {},
        "most_recent": [],
    }


def _load_stats() -> dict[str, Any]:
    if STATS_FILE.exists():
        try:
            data = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return _default_stats()
            if "other" in data:
                data["uncompleted"] = int(data.pop("other")) + int(data.get("uncompleted", 0))
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return _default_stats()
    return _default_stats()


def _atomic_write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Write text privately and atomically replace the target."""
    _ensure_storage()
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        path.chmod(mode)
    finally:
        temp_path.unlink(missing_ok=True)


def _save_stats(stats: dict[str, Any]) -> None:
    _atomic_write_text(STATS_FILE, json.dumps(stats, indent=2))


def _derive_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Return public aggregate statistics without raw session metadata."""
    success = max(0, int(stats.get("success", 0)))
    failure = max(0, int(stats.get("failure", 0)))
    uncompleted = max(0, int(stats.get("uncompleted", 0)))
    counted = success + failure
    total = counted + uncompleted
    failures = stats.get("failures_by_step", {})
    if not isinstance(failures, dict):
        failures = {}
    return {
        "success": success,
        "failure": failure,
        "uncompleted": uncompleted,
        "failures_by_step": failures,
        "total": total,
        "success_rate": round((success / counted) * 100, 2) if counted else 0.0,
        "completion_rate": round((counted / total) * 100, 2) if total else 0.0,
    }


class TelemetryEvent(BaseModel):
    """A bounded installer step event."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str = Field(min_length=1, max_length=64)
    step: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    status: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    detail: str = Field(default="", max_length=4096)


class TelemetryPayload(BaseModel):
    """Strict, bounded telemetry request body."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    product: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    instance: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    status: Literal["success", "failure", "uncompleted"]
    failure_step: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    error: str | None = Field(default=None, max_length=8192)
    events: list[TelemetryEvent] = Field(default_factory=list, max_length=200)
    log: str | None = Field(default=None, max_length=512 * 1024)
    timestamp: str = Field(min_length=1, max_length=64)


def _rotate_events_if_needed(incoming_bytes: int) -> None:
    """Rotate the JSONL archive before it exceeds its configured cap."""
    current_size = EVENTS_FILE.stat().st_size if EVENTS_FILE.exists() else 0
    if current_size + incoming_bytes <= MAX_EVENTS_FILE_BYTES:
        return
    rotated = EVENTS_FILE.with_suffix(".jsonl.1")
    rotated.unlink(missing_ok=True)
    if EVENTS_FILE.exists():
        os.replace(EVENTS_FILE, rotated)
        rotated.chmod(0o600)


def _append_event(payload: TelemetryPayload) -> None:
    encoded = (payload.model_dump_json() + "\n").encode("utf-8")
    if len(encoded) > MAX_EVENTS_FILE_BYTES:
        raise HTTPException(status_code=413, detail="Telemetry event exceeds archive capacity")
    _rotate_events_if_needed(len(encoded))
    fd = os.open(EVENTS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "ab") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    EVENTS_FILE.chmod(0o600)


def _prune_logs() -> None:
    """Apply age, file-count, and total-byte retention limits."""
    cutoff = time.time() - max(0, MAX_LOG_AGE_DAYS) * 86400
    logs: list[tuple[Path, os.stat_result]] = []
    for path in LOG_DIR.glob("*.log"):
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_mtime < cutoff:
            path.unlink(missing_ok=True)
        else:
            logs.append((path, stat))

    logs.sort(key=lambda item: item[1].st_mtime, reverse=True)
    total_bytes = 0
    for index, (path, stat) in enumerate(logs):
        if index >= MAX_LOG_FILES or total_bytes + stat.st_size > MAX_TOTAL_LOG_BYTES:
            path.unlink(missing_ok=True)
        else:
            total_bytes += stat.st_size


def _iter_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    """Read a bounded tail and skip malformed/non-object JSONL records."""
    if not path.exists():
        return []
    valid: deque[dict[str, Any]] = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    valid.append(value)
    except OSError:
        return []
    return list(valid)


app = FastAPI(title="PlexInstaller Telemetry", version="2.0.0")


@app.middleware("http")
async def request_guards(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    try:
        _check_rate_limit(client_ip)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header"})
    if request.method in {"POST", "PUT", "PATCH"}:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_REQUEST_BYTES:
                return JSONResponse(status_code=413, content={"detail": "Request body too large"})
        # BaseHTTPMiddleware wraps this as Starlette's _CachedRequest. Setting
        # _body makes wrapped_receive replay the complete, bounded payload to
        # FastAPI instead of treating our already-consumed stream as empty.
        request._body = bytes(body)
    return await call_next(request)


@app.post("/events", dependencies=[Depends(verify_ingest_key)])
async def add_event(payload: TelemetryPayload):
    _validate_session_id(payload.session_id)
    with _file_lock():
        stats = _load_stats()
        stats[payload.status] = int(stats.get(payload.status, 0)) + 1
        if payload.status == "failure" and payload.failure_step:
            failures = stats.setdefault("failures_by_step", {})
            failures[payload.failure_step] = int(failures.get(payload.failure_step, 0)) + 1
        recent = stats.setdefault("most_recent", [])
        recent.insert(
            0,
            {
                "session_id": payload.session_id,
                "product": payload.product,
                "status": payload.status,
                "timestamp": payload.timestamp,
                "failure_step": payload.failure_step,
            },
        )
        stats["most_recent"] = recent[:MAX_RECENT_STATS]
        _save_stats(stats)
        _append_event(payload)
        if payload.log:
            _atomic_write_text(LOG_DIR / f"{payload.session_id}.log", payload.log)
        _prune_logs()
    return {"ok": True}


@app.get("/stats")
async def get_stats():
    return _derive_stats(_load_stats())


@app.get("/events", dependencies=[Depends(verify_api_key)])
async def list_events(limit: Annotated[int, Query(ge=1, le=MAX_EVENT_LIST_LIMIT)] = 50):
    events = _iter_jsonl_tail(EVENTS_FILE.with_suffix(".jsonl.1"), limit)
    events.extend(_iter_jsonl_tail(EVENTS_FILE, limit))
    return events[-limit:]


@app.get("/logs", dependencies=[Depends(verify_api_key)])
async def list_logs(limit: Annotated[int, Query(ge=1, le=MAX_EVENT_LIST_LIMIT)] = 50):
    logs = []
    for path in LOG_DIR.glob("*.log"):
        try:
            logs.append((path.stat().st_mtime, path.name))
        except OSError:
            continue
    logs.sort(reverse=True)
    return [name for _, name in logs[:limit]]


@app.get("/logs/{session_id}", dependencies=[Depends(verify_api_key)])
async def get_log(session_id: str):
    _validate_session_id(session_id)
    target = LOG_DIR / f"{session_id}.log"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Log not found")
    try:
        log = target.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="Could not read log") from exc
    return {"session_id": session_id, "log": log}


def _startup_validate() -> None:
    """Validate security-sensitive runtime configuration."""
    _ensure_storage()
    if TELEMETRY_API_KEY and len(TELEMETRY_API_KEY) < 16:
        raise RuntimeError("TELEMETRY_API_KEY must contain at least 16 characters")
    if min(MAX_REQUEST_BYTES, MAX_EVENTS_FILE_BYTES, MAX_TOTAL_LOG_BYTES, MAX_LOG_FILES) <= 0:
        raise RuntimeError("Telemetry storage and request limits must be positive")
    with _file_lock():
        _prune_logs()


_startup_validate()
