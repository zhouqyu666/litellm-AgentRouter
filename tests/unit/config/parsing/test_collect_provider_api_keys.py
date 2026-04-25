#!/usr/bin/env python3
"""Unit tests for _collect_provider_api_keys function."""

from __future__ import annotations

from src.config.parsing import _collect_provider_api_keys


class TestCollectProviderApiKeys:
    """Tests for _collect_provider_api_keys."""

    def test_empty_env(self):
        """No keys in environment returns empty dict."""
        result = _collect_provider_api_keys(env={})
        assert result == {}

    # --- OpenAI keys ---

    def test_openai_single_key(self):
        """OpenAI single key; Anthropic inherits via fallback."""
        result = _collect_provider_api_keys(env={"OPENAI_API_KEY": "sk-abc"})
        assert result == {"openai": ["sk-abc"], "anthropic": ["sk-abc"]}

    def test_openai_single_key_with_commas(self):
        """Comma-separated value in OPENAI_API_KEY should auto-split; Anthropic inherits."""
        result = _collect_provider_api_keys(env={"OPENAI_API_KEY": "sk-a,sk-b"})
        assert result == {"openai": ["sk-a", "sk-b"], "anthropic": ["sk-a", "sk-b"]}

    def test_openai_multi_keys_var(self):
        """OPENAI_API_KEYS takes priority over OPENAI_API_KEY; Anthropic inherits."""
        result = _collect_provider_api_keys(env={
            "OPENAI_API_KEYS": "sk-x,sk-y",
            "OPENAI_API_KEY": "sk-ignored",
        })
        assert result == {"openai": ["sk-x", "sk-y"], "anthropic": ["sk-x", "sk-y"]}

    def test_openai_empty_key_ignored(self):
        result = _collect_provider_api_keys(env={"OPENAI_API_KEY": ""})
        assert result == {}

    def test_openai_whitespace_key_ignored(self):
        result = _collect_provider_api_keys(env={"OPENAI_API_KEY": "  "})
        assert result == {}

    def test_openai_key_falls_back_to_anthropic(self):
        """When only OPENAI_API_KEY is set, Anthropic should inherit it."""
        result = _collect_provider_api_keys(env={"OPENAI_API_KEY": "sk-shared"})
        assert result == {
            "openai": ["sk-shared"],
            "anthropic": ["sk-shared"],
        }

    def test_openai_multi_keys_fall_back_to_anthropic(self):
        """When only OPENAI_API_KEYS is set, Anthropic should inherit all."""
        result = _collect_provider_api_keys(env={"OPENAI_API_KEYS": "sk-a,sk-b"})
        assert result == {
            "openai": ["sk-a", "sk-b"],
            "anthropic": ["sk-a", "sk-b"],
        }

    # --- Anthropic keys ---

    def test_anthropic_single_key(self):
        result = _collect_provider_api_keys(env={"ANTHROPIC_API_KEY": "sk-ant-abc"})
        assert result == {"anthropic": ["sk-ant-abc"]}

    def test_anthropic_single_key_with_commas(self):
        result = _collect_provider_api_keys(env={"ANTHROPIC_API_KEY": "sk-ant-a,sk-ant-b"})
        assert result == {"anthropic": ["sk-ant-a", "sk-ant-b"]}

    def test_anthropic_multi_keys_var(self):
        """ANTHROPIC_API_KEYS takes priority over ANTHROPIC_API_KEY."""
        result = _collect_provider_api_keys(env={
            "ANTHROPIC_API_KEYS": "sk-ant-x,sk-ant-y",
            "ANTHROPIC_API_KEY": "sk-ant-ignored",
        })
        assert result == {"anthropic": ["sk-ant-x", "sk-ant-y"]}

    def test_anthropic_empty_key_ignored(self):
        """Empty ANTHROPIC_API_KEY with no OpenAI key means no keys at all."""
        result = _collect_provider_api_keys(env={"ANTHROPIC_API_KEY": ""})
        assert result == {}

    def test_anthropic_explicit_overrides_fallback(self):
        """Explicit ANTHROPIC_API_KEY is used, not the OpenAI fallback."""
        result = _collect_provider_api_keys(env={
            "OPENAI_API_KEY": "sk-oai",
            "ANTHROPIC_API_KEY": "sk-ant-explicit",
        })
        assert result["anthropic"] == ["sk-ant-explicit"]

    # --- Mixed providers ---

    def test_both_providers(self):
        result = _collect_provider_api_keys(env={
            "OPENAI_API_KEY": "sk-oai",
            "ANTHROPIC_API_KEY": "sk-ant",
        })
        assert result == {
            "openai": ["sk-oai"],
            "anthropic": ["sk-ant"],
        }

    def test_both_providers_multi_keys(self):
        result = _collect_provider_api_keys(env={
            "OPENAI_API_KEYS": "sk-1,sk-2",
            "ANTHROPIC_API_KEYS": "sk-ant-1,sk-ant-2,sk-ant-3",
        })
        assert result == {
            "openai": ["sk-1", "sk-2"],
            "anthropic": ["sk-ant-1", "sk-ant-2", "sk-ant-3"],
        }

    def test_only_anthropic_no_openai(self):
        """If only Anthropic keys are present, result should only have anthropic."""
        result = _collect_provider_api_keys(env={"ANTHROPIC_API_KEY": "sk-ant-only"})
        assert "openai" not in result
        assert result == {"anthropic": ["sk-ant-only"]}
