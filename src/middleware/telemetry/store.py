#!/usr/bin/env python3
"""SQLite-backed telemetry store for admin request inspection."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Any, Iterator


class TelemetryStore:
    """Persist recent request telemetry and provide aggregate usage totals."""

    def __init__(self, max_events: int = 10000, db_path: str | None = None):
        self.max_events = max_events
        self.db_path = db_path or self._default_db_path()
        self._lock = RLock()
        self._memory_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    def clear(self) -> None:
        """Remove all stored telemetry."""
        with self._lock, self._connection() as conn:
            conn.execute("DELETE FROM request_logs")
            conn.commit()

    def record(self, event: dict[str, Any]) -> None:
        """Record a completed or failed request event."""
        if event.get("event_type") not in {"ResponseCompleted", "ErrorRaised"}:
            return

        request = self._normalize_event(event)
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO request_logs (
                    timestamp, client_request_id, remote_addr, method, path,
                    model_alias, upstream_model, status_code, duration_s,
                    streaming, prompt_tokens, completion_tokens, total_tokens,
                    reasoning_tokens, missing_usage, parse_error, error_type,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request["timestamp"],
                    request["client_request_id"],
                    request["remote_addr"],
                    request["method"],
                    request["path"],
                    request["model_alias"],
                    request["upstream_model"],
                    request["status_code"],
                    request["duration_s"],
                    int(request["streaming"]),
                    request["usage"]["prompt_tokens"],
                    request["usage"]["completion_tokens"],
                    request["usage"]["total_tokens"],
                    request["usage"]["reasoning_tokens"],
                    int(request["missing_usage"]),
                    int(request["parse_error"]),
                    request["error_type"],
                    request["error_message"],
                ),
            )
            self._trim_old_rows(conn)
            conn.commit()

    def list_requests(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return recent requests, newest first."""
        safe_limit = self.max_events if limit is None else max(1, min(limit, self.max_events))
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM request_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [self._row_to_request(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        """Return aggregate usage totals grouped by model alias."""
        with self._lock, self._connection() as conn:
            total_row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_requests,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens
                FROM request_logs
                """
            ).fetchone()
            model_rows = conn.execute(
                """
                SELECT
                    model_alias,
                    MAX(upstream_model) AS upstream_model,
                    COUNT(*) AS request_count,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens
                FROM request_logs
                GROUP BY model_alias
                ORDER BY total_tokens DESC, request_count DESC, model_alias ASC
                """
            ).fetchall()

        return {
            "total_requests": int(total_row["total_requests"] or 0),
            "total_tokens": int(total_row["total_tokens"] or 0),
            "prompt_tokens": int(total_row["prompt_tokens"] or 0),
            "completion_tokens": int(total_row["completion_tokens"] or 0),
            "reasoning_tokens": int(total_row["reasoning_tokens"] or 0),
            "models": [
                {
                    "model_alias": row["model_alias"] or "unknown",
                    "upstream_model": row["upstream_model"] or "unknown",
                    "request_count": int(row["request_count"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "reasoning_tokens": int(row["reasoning_tokens"] or 0),
                }
                for row in model_rows
            ],
        }

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if self._memory_conn is not None:
            yield self._memory_conn
            return

        with self._connect() as conn:
            yield conn

    def _init_db(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._lock, self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    client_request_id TEXT,
                    remote_addr TEXT,
                    method TEXT,
                    path TEXT,
                    model_alias TEXT NOT NULL,
                    upstream_model TEXT,
                    status_code INTEGER,
                    duration_s REAL,
                    streaming INTEGER NOT NULL DEFAULT 0,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    reasoning_tokens INTEGER NOT NULL DEFAULT 0,
                    missing_usage INTEGER NOT NULL DEFAULT 0,
                    parse_error INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_logs_model ON request_logs(model_alias)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_logs_created ON request_logs(id DESC)"
            )
            conn.commit()

    def _trim_old_rows(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            DELETE FROM request_logs
            WHERE id NOT IN (
                SELECT id FROM request_logs ORDER BY id DESC LIMIT ?
            )
            """,
            (self.max_events,),
        )

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        usage = self._normalize_usage(event.get("usage"))
        return {
            "timestamp": event.get("timestamp"),
            "client_request_id": event.get("client_request_id"),
            "remote_addr": event.get("remote_addr"),
            "method": event.get("method"),
            "path": event.get("path"),
            "model_alias": event.get("model_alias") or "unknown",
            "upstream_model": event.get("upstream_model") or "unknown",
            "status_code": event.get("status_code"),
            "duration_s": event.get("duration_s"),
            "streaming": bool(event.get("streaming")),
            "usage": usage,
            "missing_usage": bool(event.get("missing_usage")),
            "parse_error": bool(event.get("parse_error")),
            "error_type": event.get("error_type"),
            "error_message": event.get("error_message"),
        }

    def _normalize_usage(self, usage: Any) -> dict[str, int]:
        if usage is None:
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "reasoning_tokens": 0,
            }

        if hasattr(usage, "__dict__"):
            raw_usage = usage.__dict__
        else:
            raw_usage = dict(usage)

        prompt_tokens = raw_usage.get("prompt_tokens", raw_usage.get("prompt", 0))
        completion_tokens = raw_usage.get("completion_tokens", raw_usage.get("completion", 0))
        total_tokens = raw_usage.get("total_tokens", raw_usage.get("total"))
        reasoning_tokens = raw_usage.get("reasoning_tokens", raw_usage.get("reasoning", 0))

        if total_tokens is None:
            total_tokens = int(prompt_tokens or 0) + int(completion_tokens or 0)

        return {
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "total_tokens": int(total_tokens or 0),
            "reasoning_tokens": int(reasoning_tokens or 0),
        }

    def _row_to_request(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "timestamp": row["timestamp"],
            "client_request_id": row["client_request_id"],
            "remote_addr": row["remote_addr"],
            "method": row["method"],
            "path": row["path"],
            "model_alias": row["model_alias"],
            "upstream_model": row["upstream_model"],
            "status_code": row["status_code"],
            "duration_s": row["duration_s"],
            "streaming": bool(row["streaming"]),
            "usage": {
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "reasoning_tokens": int(row["reasoning_tokens"] or 0),
            },
            "missing_usage": bool(row["missing_usage"]),
            "parse_error": bool(row["parse_error"]),
            "error_type": row["error_type"],
            "error_message": row["error_message"],
        }

    def _default_db_path(self) -> str:
        return os.getenv("TELEMETRY_DB_PATH", "data/telemetry.sqlite3")


telemetry_store = TelemetryStore()
