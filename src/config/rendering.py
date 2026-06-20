#!/usr/bin/env python3
"""
Configuration rendering functionality for LiteLLM proxy launcher.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from ..utils import build_user_agent, quote
from . import models
from .models import ModelSpec, PROVIDER_OPENAI, PROVIDER_ANTHROPIC


def _render_openai_params(
    model_spec: ModelSpec,
    upstream_base: str,
    api_key: Optional[str],
) -> List[str]:
    """Render OpenAI-specific litellm_params lines.

    OpenAI models route through the Node proxy and require
    custom_llm_provider, headers, and api_base.
    """
    upstream_model = model_spec.upstream_model
    if not upstream_model.startswith("openai/"):
        upstream_model = f"openai/{upstream_model}"

    lines = [
        f"      model: {quote(upstream_model)}",
        f"      api_base: {quote(upstream_base)}",
    ]

    if api_key:
        lines.append(f"      api_key: {quote(api_key)}")

    lines.extend([
        f"      custom_llm_provider: {quote('openai')}",
        "      headers:",
        f"        \"User-Agent\": {quote(build_user_agent())}",
        f"        \"Content-Type\": {quote('application/json')}",
    ])

    return lines


def _render_anthropic_params(
    model_spec: ModelSpec,
    api_key: Optional[str],
    node_proxy_base: Optional[str] = None,
) -> List[str]:
    """Render Anthropic-specific litellm_params lines.

    Anthropic models route through the Node proxy (when node_proxy_base is
    set) so the Anthropic JS SDK provides the proper User-Agent.
    Per-model upstream_base takes precedence over node_proxy_base.
    No custom_llm_provider or headers needed.
    """
    upstream_model = model_spec.upstream_model
    if not upstream_model.startswith("anthropic/"):
        upstream_model = f"anthropic/{upstream_model}"

    lines = [
        f"      model: {quote(upstream_model)}",
    ]

    # Per-model upstream_base takes precedence, then node_proxy_base
    if model_spec.upstream_base:
        lines.append(f"      api_base: {quote(model_spec.upstream_base)}")
    elif node_proxy_base:
        lines.append(f"      api_base: {quote(node_proxy_base)}")

    if api_key:
        lines.append(f"      api_key: {quote(api_key)}")

    return lines


def _append_reasoning_effort(
    lines: List[str],
    model_spec: ModelSpec,
) -> None:
    """Append reasoning_effort to lines if the model supports it."""
    capabilities = models.get_model_capabilities(model_spec.upstream_model)
    reasoning_effort = model_spec.reasoning_effort

    if reasoning_effort and reasoning_effort != "none":
        if capabilities.get("supports_reasoning", True):
            lines.append(f"      reasoning_effort: {quote(reasoning_effort)}")
        else:
            print(
                f"WARNING: Model {model_spec.upstream_model} does not support reasoning_effort, "
                f"ignoring reasoning_effort={reasoning_effort}",
                file=sys.stderr,
            )


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
    provider = model_spec.provider
    api_key = api_key_override or model_spec.api_key or global_defaults.get("api_key")

    lines = [
        f"  - model_name: {quote(model_spec.alias)}",
        "    litellm_params:",
    ]

    if provider == PROVIDER_ANTHROPIC:
        node_proxy_base = global_defaults.get("node_proxy_base")
        lines.extend(_render_anthropic_params(model_spec, api_key, node_proxy_base))
    else:
        # Default: OpenAI path (backward compatible)
        upstream_base = model_spec.upstream_base or global_defaults.get(
            "upstream_base", "https://agentrouter.org/v1"
        )
        lines.extend(_render_openai_params(model_spec, upstream_base, api_key))

    _append_reasoning_effort(lines, model_spec)

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
    provider_api_keys: Dict[str, List[str]] | None = None,
    node_proxy_base: str | None = None,
) -> str:
    """Render a LiteLLM proxy config supporting one or more models.

    When *api_keys* contains multiple keys, each OpenAI model is duplicated
    once per key so that LiteLLM's built-in router load-balances across them.

    *provider_api_keys* maps provider names to lists of API keys. When set,
    each model uses keys for its provider. The legacy *api_key*/*api_keys*
    parameters are treated as OpenAI keys for backward compatibility.
    """
    if model_specs is None:
        raise ValueError("No model specifications provided")

    # Build per-provider key sets
    pkeys: Dict[str, List[str]] = dict(provider_api_keys) if provider_api_keys else {}

    # Legacy api_key/api_keys are treated as OpenAI keys (backward compat)
    if PROVIDER_OPENAI not in pkeys:
        if api_keys:
            pkeys[PROVIDER_OPENAI] = api_keys
        elif api_key:
            pkeys[PROVIDER_OPENAI] = [api_key]

    lines = ["model_list:"]
    if not model_specs:
        lines[0] = "model_list: []"
    global_defaults: Dict[str, Any] = {
        "upstream_base": global_upstream_base,
        "api_key": None,
        "node_proxy_base": node_proxy_base,
    }

    any_multi_key = False

    for model_spec in model_specs:
        provider = model_spec.provider
        effective_keys = pkeys.get(provider, [])

        if len(effective_keys) > 1:
            any_multi_key = True
            for key in effective_keys:
                lines.extend(render_model_entry(model_spec, global_defaults, api_key_override=key))
        else:
            single_key = effective_keys[0] if effective_keys else None
            lines.extend(render_model_entry(model_spec, global_defaults, api_key_override=single_key))

    lines.append("")
    lines.append("litellm_settings:")
    lines.append(f"  drop_params: {'true' if drop_params else 'false'}")
    lines.append("  set_verbose: false")

    # When multiple keys are present for any provider, enable round-robin routing
    if any_multi_key:
        lines.append("")
        lines.append("router_settings:")
        lines.append("  routing_strategy: \"simple-shuffle\"")

    if master_key:
        lines.append("")
        lines.append("general_settings:")
        lines.append(f"  master_key: {quote(master_key)}")

    return "\n".join(lines) + "\n"
