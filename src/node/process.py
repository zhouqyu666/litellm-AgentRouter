#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from ..config.config import runtime_config
from ..utils import build_user_agent


def _load_dotenv_value(key: str, default: str | None = None) -> str | None:
    """Load a value from .env file, bypassing system environment variables.

    This is needed because runtime_config respects system env vars,
    but for Node proxy we want .env values to take precedence.
    """
    # Find .env file
    script_dir = Path(__file__).resolve().parents[2]
    cwd = Path.cwd()

    for env_path in (script_dir / ".env", cwd / ".env"):
        if not env_path.is_file():
            continue
        try:
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip().strip("'\"")
        except Exception:
            pass

    return default


class NodeProxyProcess:
    """Manage the Node upstream proxy subprocess."""

    def __init__(self, node_script: Path | None = None):
        runtime_config.ensure_loaded()
        self._script_path = node_script or self._resolve_node_script()
        self._process: subprocess.Popen | None = None

    @staticmethod
    def _resolve_node_script() -> Path:
        base_dir = Path(__file__).resolve().parents[2]
        script = base_dir / "node" / "main.mjs"
        if not script.is_file():
            raise FileNotFoundError(f"Node upstream proxy script not found: {script}")
        return script

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()

        # Load from .env file (bypassing system env vars) for Node proxy config
        openai_base = _load_dotenv_value("OPENAI_BASE_URL")
        if openai_base:
            env["OPENAI_BASE_URL"] = openai_base
        else:
            env.setdefault("OPENAI_BASE_URL", "https://agentrouter.org/v1")

        # Handle OpenAI API keys
        openai_keys = _load_dotenv_value("OPENAI_API_KEYS")
        openai_key = _load_dotenv_value("OPENAI_API_KEY")
        if openai_keys:
            first_key = openai_keys.split(",")[0].strip()
            env["OPENAI_API_KEY"] = first_key
        elif openai_key:
            env["OPENAI_API_KEY"] = openai_key

        # Handle Anthropic API keys
        anthropic_keys = _load_dotenv_value("ANTHROPIC_API_KEYS")
        anthropic_key = _load_dotenv_value("ANTHROPIC_API_KEY")
        if anthropic_keys:
            first_key = anthropic_keys.split(",")[0].strip()
            env["ANTHROPIC_API_KEY"] = first_key
        elif anthropic_key:
            env["ANTHROPIC_API_KEY"] = anthropic_key
        # Fallback to OpenAI key if no Anthropic key (unified proxy)
        elif not env.get("ANTHROPIC_API_KEY"):
            fallback = openai_keys.split(",")[0].strip() if openai_keys else openai_key
            if fallback:
                env["ANTHROPIC_API_KEY"] = fallback

        # Anthropic base URL - load from .env, override system env
        anthropic_base = _load_dotenv_value("ANTHROPIC_BASE_URL")
        if anthropic_base:
            env["ANTHROPIC_BASE_URL"] = anthropic_base

        env["NODE_USER_AGENT"] = build_user_agent()
        return env

    def start(self) -> subprocess.Popen:
        """Spawn the Node helper subprocess."""
        if self._process and self._process.poll() is None:
            return self._process

        if "OPENAI_API_KEY" not in os.environ and not runtime_config.get_str("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required to start the Node upstream proxy")

        env = self._build_env()
        try:
            self._process = subprocess.Popen(
                ["node", str(self._script_path)],
                env=env,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Node.js runtime is not available in PATH") from exc

        return self._process

    def stop(self) -> None:
        """Terminate the Node helper subprocess if it is running."""
        if not self._process:
            return

        if self._process.poll() is not None:
            self._process = None
            return

        self._process.terminate()
        try:
            self._process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()
        finally:
            self._process = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None
