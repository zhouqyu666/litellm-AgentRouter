#!/usr/bin/env python3
"""Unit tests for model capabilities and MODEL_CAPS registry."""

from __future__ import annotations

import yaml

from src.config.models import MODEL_CAPS, get_model_capabilities, ModelSpec
from src.config.rendering import render_config


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


class TestModelCapabilities:
    """Test model capabilities lookup."""

    def test_get_model_capabilities_known_model(self):
        """Test capabilities lookup for known models."""
        caps = get_model_capabilities("gpt-5")
        assert "supports_reasoning" in caps
        assert isinstance(caps["supports_reasoning"], bool)

    def test_get_model_capabilities_unknown_model(self):
        """Test capabilities lookup for unknown models returns defaults."""
        caps = get_model_capabilities("unknown-model-xyz")
        # Unknown models default to supporting reasoning
        assert caps["supports_reasoning"] is True


class TestGrokCodeFast1Integration:
    """Tests for Grok Code Fast-1 model integration."""

    def test_grok_code_fast_1_in_model_caps(self):
        """Verify grok-code-fast-1 is present in MODEL_CAPS."""
        assert "grok-code-fast-1" in MODEL_CAPS

    def test_grok_code_fast_1_supports_reasoning(self):
        """Verify grok-code-fast-1 supports reasoning capability."""
        caps = get_model_capabilities("grok-code-fast-1")
        assert caps["supports_reasoning"] is True

    def test_render_config_with_grok_code_fast_1(self):
        """Verify config rendering works correctly for grok-code-fast-1."""
        spec = make_spec(
            key="grok",
            alias="grok-code-fast-1",
            upstream_model="grok-code-fast-1",
            reasoning_effort="medium",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://api.x.ai/v1",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["model_name"] == "grok-code-fast-1"
        assert parsed["model_list"][0]["litellm_params"]["model"] == "openai/grok-code-fast-1"
        assert parsed["model_list"][0]["litellm_params"]["reasoning_effort"] == "medium"


class TestGLM46Integration:
    """Tests for GLM-4.6 model integration."""

    def test_glm_4_6_in_model_caps(self):
        """Verify glm-4.6 is present in MODEL_CAPS."""
        assert "glm-4.6" in MODEL_CAPS

    def test_glm_4_6_does_not_support_reasoning(self):
        """Verify glm-4.6 reasoning capability is correctly False."""
        caps = get_model_capabilities("glm-4.6")
        assert caps["supports_reasoning"] is False

    def test_render_config_with_glm_4_6(self):
        """Verify config rendering works correctly for glm-4.6."""
        spec = make_spec(
            key="glm",
            alias="glm-4.6",
            upstream_model="glm-4.6",
            reasoning_effort=None,
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://open.bigmodel.cn/api/paas/v4",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert parsed["model_list"][0]["model_name"] == "glm-4.6"
        assert parsed["model_list"][0]["litellm_params"]["model"] == "openai/glm-4.6"
        assert "reasoning_effort" not in parsed["model_list"][0]["litellm_params"]

    def test_glm_reasoning_effort_filtered_in_config(self):
        """Verify that reasoning_effort is filtered out for GLM-4.6 even if specified."""
        spec = make_spec(
            key="glm",
            alias="glm-4.6",
            upstream_model="glm-4.6",
            reasoning_effort="high",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://open.bigmodel.cn/api/paas/v4",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert "reasoning_effort" not in parsed["model_list"][0]["litellm_params"]


class TestAnthropicModels:
    """Tests for Anthropic model capabilities."""

    def test_claude_sonnet_in_model_caps(self):
        assert "claude-sonnet-4-20250514" in MODEL_CAPS

    def test_claude_opus_in_model_caps(self):
        assert "claude-opus-4-20250514" in MODEL_CAPS

    def test_claude_haiku_in_model_caps(self):
        assert "claude-haiku-4-20250514" in MODEL_CAPS

    def test_claude_does_not_support_reasoning(self):
        """Anthropic extended thinking is not controlled via reasoning_effort."""
        for model in ("claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-20250514"):
            caps = get_model_capabilities(model)
            assert caps["supports_reasoning"] is False, f"{model} should not support reasoning"

    def test_render_config_with_claude_sonnet(self):
        """Anthropic model should use anthropic/ prefix, no custom_llm_provider."""
        spec = make_spec(
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
        assert "custom_llm_provider" not in params
        assert "headers" not in params
        # Anthropic should NOT use the global upstream_base
        assert "api_base" not in params

    def test_claude_reasoning_effort_filtered(self):
        """reasoning_effort should be ignored for Claude models."""
        spec = make_spec(
            key="claude",
            alias="claude-sonnet",
            upstream_model="claude-sonnet-4-20250514",
            reasoning_effort="high",
        )
        config_text = render_config(
            model_specs=[spec],
            global_upstream_base="https://agentrouter.org/v1",
            master_key="sk-test",
            drop_params=True,
            streaming=True,
        )

        parsed = yaml.safe_load(config_text)
        assert "reasoning_effort" not in parsed["model_list"][0]["litellm_params"]
