"""Telemetry client for PlexInstaller."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


@dataclass
class TelemetrySummary:
    """Summary returned after finishing a telemetry session."""

    session_id: str
    status: str
    failure_step: Optional[str]
    error: Optional[str]
    log_path: Optional[Path]
    events: List[Dict[str, Any]]


class TelemetryClient:
    """Small helper that logs installer steps and pushes them to the telemetry API."""

    def __init__(self, endpoint: str, log_dir: Path, paste_endpoint: str, enabled: bool = True):
        self.enabled = enabled
        self.endpoint = endpoint.rstrip("/") if endpoint else ""
        self.log_dir = log_dir
        if self.enabled:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self.paste_endpoint = paste_endpoint

        self._active = False
        self._session_id: Optional[str] = None
        self._product: Optional[str] = None
        self._instance: Optional[str] = None
        self._current_log_path: Optional[Path] = None
        self._events: List[Dict[str, Any]] = []

    @property
    def log_path(self) -> Optional[Path]:
        return self._current_log_path

    def start_session(self, product: str, instance: str) -> str:
        """Start a new telemetry session for a product installation."""
        if not self.enabled:
            return ""

        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        self._session_id = f"{timestamp}-{product}-{instance}"
        self._product = product
        self._instance = instance
        self._current_log_path = self.log_dir / f"{self._session_id}.log"
        self._events = []
        self._active = True

        self._write_line(
            f"Session {self._session_id} started for {product} (instance: {instance})"
        )
        return self._session_id

    def log_step(self, step: str, status: str, detail: Optional[str] = None):
        """Record a step result inside the session log."""
        if not self.enabled or not self._active or not self._session_id:
            return

        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "step": step,
            "status": status,
            "detail": detail or "",
        }
        self._events.append(entry)

        detail_str = f" — {detail}" if detail else ""
        self._write_line(f"[{entry['timestamp']}] {step}: {status.upper()}{detail_str}")

    def finish_session(
        self,
        status: str,
        failure_step: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[TelemetrySummary]:
        """Finalize the session and push data to the telemetry API."""
        if not self.enabled or not self._active or not self._session_id:
            return None

        summary = TelemetrySummary(
            session_id=self._session_id,
            status=status,
            failure_step=failure_step,
            error=error,
            log_path=self._current_log_path,
            events=self._events.copy(),
        )

        if error:
            self._write_line(f"Session error: {error}")
        self._write_line(f"Session completed with status: {status.upper()}")

        payload: Dict[str, Any] = {
            "session_id": summary.session_id,
            "product": self._product,
            "instance": self._instance,
            "status": status,
            "failure_step": failure_step,
            "error": error,
            "events": self._events,
            "log": self._read_log_contents(),
            "timestamp": datetime.utcnow().isoformat(),
        }

        self._post_payload(payload)

        self._active = False
        self._session_id = None
        return summary

    def share_log(self) -> Optional[str]:
        """Upload the current log file to the configured paste service."""
        if (not self.enabled or not self.paste_endpoint or
            not self._current_log_path or not self._current_log_path.exists()):
            return None

        try:
            contents = self._current_log_path.read_text()
            response = requests.post(
                self.paste_endpoint,
                data=contents.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("url") or data.get("key")
        except requests.RequestException:
            return None

    def _read_log_contents(self) -> str:
        if self.enabled and self._current_log_path and self._current_log_path.exists():
            return self._current_log_path.read_text()
        return ""

    def _post_payload(self, payload: Dict[str, Any]):
        if not self.enabled or not self.endpoint:
            return
        try:
            requests.post(
                f"{self.endpoint}/events",
                json=payload,
                timeout=5,
            )
        except requests.RequestException:
            pass

    def _write_line(self, message: str):
        if not self.enabled or not self._current_log_path:
            return
        timestamp = datetime.utcnow().isoformat()
        with self._current_log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} :: {message}\n")