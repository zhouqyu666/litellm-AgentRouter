#!/usr/bin/env python3
"""
Configuration rendering functionality for LiteLLM proxy launcher.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from ..utils import build_user_agent, quote
from . import models
from .models import ModelSpec


def render_model_entry(
    model_spec: ModelSpec,
    global_defaults: Dict[str, Any],
    api_key_override: Optional[str] = None,
) -> List[str]:
    """Render a single model entry for LiteLLM config.

    Args:
        model_spec: The model specification.
        global_defaults: Global configuration defaults.
        api_key_override: If provided, use this key instead of the global default.
    """
    # Use defaults from model_spec, falling back to global defaults
    upstream_base = model_spec.upstream_base or global_defaults.get(
        "upstream_base", "https://agentrouter.org/v1"
    )
    api_key = api_key_override or global_defaults.get("api_key")

    # Convert model to openai/ format if it's not already prefixed
    upstream_model = model_spec.upstream_model
    if not upstream_model.startswith("openai/"):
        upstream_model = f"openai/{upstream_model}"

    lines = [
        f"  - model_name: {quote(model_spec.alias)}",
        "    litellm_params:",
        f"      model: {quote(upstream_model)}",
        f"      api_base: {quote(upstream_base)}",
    ]

    # Add api_key if provided
    if api_key:
        lines.append(f"      api_key: {quote(api_key)}")

    lines.extend([
        f"      custom_llm_provider: {quote('openai')}",
        "      headers:",
        f"        \"User-Agent\": {quote(build_user_agent())}",
        f"        \"Content-Type\": {quote('application/json')}",
    ])

    # Check model capabilities and add reasoning_effort if supported
    capabilities = models.get_model_capabilities(model_spec.upstream_model)
    reasoning_effort = model_spec.reasoning_effort

    if reasoning_effort and reasoning_effort != "none":
        if capabilities.get("supports_reasoning", True):
            lines.append(f"      reasoning_effort: {quote(reasoning_effort)}")
        else:
            # Model doesn't support reasoning, but user explicitly set it
            print(
                f"WARNING: Model {model_spec.upstream_model} does not support reasoning_effort, "
                f"ignoring reasoning_effort={reasoning_effort}",
                file=sys.stderr,
            )

    return lines


def parse_api_keys(api_keys_str: Optional[str]) -> List[str]:
    """Parse a comma-separated string of API keys into a list.

    Args:
        api_keys_str: Comma-separated API keys (e.g. "sk-key1,sk-key2,sk-key3").

    Returns:
        List of non-empty, stripped API key strings.
    """
    if not api_keys_str:
        return []
    return [k.strip() for k in api_keys_str.split(",") if k.strip()]


def render_config(
    *,
    model_specs: List[ModelSpec],
    global_upstream_base: str,
    master_key: str | None,
    drop_params: bool,
    streaming: bool,
    api_key: str | None = None,
    api_keys: List[str] | None = None,
) -> str:
    """Render a LiteLLM proxy config supporting one or more models.

    When *api_keys* contains multiple keys, each model is duplicated once per
    key so that LiteLLM's built-in router load-balances across them.
    """
    if not model_specs:
        raise ValueError("No model specifications provided")

    # Determine the effective set of API keys to use
    effective_keys: List[str] = []
    if api_keys:
        effective_keys = api_keys
    elif api_key:
        effective_keys = [api_key]

    lines = ["model_list:"]
    global_defaults = {
        "upstream_base": global_upstream_base,
        "api_key": None,  # Keys are handled per-entry now
    }

    for model_spec in model_specs:
        if len(effective_keys) > 1:
            # Generate one entry per key for load-balanced routing
            for key in effective_keys:
                lines.extend(render_model_entry(model_spec, global_defaults, api_key_override=key))
        else:
            # Single key or no key – one entry per model (backward compat)
            single_key = effective_keys[0] if effective_keys else None
            lines.extend(render_model_entry(model_spec, global_defaults, api_key_override=single_key))

    lines.append("")
    lines.append("litellm_settings:")
    lines.append(f"  drop_params: {'true' if drop_params else 'false'}")
    lines.append("  set_verbose: false")

    # When multiple keys are present, enable round-robin routing
    if len(effective_keys) > 1:
        lines.append("")
        lines.append("router_settings:")
        lines.append("  routing_strategy: \"simple-shuffle\"")

    if master_key:
        lines.append("")
        lines.append("general_settings:")
        lines.append(f"  master_key: {quote(master_key)}")

    return "\n".join(lines) + "\n"
