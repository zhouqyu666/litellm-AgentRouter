#!/usr/bin/env python3
"""Unit tests for render_config function."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from src.config.models import ModelSpec
from src.config.rendering import parse_api_keys, render_config


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


class TestParseApiKeys:
    """Tests for parse_api_keys helper."""

    def test_parse_single_key(self):
        assert parse_api_keys("sk-abc") == ["sk-abc"]

    def test_parse_multiple_keys(self):
        result = parse_api_keys("sk-a,sk-b,sk-c")
        assert result == ["sk-a", "sk-b", "sk-c"]

    def test_parse_strips_whitespace(self):
        result = parse_api_keys(" sk-a , sk-b , sk-c ")
        assert result == ["sk-a", "sk-b", "sk-c"]

    def test_parse_empty_string(self):
        assert parse_api_keys("") == []

    def test_parse_none(self):
        assert parse_api_keys(None) == []

    def test_parse_ignores_empty_segments(self):
        result = parse_api_keys("sk-a,,sk-b,")
        assert result == ["sk-a", "sk-b"]


class TestRenderConfig:
    """Tests for render_config."""

    def test_render_config_single_model(self):
        """Render config for one model and include reasoning effort."""
        spec = make_spec(
            key="gpt5",
            alias="gpt-5",
            upstream_model="gpt-5",
            reasoning_effort="medium",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key="sk-master",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["model_name"] == "gpt-5"
        assert parsed["model_list"][0]["litellm_params"]["model"] == "openai/gpt-5"
        assert parsed["model_list"][0]["litellm_params"]["reasoning_effort"] == "medium"
        assert parsed["general_settings"]["master_key"] == "sk-master"

    def test_render_config_allows_reasoning_for_deepseek(self):
        """Reasoning effort should be preserved for DeepSeek when requested."""
        spec = make_spec(
            key="deepseek",
            alias="deepseek-v3.2",
            upstream_model="deepseek-v3.2",
            reasoning_effort="medium",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=False,
        )

        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["litellm_params"]["reasoning_effort"] == "medium"

    def test_render_config_without_api_key_field(self):
        """Test rendering config does not include api_key field."""
        model_spec = ModelSpec(
            key="test",
            alias="test-model",
            upstream_model="gpt-5"
        )

        config_text = render_config(
            model_specs=[model_spec],
            global_upstream_base="https://api.openai.com",
            master_key="sk-test",
            drop_params=True,
            streaming=True
        )

        assert "api_key" not in config_text

    def test_render_config_with_reasoning_unsupported_model(self):
        """Test rendering config with reasoning effort for unsupported model."""
        with patch('src.config.models.get_model_capabilities') as mock_caps:
            mock_caps.return_value = {"supports_reasoning": False}

            model_spec = ModelSpec(
                key="test",
                alias="test-model",
                upstream_model="unsupported-model",
                reasoning_effort="high"
            )

            with patch('builtins.print') as mock_print:
                render_config(
                    model_specs=[model_spec],
                    global_upstream_base="https://api.openai.com",
                    master_key="sk-test",
                    drop_params=True,
                    streaming=True
                )

                mock_print.assert_called()
                warning_call = str(mock_print.call_args[0][0])
                assert "WARNING: Model unsupported-model does not support reasoning_effort" in warning_call
                assert "ignoring reasoning_effort=high" in warning_call

    def test_render_config_empty_model_specs(self):
        """render_config should raise ValueError for empty model specs."""
        with pytest.raises(ValueError, match="No model specifications provided"):
            render_config(
                model_specs=[],
                global_upstream_base="https://api.openai.com/v1",
                master_key="sk-test",
                drop_params=False,
                streaming=True
            )

    def test_render_config_none_model_specs(self):
        """render_config should raise ValueError for None model specs."""
        with pytest.raises(ValueError, match="No model specifications provided"):
            render_config(
                model_specs=None,
                global_upstream_base="https://api.openai.com/v1",
                master_key="sk-test",
                drop_params=False,
                streaming=True
            )

    def test_render_config_multiple_api_keys_duplicates_entries(self):
        """Each model should produce N entries when N API keys are provided."""
        spec = make_spec(key="glm", alias="glm-4.6", upstream_model="glm-4.6")
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            api_keys=["sk-a", "sk-b", "sk-c"],
        )

        parsed = yaml.safe_load(config_text)
        entries = parsed["model_list"]
        assert len(entries) == 3
        # All entries share the same model_name
        assert all(e["model_name"] == "glm-4.6" for e in entries)
        # Each entry has a distinct api_key
        keys = [e["litellm_params"]["api_key"] for e in entries]
        assert keys == ["sk-a", "sk-b", "sk-c"]
        # router_settings should enable simple-shuffle
        assert parsed["router_settings"]["routing_strategy"] == "simple-shuffle"

    def test_render_config_multiple_keys_multiple_models(self):
        """Multiple models × multiple keys should produce M×N entries."""
        specs = [
            make_spec(key="glm", alias="glm-4.6", upstream_model="glm-4.6"),
            make_spec(key="gpt5", alias="gpt-5", upstream_model="gpt-5"),
        ]
        config_text = render_config(
            model_specs=specs,
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            api_keys=["sk-1", "sk-2"],
        )

        parsed = yaml.safe_load(config_text)
        entries = parsed["model_list"]
        assert len(entries) == 4  # 2 models × 2 keys

    def test_render_config_single_api_key_backward_compat(self):
        """A single api_key should produce one entry per model (old behaviour)."""
        spec = make_spec(key="glm", alias="glm-4.6", upstream_model="glm-4.6")
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            api_key="sk-single",
        )

        parsed = yaml.safe_load(config_text)
        assert len(parsed["model_list"]) == 1
        assert parsed["model_list"][0]["litellm_params"]["api_key"] == "sk-single"
        assert "router_settings" not in parsed


class TestRenderConfigAnthropic:
    """Tests for Anthropic model rendering."""

    def test_anthropic_model_uses_anthropic_prefix(self):
        """Anthropic models should use anthropic/ prefix."""
        spec = ModelSpec(
            key="claude",
            alias="claude-sonnet",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert params["model"] == "anthropic/claude-sonnet-4-20250514"

    def test_anthropic_model_no_custom_llm_provider(self):
        """Anthropic models should NOT have custom_llm_provider."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert "custom_llm_provider" not in params

    def test_anthropic_model_no_headers(self):
        """Anthropic models should NOT have headers block."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert "headers" not in params

    def test_anthropic_model_no_global_api_base(self):
        """Anthropic models should NOT inherit global upstream_base (without node_proxy_base)."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert "api_base" not in params

    def test_anthropic_model_gets_node_proxy_base(self):
        """Anthropic models should get api_base when node_proxy_base is set."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            node_proxy_base="http://127.0.0.1:4000",
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert params["api_base"] == "http://127.0.0.1:4000"

    def test_anthropic_model_explicit_upstream_base_overrides_node_proxy(self):
        """Anthropic model with explicit upstream_base should override node_proxy_base."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
            upstream_base="https://my-anthropic-proxy.com/v1",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            node_proxy_base="http://127.0.0.1:4000",
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert params["api_base"] == "https://my-anthropic-proxy.com/v1"

    def test_anthropic_model_explicit_upstream_base(self):
        """Anthropic model with explicit upstream_base should set api_base."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
            upstream_base="https://my-anthropic-proxy.com/v1",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert params["api_base"] == "https://my-anthropic-proxy.com/v1"

    def test_anthropic_model_with_api_key(self):
        """Anthropic model should accept API key."""
        spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            provider_api_keys={"anthropic": ["sk-ant-test"]},
        )

        parsed = yaml.safe_load(config_text)
        params = parsed["model_list"][0]["litellm_params"]
        assert params["api_key"] == "sk-ant-test"

    def test_anthropic_already_prefixed_not_double_prefixed(self):
        """Model already prefixed with anthropic/ should not get double prefix."""
        spec = ModelSpec(
            key="claude",
            upstream_model="anthropic/claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["litellm_params"]["model"] == "anthropic/claude-sonnet-4-20250514"


class TestRenderConfigMixedProviders:
    """Tests for mixed OpenAI + Anthropic rendering."""

    def test_mixed_providers_both_rendered(self):
        """OpenAI and Anthropic models should each use their own rendering."""
        openai_spec = make_spec(key="gpt5", alias="gpt-5", upstream_model="gpt-5")
        anthropic_spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[openai_spec, anthropic_spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        entries = parsed["model_list"]
        assert len(entries) == 2

        gpt_entry = next(e for e in entries if e["model_name"] == "gpt-5")
        claude_entry = next(e for e in entries if e["model_name"] == "claude-sonnet-4-20250514")

        assert gpt_entry["litellm_params"]["model"] == "openai/gpt-5"
        assert "custom_llm_provider" in gpt_entry["litellm_params"]
        assert claude_entry["litellm_params"]["model"] == "anthropic/claude-sonnet-4-20250514"
        assert "custom_llm_provider" not in claude_entry["litellm_params"]

    def test_provider_api_keys_per_provider(self):
        """Each provider should get its own API keys for load balancing."""
        openai_spec = make_spec(key="gpt5", alias="gpt-5", upstream_model="gpt-5")
        anthropic_spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[openai_spec, anthropic_spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            provider_api_keys={
                "openai": ["sk-oai-1", "sk-oai-2"],
                "anthropic": ["sk-ant-1", "sk-ant-2"],
            },
        )

        parsed = yaml.safe_load(config_text)
        entries = parsed["model_list"]
        # 2 keys per provider × 1 model each = 4 total entries
        assert len(entries) == 4

        gpt_entries = [e for e in entries if e["model_name"] == "gpt-5"]
        claude_entries = [e for e in entries if e["model_name"] == "claude-sonnet-4-20250514"]

        assert len(gpt_entries) == 2
        assert len(claude_entries) == 2

        gpt_keys = [e["litellm_params"]["api_key"] for e in gpt_entries]
        claude_keys = [e["litellm_params"]["api_key"] for e in claude_entries]

        assert gpt_keys == ["sk-oai-1", "sk-oai-2"]
        assert claude_keys == ["sk-ant-1", "sk-ant-2"]

        # Should have router_settings for multi-key
        assert parsed["router_settings"]["routing_strategy"] == "simple-shuffle"

    def test_provider_api_keys_single_no_router(self):
        """Single key per provider should NOT trigger router_settings."""
        openai_spec = make_spec(key="gpt5", alias="gpt-5", upstream_model="gpt-5")
        anthropic_spec = ModelSpec(
            key="claude",
            upstream_model="claude-sonnet-4-20250514",
        )
        config_text = render_config(
            model_specs=[openai_spec, anthropic_spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key=None,
            drop_params=True,
            streaming=True,
            provider_api_keys={
                "openai": ["sk-oai-only"],
                "anthropic": ["sk-ant-only"],
            },
        )

        parsed = yaml.safe_load(config_text)
        assert len(parsed["model_list"]) == 2
        assert "router_settings" not in parsed
