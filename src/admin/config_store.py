#!/usr/bin/env python3
"""SQLite-backed configuration store for models, API keys, and settings."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Optional


class ConfigStore:
    """Persist models, API keys, and admin settings in SQLite."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self._default_db_path()
        self._lock = RLock()
        self._memory_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row
        self._init_db()

    @staticmethod
    def _default_db_path() -> str:
        return os.getenv("CONFIG_DB_PATH", "data/config.sqlite3")

    # ------------------------------------------------------------------
    # connection management
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        with self._lock, self._connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT NOT NULL UNIQUE,
                    upstream_model TEXT NOT NULL,
                    upstream_base TEXT,
                    provider TEXT,
                    reasoning_effort TEXT,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    key_value TEXT NOT NULL,
                    key_index INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_api_keys_provider
                    ON api_keys(provider, key_index);

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                );
                """
            )
            conn.commit()

    # ------------------------------------------------------------------
    # model CRUD
    # ------------------------------------------------------------------

    def get_all_models(self) -> list[dict[str, Any]]:
        """Return all model definitions ordered by key."""
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM models ORDER BY key ASC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_model(self, key: str) -> dict[str, Any] | None:
        """Get a single model by its key (case-insensitive)."""
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM models WHERE key = ?", (key.upper(),)
            ).fetchone()
        return dict(row) if row else None

    def save_model(
        self,
        key: str,
        upstream_model: str,
        *,
        upstream_base: str | None = None,
        provider: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Insert or replace a model definition."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO models (key, upstream_model, upstream_base, provider,
                                    reasoning_effort, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    upstream_model=excluded.upstream_model,
                    upstream_base=excluded.upstream_base,
                    provider=excluded.provider,
                    reasoning_effort=excluded.reasoning_effort,
                    updated_at=excluded.updated_at
                """,
                (key.upper(), upstream_model, upstream_base, provider,
                 reasoning_effort, now),
            )
            conn.commit()

    def delete_model(self, key: str) -> bool:
        """Delete a model by key. Returns True if a row was removed."""
        with self._lock, self._connection() as conn:
            cur = conn.execute(
                "DELETE FROM models WHERE key = ?", (key.upper(),)
            )
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # API key CRUD
    # ------------------------------------------------------------------

    def get_api_keys(self, provider: str) -> list[str]:
        """Return API keys for a provider, ordered by key_index."""
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT key_value FROM api_keys WHERE provider = ? ORDER BY key_index",
                (provider.lower(),),
            ).fetchall()
        return [r["key_value"] for r in rows]

    def set_api_keys(self, provider: str, keys: list[str]) -> None:
        """Replace all API keys for a provider."""
        with self._lock, self._connection() as conn:
            conn.execute(
                "DELETE FROM api_keys WHERE provider = ?", (provider.lower(),)
            )
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            for idx, key_val in enumerate(keys):
                conn.execute(
                    "INSERT INTO api_keys (provider, key_value, key_index, created_at) VALUES (?, ?, ?, ?)",
                    (provider.lower(), key_val, idx, now),
                )
            conn.commit()

    def add_api_key(self, provider: str, key_value: str) -> int:
        """Append a single API key. Returns the new total count."""
        with self._lock, self._connection() as conn:
            max_idx = conn.execute(
                "SELECT COALESCE(MAX(key_index), -1) FROM api_keys WHERE provider = ?",
                (provider.lower(),),
            ).fetchone()[0]
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "INSERT INTO api_keys (provider, key_value, key_index, created_at) VALUES (?, ?, ?, ?)",
                (provider.lower(), key_value, max_idx + 1, now),
            )
            conn.commit()
            return max_idx + 2  # total count

    def remove_api_key(self, provider: str, index: int) -> str | None:
        """Remove an API key by index. Returns the removed key value or None."""
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT key_value FROM api_keys WHERE provider = ? AND key_index = ?",
                (provider.lower(), index),
            ).fetchone()
            if not row:
                return None
            removed = row["key_value"]
            conn.execute(
                "DELETE FROM api_keys WHERE provider = ? AND key_index = ?",
                (provider.lower(), index),
            )
            # Re-index remaining keys
            rows = conn.execute(
                "SELECT id FROM api_keys WHERE provider = ? ORDER BY key_index",
                (provider.lower(),),
            ).fetchall()
            for new_idx, r in enumerate(rows):
                conn.execute(
                    "UPDATE api_keys SET key_index = ? WHERE id = ?",
                    (new_idx, r["id"]),
                )
            conn.commit()
            return removed

    def get_all_provider_keys(self) -> dict[str, list[str]]:
        """Return all API keys grouped by provider."""
        result: dict[str, list[str]] = {}
        with self._lock, self._connection() as conn:
            rows = conn.execute(
                "SELECT provider, key_value FROM api_keys ORDER BY provider, key_index"
            ).fetchall()
        for r in rows:
            result.setdefault(r["provider"], []).append(r["key_value"])
        return result

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        """Get a single setting value."""
        with self._lock, self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Set a single setting (upsert)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        with self._lock, self._connection() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
            conn.commit()

    def delete_setting(self, key: str) -> bool:
        """Delete a setting. Returns True if removed."""
        with self._lock, self._connection() as conn:
            cur = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # migration from .env
    # ------------------------------------------------------------------

    def migrate_from_env(self, env_data: dict[str, str]) -> dict[str, Any]:
        """Import models, keys, and settings from .env-style dict.

        Returns a summary of what was migrated.
        """
        import re

        model_pattern = re.compile(r"^MODEL_([A-Z0-9_]+)_UPSTREAM_MODEL$")
        summary: dict[str, Any] = {"models": 0, "keys": 0, "settings": 0}

        # Migrate models
        migrated_keys: set[str] = set()
        for env_key, value in sorted(env_data.items()):
            m = model_pattern.match(env_key)
            if not m:
                continue
            model_key = m.group(1)
            if model_key in migrated_keys:
                continue
            migrated_keys.add(model_key)

            upstream_base = env_data.get(f"MODEL_{model_key}_UPSTREAM_BASE")
            provider = env_data.get(f"MODEL_{model_key}_PROVIDER")
            reasoning = env_data.get(f"MODEL_{model_key}_REASONING_EFFORT")

            self.save_model(
                key=model_key,
                upstream_model=value,
                upstream_base=upstream_base,
                provider=provider,
                reasoning_effort=reasoning,
            )
            summary["models"] += 1

        # Migrate API keys
        from src.config.rendering import parse_api_keys

        for provider in ("openai", "anthropic"):
            keys: list[str] = []
            multi_str = env_data.get(f"{provider.upper()}_API_KEYS", "")
            if multi_str:
                keys = parse_api_keys(multi_str)
            if not keys:
                single = env_data.get(f"{provider.upper()}_API_KEY", "")
                if "," in single:
                    keys = parse_api_keys(single)
                elif single.strip():
                    keys = [single.strip()]
            if keys:
                self.set_api_keys(provider, keys)
                summary["keys"] += len(keys)

        # Migrate settings that are managed by the Admin UI.
        for setting_key in (
            "ADMIN_USERNAME",
            "ADMIN_PASSWORD",
            "LITELLM_MASTER_KEY",
            "UPSTREAM_PROXY_URL",
        ):
            val = env_data.get(setting_key)
            if val:
                self.set_setting(setting_key, val)
                summary["settings"] += 1

        return summary

    # ------------------------------------------------------------------
    # build env dict (for os.environ sync)
    # ------------------------------------------------------------------

    def build_model_env_vars(self) -> dict[str, str]:
        """Build MODEL_<KEY>_* environment variables from stored models.

        Returns a dict suitable for merging into os.environ.
        """
        result: dict[str, str] = {}
        for model in self.get_all_models():
            key = model["key"]
            result[f"MODEL_{key}_UPSTREAM_MODEL"] = model["upstream_model"]
            if model.get("upstream_base"):
                result[f"MODEL_{key}_UPSTREAM_BASE"] = model["upstream_base"]
            if model.get("provider"):
                result[f"MODEL_{key}_PROVIDER"] = model["provider"]
            if model.get("reasoning_effort"):
                result[f"MODEL_{key}_REASONING_EFFORT"] = model["reasoning_effort"]
        return result

    def build_key_env_vars(self) -> dict[str, str]:
        """Build *_API_KEYS environment variables from stored keys."""
        result: dict[str, str] = {}
        all_keys = self.get_all_provider_keys()
        for provider, keys in all_keys.items():
            if keys:
                result[f"{provider.upper()}_API_KEYS"] = ",".join(keys)
        return result

    def build_setting_env_vars(self) -> dict[str, str]:
        """Build environment variables for runtime settings stored in SQLite."""
        result: dict[str, str] = {}
        for key in (
            "LITELLM_MASTER_KEY",
            "ADMIN_USERNAME",
            "ADMIN_PASSWORD",
            "UPSTREAM_PROXY_URL",
        ):
            value = self.get_setting(key)
            if value:
                result[key] = value
        return result


def get_config_store() -> ConfigStore:
    """Return the process-wide configuration store."""
    return config_store


def set_config_store(store: ConfigStore) -> None:
    """Replace the process-wide configuration store.

    This is primarily used by tests and local tooling that need an isolated
    SQLite database without mutating the default runtime database.
    """
    global config_store
    config_store = store


# Singleton
config_store = ConfigStore()
