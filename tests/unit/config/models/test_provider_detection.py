#!/usr/bin/env python3
"""Unit tests for detect_provider function."""

from __future__ import annotations

import pytest

from src.config.models import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    detect_provider,
)


class TestDetectProviderExplicitPrefix:
    """Provider is inferred from an explicit provider/ prefix on the model string."""

    def test_openai_prefix(self):
        assert detect_provider("openai/gpt-5") == PROVIDER_OPENAI

    def test_anthropic_prefix(self):
        assert detect_provider("anthropic/claude-sonnet-4-20250514") == PROVIDER_ANTHROPIC

    def test_openai_prefix_unknown_model(self):
        """Even an unknown model name should return 'openai' when prefixed."""
        assert detect_provider("openai/some-future-model") == PROVIDER_OPENAI

    def test_anthropic_prefix_unknown_model(self):
        assert detect_provider("anthropic/some-future-model") == PROVIDER_ANTHROPIC


class TestDetectProviderPatternMatch:
    """Provider is detected from model name patterns when no prefix is present."""

    def test_claude_model(self):
        assert detect_provider("claude-sonnet-4-20250514") == PROVIDER_ANTHROPIC

    def test_claude_opus(self):
        assert detect_provider("claude-opus-4-20250514") == PROVIDER_ANTHROPIC

    def test_claude_haiku(self):
        assert detect_provider("claude-haiku-4-20250514") == PROVIDER_ANTHROPIC

    def test_claude_case_insensitive(self):
        assert detect_provider("Claude-3-Sonnet") == PROVIDER_ANTHROPIC

    def test_claude_uppercase(self):
        assert detect_provider("CLAUDE-3-OPUS") == PROVIDER_ANTHROPIC


class TestDetectProviderDefault:
    """Unknown models without a prefix default to 'openai'."""

    def test_gpt_model(self):
        assert detect_provider("gpt-5") == PROVIDER_OPENAI

    def test_deepseek_model(self):
        assert detect_provider("deepseek-v3.2") == PROVIDER_OPENAI

    def test_glm_model(self):
        assert detect_provider("glm-4.6") == PROVIDER_OPENAI

    def test_grok_model(self):
        assert detect_provider("grok-code-fast-1") == PROVIDER_OPENAI

    def test_unknown_model(self):
        assert detect_provider("some-totally-unknown-model") == PROVIDER_OPENAI

    def test_empty_string(self):
        """Edge case: empty string should default to openai."""
        assert detect_provider("") == PROVIDER_OPENAI
