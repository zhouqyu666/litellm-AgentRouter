#!/usr/bin/env python3
"""
Safe .env file reader/writer with atomic writes and backup rotation.
"""

from __future__ import annotations

import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

if sys.platform != "win32":
    import fcntl
else:
    fcntl = None


def _flock_lock(f, flag: int) -> None:
    """Acquire file lock, no-op on Windows."""
    if fcntl is not None:
        fcntl.flock(f.fileno(), flag)


def _flock_unlock(f) -> None:
    """Release file lock, no-op on Windows."""
    if fcntl is not None:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


class EnvFile:
    """Manages reading and writing the .env file safely."""

    MAX_BACKUPS = 5

    def __init__(self, path: Optional[str] = None):
        if path:
            self._path = Path(path)
        elif Path("/app/.env").is_file():
            self._path = Path("/app/.env")
        else:
            self._path = Path(__file__).resolve().parent.parent.parent / ".env"

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def read(self) -> Dict[str, str]:
        """Read all key=value pairs from .env."""
        result: Dict[str, str] = {}
        if not self.exists():
            return result
        for raw_line in self._path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            if key:
                result[key] = value
        return result

    def read_raw(self) -> str:
        """Read raw .env file content."""
        if not self.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def get(self, key: str) -> Optional[str]:
        """Get a single value by key."""
        return self.read().get(key)

    def set(self, key: str, value: str) -> None:
        """Set a single key=value pair, preserving comments and structure."""
        self._set_items({key: value})

    def set_many(self, items: Dict[str, str]) -> None:
        """Set multiple key=value pairs at once."""
        self._set_items(items)

    def delete(self, key_prefix: str) -> List[str]:
        """Delete all keys matching prefix. Returns list of deleted keys."""
        if not self.exists():
            return []

        deleted: List[str] = []
        lines: List[str] = []
        prefix_upper = key_prefix.upper()

        with open(self._path, "r", encoding="utf-8") as f:
            _flock_lock(f, fcntl.LOCK_EX if fcntl else 0)
            try:
                for raw_line in f.read().splitlines():
                    line = raw_line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k = line.split("=", 1)[0].strip()
                        if k.upper().startswith(prefix_upper):
                            deleted.append(k)
                            continue
                    lines.append(raw_line)
            finally:
                _flock_unlock(f)

        self._write_lines(lines)
        return deleted

    def delete_key(self, key: str) -> bool:
        """Delete a single exact key. Returns True if found and deleted."""
        return len(self._delete_exact(key)) > 0

    def _delete_exact(self, key: str) -> List[str]:
        """Delete a single exact key from .env file."""
        if not self.exists():
            return []

        deleted: List[str] = []
        lines: List[str] = []
        key_upper = key.upper()

        with open(self._path, "r", encoding="utf-8") as f:
            _flock_lock(f, fcntl.LOCK_EX if fcntl else 0)
            try:
                for raw_line in f.read().splitlines():
                    line = raw_line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k = line.split("=", 1)[0].strip()
                        if k.upper() == key_upper:
                            deleted.append(k)
                            continue
                    lines.append(raw_line)
            finally:
                _flock_unlock(f)

        if deleted:
            self._write_lines(lines)
        return deleted

    def backup(self) -> str:
        """Create a timestamped backup. Returns backup path."""
        if not self.exists():
            return ""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = str(self._path) + f".backup.{timestamp}"
        shutil.copy2(str(self._path), backup_path)
        self._rotate_backups()
        return backup_path

    def _set_items(self, items: Dict[str, str]) -> None:
        """Set multiple items, preserving file structure."""
        self.backup()

        if not self.exists():
            lines: List[str] = []
            for key, value in items.items():
                lines.append(f"{key}={value}")
            self._write_lines(lines)
            return

        with open(self._path, "r", encoding="utf-8") as f:
            _flock_lock(f, fcntl.LOCK_EX if fcntl else 0)
            try:
                raw = f.read()
            finally:
                _flock_unlock(f)

        lines = raw.splitlines()
        updated_keys: set = set()
        last_model_line_idx = -1

        for i, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            if stripped.startswith("MODEL_"):
                last_model_line_idx = i

        new_lines: List[str] = []
        for raw_line in lines:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in items:
                    new_lines.append(f"{k}={items[k]}")
                    updated_keys.add(k)
                    continue
            new_lines.append(raw_line)

        remaining = {k: v for k, v in items.items() if k not in updated_keys}
        if remaining:
            if last_model_line_idx >= 0:
                insert_pos = last_model_line_idx + 1
                for idx, (k, v) in enumerate(remaining.items()):
                    new_lines.insert(insert_pos + idx, f"{k}={v}")
            else:
                if new_lines and new_lines[-1] != "":
                    new_lines.append("")
                for k, v in remaining.items():
                    new_lines.append(f"{k}={v}")

        self._write_lines(new_lines)

    def _write_lines(self, lines: List[str]) -> None:
        """Write lines to .env atomically."""
        tmp_path = str(self._path) + ".tmp"
        content = "\n".join(lines)
        if content and not content.endswith("\n"):
            content += "\n"

        with open(tmp_path, "w", encoding="utf-8") as f:
            _flock_lock(f, fcntl.LOCK_EX if fcntl else 0)
            try:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())
            finally:
                _flock_unlock(f)

        try:
            os.replace(tmp_path, str(self._path))
        except OSError:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _rotate_backups(self) -> None:
        """Keep only the most recent backups."""
        parent = self._path.parent
        stem = self._path.name
        backups = sorted(parent.glob(f"{stem}.backup.*"), reverse=True)
        for old in backups[self.MAX_BACKUPS:]:
            old.unlink(missing_ok=True)
