#!/usr/bin/env python3
"""Unit tests for the container entrypoint flow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _get_repo_root() -> Path:
    """Locate the repository root relative to the tests directory."""
    for parent in Path(__file__).resolve().parents:
        if parent.name == "tests":
            return parent.parent
    raise RuntimeError("Unable to locate repository root from tests directory.")


REPO_ROOT = _get_repo_root()


def _base_env(app_dir: Path) -> dict[str, str]:
    """Return a baseline environment for invoking the Python entrypoint."""
    env = os.environ.copy()
    for key in list(env.keys()):
        if key.startswith("MODEL_"):
            env.pop(key)
    env.pop("PROXY_MODEL_KEYS", None)
    env.update(
        {
            "ENTRYPOINT_TEST_MODE": "1",
            "GENERATED_CONFIG_PATH": str(app_dir / "generated-config.yaml"),
            "SKIP_DOTENV": "1",
        }
    )
    return env


def _run_entrypoint(env: dict[str, str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", "-m", "src.config.entrypoint"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_generates_config_with_reasoning_effort(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "gpt-5",
            "MODEL_PRIMARY_REASONING_EFFORT": "high",
            "OPENAI_API_KEY": "sk-test-123",
            "LITELLM_MASTER_KEY": "sk-test-master",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code == 0, f"entrypoint failed: {out}\n{err}"

    generated = Path(env["GENERATED_CONFIG_PATH"])
    assert generated.exists()
    config_text = generated.read_text()
    assert 'model_name: "gpt-5"' in config_text
    assert 'reasoning_effort: "high"' in config_text
    assert 'master_key: "sk-test-master"' in config_text
    assert "ENTRYPOINT_TEST_MODE enabled" in out


def test_env_overrides_host_port_and_master_key(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "gpt-5",
            "OPENAI_API_KEY": "sk-test-abc",
            "PORT": "8088",
            "LITELLM_HOST": "127.0.0.1",
            "LITELLM_MASTER_KEY": "sk-local-override",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code == 0, f"entrypoint failed: {out}\n{err}"

    config_text = Path(env["GENERATED_CONFIG_PATH"]).read_text()
    assert 'master_key: "sk-local-override"' in config_text
    assert "Container listening on port 4000; host publishes 8088 -> 4000" in out
    assert "Starting LiteLLM proxy on 127.0.0.1:4000" in out


def test_fails_when_legacy_alias_present(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_GPT5_ALIAS": "gpt-5",
            "MODEL_GPT5_UPSTREAM_MODEL": "gpt-5",
            "OPENAI_API_KEY": "sk-test-xyz",
            "LITELLM_MASTER_KEY": "sk-test-master",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code != 0
    combined = out + err
    assert "Legacy environment variable 'MODEL_GPT5_ALIAS' detected" in combined


def test_missing_required_vars(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    # Missing master key should fall back to default
    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "gpt-5",
            "OPENAI_API_KEY": "sk-test-123",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code == 0, f"entrypoint failed: {out}\n{err}"
    config_text = Path(env["GENERATED_CONFIG_PATH"]).read_text()
    assert 'master_key: "sk-local-master"' in config_text

    # Missing model configuration entirely
    env = _base_env(app_dir)
    env.update(
        {
            "LITELLM_MASTER_KEY": "sk-test-master",
            "OPENAI_API_KEY": "sk-test-123",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code != 0
    assert "MODEL_<KEY>_UPSTREAM_MODEL" in (out + err)


def test_concurrent_env_var_handling(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "gpt-5",
            "MODEL_PRIMARY_REASONING_EFFORT": "medium",
            "MODEL_SECONDARY_UPSTREAM_MODEL": "claude-3",
            "MODEL_SECONDARY_REASONING_EFFORT": "high",
            "OPENAI_API_KEY": "sk-test-123",
            "LITELLM_MASTER_KEY": "sk-test-master",
            "LITELLM_HOST": "127.0.0.1",
            "PORT": "3000",
            "DROP_PARAMS": "true",
            "STREAMING": "false",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code == 0, f"entrypoint failed: {out}\n{err}"

    config_text = Path(env["GENERATED_CONFIG_PATH"]).read_text()
    assert 'model_name: "claude-3"' in config_text
    assert 'reasoning_effort: "high"' in config_text
    assert 'model_name: "gpt-5"' in config_text
    assert 'drop_params: true' in config_text


def test_config_generation_with_special_characters(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "gpt-5-turbo",
            "MODEL_PRIMARY_REASONING_EFFORT": "high",
            "OPENAI_API_KEY": "sk-test-special!@#$%",
            "LITELLM_MASTER_KEY": "sk-master-2024",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code == 0, f"entrypoint failed: {out}\n{err}"

    config_text = Path(env["GENERATED_CONFIG_PATH"]).read_text()
    assert 'model_name: "gpt-5-turbo"' in config_text
    assert 'api_key: "sk-test-special!@#$%"' in config_text


def test_script_error_handling(tmp_path: Path):
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    env = _base_env(app_dir)
    env.update(
        {
            "MODEL_PRIMARY_UPSTREAM_MODEL": "",
            "OPENAI_API_KEY": "sk-test-123",
            "LITELLM_MASTER_KEY": "sk-test-master",
        }
    )

    code, out, err = _run_entrypoint(env)
    assert code != 0
    assert "MODEL_PRIMARY_UPSTREAM_MODEL" in (out + err)
