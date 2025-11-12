#!/usr/bin/env python3
"""
Utility functions for LiteLLM proxy launcher.
"""

from __future__ import annotations

import atexit
import json
import os
import platform
import signal
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def quote(value: str) -> str:
    """Return a JSON-escaped string that is also valid YAML."""
    return json.dumps(value)


def build_user_agent(cli_version: str | None = None) -> str:
    """Return the canonical CLI user agent string for upstream requests."""
    version = cli_version or os.getenv("CLI_VERSION", "0.2.0")
    os_name = platform.system().lower()
    architecture = platform.machine()
    return f"QwenCode/{version} ({os_name}; {architecture})"


@contextmanager
def temporary_config(config_data: str | Path, is_generated: bool = True) -> Iterator[Path]:
    """Yield a config path, creating a temporary file when needed.

    Args:
        config_data: Configuration text (when generated) or an existing file path.
        is_generated: Whether the config_data was freshly generated and needs persistence.
    """
    if not is_generated:
        yield Path(config_data)
        return

    if not isinstance(config_data, str):
        raise TypeError("Generated configuration data must be a string.")

    config_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="litellm-config-", delete=False
    )
    try:
        with config_file as handle:
            handle.write(config_data)
            handle.flush()
            path = Path(handle.name)
        yield path
    finally:
        try:
            Path(config_file.name).unlink(missing_ok=True)
        except Exception:
            pass


def attach_signal_handlers() -> None:
    """Attach signal handlers for graceful shutdown."""

    def handle_signal(signum, frame):  # pragma: no cover - runtime behaviour
        signame = signal.Signals(signum).name
        print(f"\nReceived {signame}, shutting down LiteLLM proxy...", file=sys.stderr)
        raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, handle_signal)


def register_node_proxy_cleanup() -> None:
    """Register cleanup handler to terminate the Node helper subprocess."""
    node_pid = os.getenv("NODE_UPSTREAM_PROXY_PID")
    if not node_pid:
        return

    try:
        parsed_pid = int(node_pid)
    except ValueError:
        return

    def cleanup() -> None:
        try:
            os.kill(parsed_pid, signal.SIGTERM)
        except OSError:
            pass

    atexit.register(cleanup)


@contextmanager
def create_temp_config_if_needed(config_data: str | Path, is_generated: bool) -> Iterator[Path]:
    """Return a context manager that yields a config path, creating one when required."""
    with temporary_config(config_data, is_generated) as path:
        yield path


def validate_prereqs() -> None:
    """Validate that required dependencies are available."""
    if env_bool("SKIP_PREREQ_CHECK", False):
        return
    try:
        import litellm  # noqa: F401
        import litellm.proxy.proxy_cli  # noqa: F401
    except ImportError as exc:  # pragma: no cover - import error reported to user
        print(
            "ERROR: LiteLLM proxy dependencies are missing. "
            "Install them with `pip install 'litellm[proxy]'`.",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc

    # Only check for Node.js if we need to start it as a subprocess
    # Skip check if using external Node proxy service (docker-compose mode)
    if env_bool("NODE_UPSTREAM_PROXY_ENABLE", True):
        # Check if we're in docker-compose mode with external node-proxy service
        import socket
        try:
            socket.gethostbyname('node-proxy')
            # External Node proxy service is available, skip Node.js runtime check
            return
        except socket.gaierror:
            # No external service, we need Node.js runtime for subprocess
            pass

        if shutil.which("node") is None:
            print(
                "ERROR: Node.js runtime is required for the Node upstream proxy but not found.",
                file=sys.stderr,
            )
            raise SystemExit(2)

        try:
            subprocess.run(
                ["node", "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except subprocess.SubprocessError as exc:
            print(
                "ERROR: Failed to verify Node.js runtime availability.",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
