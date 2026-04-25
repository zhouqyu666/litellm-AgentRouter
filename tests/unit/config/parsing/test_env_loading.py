#!/usr/bin/env python3
"""Unit tests for environment-based model spec loading."""

from __future__ import annotations

import os

import pytest

from src.config import parsing as parsing_module
from src.config.parsing import load_model_specs_from_env, load_model_specs_from_cli


@pytest.fixture(autouse=True)
def clear_model_env(monkeypatch):
    """Ensure each test starts without lingering MODEL_* variables."""
    for key in list(os.environ.keys()):
        if key.startswith("MODEL_"):
            monkeypatch.delenv(key, raising=False)


class TestLoadModelSpecsFromEnv:
    """Tests for environment-driven spec loading."""

    def test_load_model_specs_from_env_success(self, monkeypatch):
        """Load two models from environment variables."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://agentrouter.org/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        monkeypatch.setenv("MODEL_DEEPSEEK_UPSTREAM_MODEL", "deepseek-v3.2")
        monkeypatch.setenv("MODEL_DEEPSEEK_REASONING_EFFORT", "medium")
        monkeypatch.setenv("MODEL_GPT5_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("MODEL_GPT5_REASONING_EFFORT", "medium")

        specs = load_model_specs_from_env()
        assert [spec.alias for spec in specs] == ["deepseek-v3.2", "gpt-5"]
        assert specs[0].reasoning_effort == "medium"
        assert specs[1].reasoning_effort == "medium"

    def test_load_model_specs_from_env_missing_models(self, monkeypatch):
        """Missing MODEL_* variables should raise ValueError."""
        with pytest.raises(ValueError):
            load_model_specs_from_env()

    def test_legacy_alias_env_var_raises(self, monkeypatch):
        """Legacy MODEL_XXX_ALIAS variables should raise a helpful error."""
        monkeypatch.setenv("MODEL_TEST_ALIAS", "legacy-alias")
        monkeypatch.setenv("MODEL_TEST_UPSTREAM_MODEL", "gpt-5")

        with pytest.raises(
            ValueError,
            match="Legacy environment variable 'MODEL_TEST_ALIAS' detected",
        ):
            load_model_specs_from_env()

    def test_missing_upstream_model_env_var(self, monkeypatch):
        """Test error when MODEL_XXX_UPSTREAM_MODEL is missing."""
        monkeypatch.setenv("MODEL_TEST_UPSTREAM_MODEL", "")
        with pytest.raises(ValueError, match="Missing environment variable: MODEL_TEST_UPSTREAM_MODEL"):
            load_model_specs_from_env()

    def test_grok_config_from_environment(self, monkeypatch):
        """Verify Grok can be configured via environment variables."""
        monkeypatch.setenv("MODEL_GROK_UPSTREAM_MODEL", "grok-code-fast-1")
        monkeypatch.setenv("MODEL_GROK_REASONING_EFFORT", "high")
        monkeypatch.setenv("XAI_API_KEY", "sk-xai-test")

        specs = load_model_specs_from_env()
        assert len(specs) == 1
        assert specs[0].alias == "grok-code-fast-1"
        assert specs[0].upstream_model == "grok-code-fast-1"
        assert specs[0].reasoning_effort == "high"

    def test_glm_config_from_environment(self, monkeypatch):
        """Verify GLM can be configured via environment variables."""
        monkeypatch.setenv("MODEL_GLM_UPSTREAM_MODEL", "glm-4.6")
        monkeypatch.setenv("MODEL_GLM_REASONING_EFFORT", "none")
        monkeypatch.setenv("GLM_API_KEY", "sk-glm-test")

        specs = load_model_specs_from_env()
        assert len(specs) == 1
        assert specs[0].alias == "glm-4.6"
        assert specs[0].upstream_model == "glm-4.6"
        assert specs[0].reasoning_effort == "none"

    def test_proxy_model_keys_warning(self, monkeypatch, capsys):
        """PROXY_MODEL_KEYS should be ignored but emit a warning."""
        parsing_module._proxy_warning_emitted = False
        monkeypatch.setenv("PROXY_MODEL_KEYS", "legacy")
        monkeypatch.setenv("MODEL_PRIMARY_UPSTREAM_MODEL", "gpt-5")

        specs = load_model_specs_from_env()
        assert len(specs) == 1

        captured = capsys.readouterr()
        assert "PROXY_MODEL_KEYS is ignored" in captured.err

    def test_alphabetical_ordering(self, monkeypatch):
        """Discovered models should be sorted alphabetically."""
        monkeypatch.setenv("MODEL_ZETA_UPSTREAM_MODEL", "zeta")
        monkeypatch.setenv("MODEL_ALPHA_UPSTREAM_MODEL", "alpha")
        monkeypatch.setenv("MODEL_MIDDLE_UPSTREAM_MODEL", "mid")

        specs = load_model_specs_from_env()
        assert [spec.key for spec in specs] == ["alpha", "middle", "zeta"]


    def test_anthropic_model_auto_detected(self, monkeypatch):
        """Claude model should auto-detect as anthropic provider."""
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")

        specs = load_model_specs_from_env()
        assert len(specs) == 1
        assert specs[0].provider == "anthropic"
        assert specs[0].alias == "claude-sonnet-4-20250514"

    def test_explicit_provider_env_var(self, monkeypatch):
        """MODEL_<KEY>_PROVIDER should override auto-detection."""
        monkeypatch.setenv("MODEL_CUSTOM_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("MODEL_CUSTOM_PROVIDER", "anthropic")

        specs = load_model_specs_from_env()
        assert specs[0].provider == "anthropic"

    def test_per_model_api_key_env_var(self, monkeypatch):
        """MODEL_<KEY>_API_KEY should be stored on the spec."""
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")
        monkeypatch.setenv("MODEL_CLAUDE_API_KEY", "sk-ant-per-model")

        specs = load_model_specs_from_env()
        assert specs[0].api_key == "sk-ant-per-model"

    def test_mixed_openai_and_anthropic(self, monkeypatch):
        """Mixed OpenAI and Anthropic models from environment."""
        monkeypatch.setenv("MODEL_GPT5_UPSTREAM_MODEL", "gpt-5")
        monkeypatch.setenv("MODEL_CLAUDE_UPSTREAM_MODEL", "claude-sonnet-4-20250514")

        specs = load_model_specs_from_env()
        assert len(specs) == 2
        claude_spec = next(s for s in specs if s.key == "claude")
        gpt_spec = next(s for s in specs if s.key == "gpt5")
        assert claude_spec.provider == "anthropic"
        assert gpt_spec.provider == "openai"


class TestLoadModelSpecsFromCli:
    """Tests for CLI-based model spec loading."""

    def test_load_model_specs_empty_args(self):
        """Test load_model_specs_from_cli with no arguments."""
        result = load_model_specs_from_cli(None)
        assert result == []
        result2 = load_model_specs_from_cli([])
        assert result2 == []
