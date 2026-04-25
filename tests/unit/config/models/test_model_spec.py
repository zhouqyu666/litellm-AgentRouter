#!/usr/bin/env python3
"""Unit tests for ModelSpec class and validation."""

from __future__ import annotations

import pytest

from src.config.models import ModelSpec


class TestModelSpecValidation:
    """Test ModelSpec validation and initialization."""

    def test_model_spec_basic_creation(self):
        """Test basic ModelSpec creation with required fields."""
        spec = ModelSpec(
            key="test",
            alias="test-model",
            upstream_model="gpt-4"
        )
        assert spec.key == "test"
        assert spec.alias == "test-model"
        assert spec.upstream_model == "gpt-4"

    def test_model_spec_empty_key(self):
        """Test ModelSpec validation with empty key."""
        with pytest.raises(ValueError, match="Model key cannot be empty"):
            ModelSpec(
                key="",
                alias="test-model",
                upstream_model="gpt-5"
            )

    def test_model_spec_empty_alias_auto_derived(self):
        """Test ModelSpec with empty alias - should be auto-derived from upstream."""
        spec = ModelSpec(
            key="test",
            alias="",
            upstream_model="gpt-5"
        )
        assert spec.alias == "gpt-5"

    def test_model_spec_none_alias_auto_derived(self):
        """Alias of None should also be auto-derived."""
        spec = ModelSpec(
            key="test",
            alias=None,  # type: ignore[arg-type]
            upstream_model="openai/gpt-5",
        )
        assert spec.alias == "gpt-5"

    def test_model_spec_empty_upstream_model(self):
        """Test ModelSpec validation with empty upstream model."""
        with pytest.raises(ValueError, match="Upstream model cannot be empty"):
            ModelSpec(
                key="test",
                alias="test-model",
                upstream_model=""
            )

    def test_model_spec_with_reasoning_effort(self):
        """Test ModelSpec with reasoning effort parameter."""
        spec = ModelSpec(
            key="gpt5",
            alias="gpt-5",
            upstream_model="gpt-5",
            reasoning_effort="medium"
        )
        assert spec.reasoning_effort == "medium"

    def test_model_spec_with_upstream_base(self):
        """Test ModelSpec with custom upstream base URL."""
        spec = ModelSpec(
            key="custom",
            alias="custom-model",
            upstream_model="gpt-4",
            upstream_base="https://custom.api.com/v1"
        )
        assert spec.upstream_base == "https://custom.api.com/v1"

    def test_model_spec_provider_auto_detected_openai(self):
        """Provider should auto-detect to openai for OpenAI models."""
        spec = ModelSpec(key="test", upstream_model="gpt-5")
        assert spec.provider == "openai"

    def test_model_spec_provider_auto_detected_anthropic(self):
        """Provider should auto-detect to anthropic for Claude models."""
        spec = ModelSpec(key="test", upstream_model="claude-sonnet-4-20250514")
        assert spec.provider == "anthropic"

    def test_model_spec_provider_explicit_override(self):
        """Explicit provider should override auto-detection."""
        spec = ModelSpec(key="test", upstream_model="gpt-5", provider="anthropic")
        assert spec.provider == "anthropic"

    def test_model_spec_api_key(self):
        """Per-model API key should be stored on the spec."""
        spec = ModelSpec(key="test", upstream_model="gpt-5", api_key="sk-per-model")
        assert spec.api_key == "sk-per-model"

    def test_model_spec_api_key_default_none(self):
        """api_key should default to None when not provided."""
        spec = ModelSpec(key="test", upstream_model="gpt-5")
        assert spec.api_key is None

    def test_model_spec_post_init(self):
        """Test __post_init__ method for legacy compatibility."""
        spec = ModelSpec(key="test", alias="test-alias", upstream_model="gpt-4")
        spec.__post_init__()
        assert spec.upstream_model == "gpt-4"
