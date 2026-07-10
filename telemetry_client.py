"""Telemetry client for PlexInstaller."""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# Patterns to redact from log output
_REDACT_PATTERNS = [
    # MongoDB connection strings with credentials
    re.compile(r"mongodb(?:\+srv)?://[^:]+:[^@]+@", re.IGNORECASE),
    # Generic password/token/secret key-value patterns
    re.compile(r"(password|passwd|token|secret|api_key|apikey|auth)\s*[=:]\s*\S+", re.IGNORECASE),
    # Bearer tokens
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
]

_SAFE_COMPONENT_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")
_MAX_COMPONENT_LENGTH = 64


def _redact(text: str) -> str:
    """Redact sensitive information from text before logging."""
    result = text
    for pattern in _REDACT_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    return result


def _sanitize_component(value: str, fallback: str, *, max_length: int = _MAX_COMPONENT_LENGTH) -> str:
    """Return a bounded component safe for identifiers and filenames."""
    sanitized = _SAFE_COMPONENT_PATTERN.sub("-", str(value)).strip("-_")
    return (sanitized[:max_length] or fallback).lower()


@dataclass
class TelemetrySummary:
    """Summary returned after finishing a telemetry session."""

    session_id: str
    status: str
    failure_step: str | None
    error: str | None
    log_path: Path | None
    events: list[dict[str, Any]]


class TelemetryClient:
    """Small helper that logs installer steps and pushes them to the telemetry API."""

    def __init__(
        self,
        endpoint: str,
        log_dir: Path,
        paste_endpoint: str,
        enabled: bool = True,
        api_key: str | None = None,
    ):
        self.enabled = enabled
        self.endpoint = endpoint.rstrip("/") if endpoint else ""
        self.log_dir = log_dir
        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            self.log_dir.chmod(0o700)
        self.paste_endpoint = paste_endpoint
        self.api_key = os.environ.get("PLEX_TELEMETRY_API_KEY") if api_key is None else api_key

        self._active = False
        self._session_id: str | None = None
        self._product: str | None = None
        self._instance: str | None = None
        self._current_log_path: Path | None = None
        self._events: list[dict[str, Any]] = []

    @property
    def log_path(self) -> Path | None:
        return self._current_log_path

    def start_session(self, product: str, instance: str) -> str:
        """Start a new telemetry session for a product installation."""
        if not self.enabled:
            return ""

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_product = _sanitize_component(product, "unknown-product", max_length=40)
        safe_instance = _sanitize_component(instance, "default", max_length=32)
        nonce = secrets.token_hex(4)
        self._session_id = f"{timestamp}-{safe_product}-{safe_instance}-{nonce}"
        self._product = safe_product
        self._instance = safe_instance
        self._current_log_path = self.log_dir / f"{self._session_id}.log"
        self._events = []
        self._active = True

        self._write_line(f"Session {self._session_id} started for {safe_product} (instance: {safe_instance})")
        return self._session_id

    def log_step(self, step: str, status: str, detail: str | None = None):
        """Record a step result inside the session log."""
        if not self.enabled or not self._active or not self._session_id:
            return

        safe_step = _sanitize_component(step, "unknown-step")
        safe_status = _sanitize_component(status, "unknown")
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": safe_step,
            "status": safe_status,
            "detail": _redact(detail) if detail else "",
        }
        self._events.append(entry)

        detail_str = f" — {_redact(detail)}" if detail else ""
        self._write_line(f"[{entry['timestamp']}] {safe_step}: {safe_status.upper()}{detail_str}")

    def finish_session(
        self,
        status: str,
        failure_step: str | None = None,
        error: str | None = None,
    ) -> TelemetrySummary | None:
        """Finalize the session and push data to the telemetry API."""
        if not self.enabled or not self._active or not self._session_id:
            return None

        safe_status = _sanitize_component(status, "unknown")
        safe_failure_step = _sanitize_component(failure_step, "unknown-step") if failure_step else None
        safe_error = _redact(error) if error else None
        summary = TelemetrySummary(
            session_id=self._session_id,
            status=safe_status,
            failure_step=safe_failure_step,
            error=safe_error,
            log_path=self._current_log_path,
            events=self._events.copy(),
        )

        if safe_error:
            self._write_line(f"Session error: {safe_error}")
        self._write_line(f"Session completed with status: {safe_status.upper()}")

        payload: dict[str, Any] = {
            "session_id": summary.session_id,
            "product": self._product,
            "instance": self._instance,
            "status": safe_status,
            "failure_step": safe_failure_step,
            "error": safe_error,
            "events": summary.events,
            "log": self._read_log_contents(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._post_payload(payload)

        self._active = False
        self._session_id = None
        return summary

    def share_log(self) -> str | None:
        """Upload the current log file to the configured paste service."""
        if (
            not self.enabled
            or not self.paste_endpoint
            or not self._current_log_path
            or not self._current_log_path.exists()
        ):
            return None

        try:
            contents = self._current_log_path.read_text()
            response = requests.post(
                self.paste_endpoint,
                data=contents.encode("utf-8"),
                headers=self._headers(content_type="text/plain"),
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("url") or data.get("key") or None
        except requests.RequestException:
            return None

    def _read_log_contents(self) -> str:
        if self.enabled and self._current_log_path and self._current_log_path.exists():
            return self._current_log_path.read_text()
        return ""

    def _post_payload(self, payload: dict[str, Any]):
        if not self.enabled or not self.endpoint:
            return
        try:
            response = requests.post(
                f"{self.endpoint}/events",
                json=payload,
                headers=self._headers(),
                timeout=5,
            )
            response.raise_for_status()
        except requests.RequestException:
            pass

    def _headers(self, *, content_type: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    def _write_line(self, message: str):
        if not self.enabled or not self._current_log_path:
            return
        timestamp = datetime.now(timezone.utc).isoformat()
        fd = os.open(self._current_log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} :: {message}\n")
        self._current_log_path.chmod(0o600)
