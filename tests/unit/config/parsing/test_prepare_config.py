#!/usr/bin/env python3
"""Unit tests for prepare_config function."""

from __future__ import annotations
from src.utils import create_temp_config_if_needed

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from src.config.models import ModelSpec
from src.admin.config_store import ConfigStore, get_config_store, set_config_store
from src.config.parsing import auto_migrate_from_env_if_db_empty, prepare_config


@pytest.fixture(autouse=True)
def clear_model_env(monkeypatch):
    """Ensure MODEL_* variables from other tests don't leak into these cases."""
    for key in list(os.environ.keys()):
        if key.startswith("MODEL_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("PROXY_MODEL_KEYS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEYS", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEYS", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CONFIG_BACKEND", "env")


def make_spec(
    *,
    key: str,
    alias: str,
    upstream_model: str,
    reasoning_effort: str | None = None,
    upstream_base: str | None = None,
) -> ModelSpec:
    """Helper to create a ModelSpec with defaults."""
    return ModelSpec(
        key=key,
        alias=alias,
        upstream_model=upstream_model,
        upstream_base=upstream_base,
        reasoning_effort=reasoning_effort,
    )


class TestPrepareConfig:
    """Tests for prepare_config."""

    def test_prepare_config_uses_cli_specs(self, monkeypatch):
        """CLI-provided model specs should be rendered into config."""
        args = SimpleNamespace(
            config=None,
            model_specs=[
                make_spec(
                    key="model1",
                    alias="model-one",
                    upstream_model="gpt-5",
                    reasoning_effort="high",
                )
            ],
            upstream_base=None,
            master_key="sk-cli",
            no_master_key=False,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=True,
            print_config=False,
        )

        with patch.dict(os.environ, {}, clear=True):
            config_text, is_generated = prepare_config(args)

        assert is_generated is True
        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["model_name"] == "model-one"
        assert parsed["model_list"][0]["litellm_params"]["reasoning_effort"] == "high"
        assert parsed["general_settings"]["master_key"] == "sk-cli"
        assert args.model_specs

    def test_prepare_config_from_env(self, monkeypatch):
        """When CLI specs missing, environment should be used."""
        monkeypatch.setenv("MODEL_PRIMARY_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=False,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        assert is_generated is True
        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["model_name"] == "gpt-5"

    def test_prepare_config_node_proxy_overrides_upstream_base(self):
        """Node proxy enablement should force LiteLLM api_base to the local proxy."""
        spec = make_spec(
            key="node-test",
            alias="node-model",
            upstream_model="gpt-5",
        )

        args = SimpleNamespace(
            config=None,
            model_specs=[spec],
            upstream_base=None,  # No custom upstream_base, so node proxy will be used
            master_key="sk-node",
            no_master_key=False,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=True,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["litellm_params"]["api_base"] == "http://127.0.0.1:4000/v1"

    def test_prepare_config_anthropic_gets_node_proxy_base(self, monkeypatch):
        """Anthropic models should get node_proxy_base (without /v1) when node proxy enabled."""
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=True,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        parsed = yaml.safe_load(config_text)
        claude_entry = parsed["model_list"][0]
        assert claude_entry["litellm_params"]["api_base"] == "http://127.0.0.1:4000"

    def test_prepare_config_no_node_proxy_base_when_disabled(self, monkeypatch):
        """Anthropic models should NOT get node_proxy_base when node proxy disabled."""
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        parsed = yaml.safe_load(config_text)
        claude_entry = parsed["model_list"][0]
        assert "api_base" not in claude_entry["litellm_params"]

    def test_prepare_config_missing_env_errors(self, monkeypatch):
        """Missing environment configuration should exit with error."""
        for key in list(os.environ.keys()):
            if key.startswith("MODEL_"):
                monkeypatch.delenv(key, raising=False)
        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=True,
            print_config=False,
        )

        with pytest.raises(SystemExit):
            prepare_config(args)

    def test_prepare_config_db_backend_allows_empty_models(self, monkeypatch):
        """DB backend can render an empty config so Admin UI can add models."""
        monkeypatch.setenv("CONFIG_BACKEND", "db")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key="sk-test",
            no_master_key=False,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        with patch("src.config.parsing.load_model_specs_from_db", return_value=[]):
            config_text, is_generated = prepare_config(args)

        parsed = yaml.safe_load(config_text)
        assert is_generated is True
        assert parsed["model_list"] == []
        assert parsed["general_settings"]["master_key"] == "sk-test"

    def test_prepare_config_db_backend_prefers_master_key_from_sqlite(self, monkeypatch):
        """DB-backed runtime should prefer LITELLM_MASTER_KEY stored in settings."""
        monkeypatch.setenv("CONFIG_BACKEND", "db")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-env-master")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=False,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        mock_store = type("Store", (), {
            "get_setting": lambda self, key: "sk-db-master" if key == "LITELLM_MASTER_KEY" else None,
            "get_all_provider_keys": lambda self: {},
        })()

        with patch("src.config.parsing.load_model_specs_from_db", return_value=[]), \
                patch("src.config.parsing._get_config_store", return_value=mock_store):
            config_text, is_generated = prepare_config(args)

        parsed = yaml.safe_load(config_text)
        assert is_generated is True
        assert parsed["general_settings"]["master_key"] == "sk-db-master"

    def test_auto_migrate_backfills_master_key_when_models_exist(self, monkeypatch):
        """Existing DB data should still receive missing admin-managed settings."""
        old_store = get_config_store()
        store = ConfigStore(":memory:")
        store.save_model(key="GPT5", upstream_model="gpt-5", provider="openai")
        set_config_store(store)
        monkeypatch.setenv("CONFIG_BACKEND", "db")
        monkeypatch.setenv("SKIP_DOTENV", "1")
        monkeypatch.delenv("ADMIN_USERNAME", raising=False)
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-env-master")

        try:
            summary = auto_migrate_from_env_if_db_empty()
        finally:
            set_config_store(old_store)

        assert summary == {"models": 0, "keys": 0, "settings": 1}
        assert store.get_setting("LITELLM_MASTER_KEY") == "sk-env-master"

    def test_prepare_config_returns_path_for_existing_config(self, tmp_path):
        """Existing config file should be returned as a path with is_generated False."""
        config_path = tmp_path / "litellm-config.yaml"
        config_content = "model_list:\n  - model_name: external\n"
        config_path.write_text(config_content)

        args = SimpleNamespace(
            config=config_path,
            model_specs=None,
            upstream_base=None,
            master_key="unused",
            no_master_key=False,
            drop_params=True,
            streaming=True,
            print_config=False,
        )

        config_data, is_generated = prepare_config(args)
        assert is_generated is False
        assert config_data == config_path

        with create_temp_config_if_needed(config_data, is_generated) as resolved_path:
            assert resolved_path == config_path

    def test_prepare_config_anthropic_keys_passed(self, monkeypatch):
        """Anthropic keys from env should be passed via provider_api_keys."""
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        assert is_generated is True
        parsed = yaml.safe_load(config_text)
        claude_entry = parsed["model_list"][0]
        assert claude_entry["litellm_params"]["model"] == "anthropic/claude-sonnet-4-20250514"
        assert claude_entry["litellm_params"]["api_key"] == "sk-ant-test"

    def test_prepare_config_mixed_providers_keys(self, monkeypatch):
        """Both OpenAI and Anthropic keys should be passed to their respective models."""
        monkeypatch.setenv("MODEL_GPT5_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base=None,
            master_key="sk-test",
            no_master_key=False,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=False,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        parsed = yaml.safe_load(config_text)
        entries = parsed["model_list"]

        claude_entry = next(e for e in entries if "anthropic/" in e["litellm_params"]["model"])
        gpt_entry = next(e for e in entries if "openai/" in e["litellm_params"]["model"])

        assert claude_entry["litellm_params"]["api_key"] == "sk-ant"
        assert gpt_entry["litellm_params"]["api_key"] == "sk-oai"

    def test_prepare_config_custom_upstream_base(self, monkeypatch):
        """Custom upstream_base from CLI should override node proxy."""
        monkeypatch.setenv("MODEL_GPT5_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-custom")

        args = SimpleNamespace(
            config=None,
            model_specs=[],
            upstream_base="https://custom.api.example.com/v1",
            master_key=None,
            no_master_key=True,
            drop_params=True,
            streaming=True,
            node_upstream_proxy_enabled=True,
            print_config=False,
        )

        config_text, is_generated = prepare_config(args)
        assert is_generated is True
        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["litellm_params"]["api_base"] == "https://custom.api.example.com/v1"

    def test_prepare_config_missing_config_file(self):
        """Test error when config file doesn't exist."""
        from unittest.mock import MagicMock
        mock_args = MagicMock()
        mock_args.config = "nonexistent.yaml"

        with pytest.raises(FileNotFoundError, match="Config file not found: nonexistent.yaml"):
            prepare_config(mock_args)


class TestTemporaryConfig:
    """Tests for temporary config helper."""

    def test_create_temp_config_if_needed(self, tmp_path):
        """Generated config should be written to a temporary file."""
        config_text = "model_list:\n  - model_name: test\n"

        with create_temp_config_if_needed(config_text, True) as path:
            assert path.exists()
            assert path.read_text() == config_text

        assert not path.exists()

    def test_create_temp_config_with_existing_path(self):
        """Test when config_data is an existing path (not generated)."""
        from src.utils import temporary_config as create_temp_config_if_needed
        from unittest.mock import patch, MagicMock

        with patch('builtins.open', create=True) as mock_open:
            mock_file = MagicMock()
            mock_file.__enter__.return_value = mock_file
            mock_file.__exit__.return_value = None
            mock_open.return_value = mock_file

            existing_path = Path("/tmp/test_config.yaml")

            with create_temp_config_if_needed(existing_path, False) as config_path:
                assert config_path == existing_path
                mock_open.assert_not_called()
