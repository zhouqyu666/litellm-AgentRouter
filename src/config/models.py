#!/usr/bin/env python3
"""
Configuration models for LiteLLM proxy launcher.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

# Provider constants
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

# Model name prefix → provider mapping
_PROVIDER_PATTERNS: Dict[str, str] = {}


def detect_provider(upstream_model: str) -> str:
    """Detect provider from upstream model identifier.

    If the model already has a known provider prefix (e.g. 'openai/', 'anthropic/'),
    return that provider. Otherwise, match against known model name prefixes.
    Defaults to 'openai' for backward compatibility.

    Args:
        upstream_model: The upstream model identifier.

    Returns:
        Provider string (e.g. 'openai', 'anthropic').
    """
    known_prefixes = {
        f"{PROVIDER_OPENAI}/": PROVIDER_OPENAI,
        f"{PROVIDER_ANTHROPIC}/": PROVIDER_ANTHROPIC,
    }

    for prefix, provider in known_prefixes.items():
        if upstream_model.startswith(prefix):
            return provider

    # Match against model name patterns
    model_lower = upstream_model.lower()
    for pattern, provider in _PROVIDER_PATTERNS.items():
        if model_lower.startswith(pattern):
            return provider

    return PROVIDER_OPENAI


def derive_alias(upstream_model: str) -> str:
    """Derive public alias from upstream model identifier.

    Args:
        upstream_model: The upstream model identifier (e.g., 'openai/gpt-5', 'deepseek-v3.2')

    Returns:
        Derived alias string (e.g., 'gpt-5', 'deepseek-v3.2')
    """
    # Strip known provider prefixes
    known_prefixes = ['openai/', 'anthropic/', 'google/', 'azure/']

    for prefix in known_prefixes:
        if upstream_model.startswith(prefix):
            return upstream_model[len(prefix):]

    # Return upstream model unchanged when no known prefix exists
    return upstream_model


class ModelSpec:
    """Configuration for a single model in the proxy."""

    def __init__(
        self,
        key: str,
        upstream_model: str,
        alias: Optional[str] = None,
        upstream_base: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize ModelSpec.

        Args:
            key: Logical key identifier
            alias: Public model name exposed by proxy (auto-derived if not provided)
            upstream_model: Upstream provider model ID
            upstream_base: Base URL (defaults to global)
            reasoning_effort: Reasoning effort level
            provider: Explicit provider override (auto-detected if None)
            api_key: Per-model API key
        """
        self.key = key
        self.alias = alias or derive_alias(upstream_model)
        self.upstream_model = upstream_model
        self.upstream_base = upstream_base
        self.reasoning_effort = reasoning_effort
        self.provider = provider or detect_provider(upstream_model)
        self.api_key = api_key
        self._validate()

    def _validate(self) -> None:
        """Validate model spec parameters."""
        if not self.key:
            raise ValueError("Model key cannot be empty")
        if not self.upstream_model:
            raise ValueError("Upstream model cannot be empty")

    def __post_init__(self) -> None:
        """Legacy compatibility - validation now done in __init__."""
        pass


# Model capability mapping
MODEL_CAPS: Dict[str, Dict[str, Any]] = {
    "deepseek-v3.2": {"supports_reasoning": True},
    "gpt-5": {"supports_reasoning": True},
    "glm-4.6": {"supports_reasoning": False},
    "glm-5.1": {"supports_reasoning": True},
    "grok-code-fast-1": {"supports_reasoning": True},
    # Anthropic models (extended thinking is not controlled via reasoning_effort)
    "claude-sonnet-4-20250514": {"supports_reasoning": False},
    "claude-opus-4-20250514": {"supports_reasoning": False},
    "claude-haiku-4-20250514": {"supports_reasoning": False},
    "claude-opus-4-6": {"supports_reasoning": False},
    "claude-haiku-4-5-20251001": {"supports_reasoning": False},
    # Add more models as needed
}


def get_model_capabilities(upstream_model: str) -> Dict[str, Any]:
    """Get capabilities for a model, defaulting to unknown model capabilities."""
    return MODEL_CAPS.get(upstream_model, {"supports_reasoning": True})  # Default to not supporting reasoning
