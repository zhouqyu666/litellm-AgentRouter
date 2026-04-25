#!/usr/bin/env python3
"""
Configuration parsing functionality for LiteLLM proxy launcher.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Mapping

from .models import ModelSpec, PROVIDER_OPENAI, PROVIDER_ANTHROPIC

MODEL_ENV_PATTERN = re.compile(r"^MODEL_([A-Z0-9_]+)_UPSTREAM_MODEL$")
_proxy_warning_emitted = False


def parse_model_spec(spec_str: str) -> ModelSpec:
    """Parse a model specification string into a ModelSpec object.

    Format: key=xxx,upstream=xxx[,alias=xxx][,base=xxx][,key_env=xxx][,reasoning=xxx]
    """
    parts: dict[str, str] = {}
    for part in spec_str.split(','):
        if '=' not in part:
            raise ValueError(f"Invalid model spec part: {part}")
        key, value = part.split('=', 1)
        parts[key.strip()] = value.strip()

    required_fields = ['key', 'upstream']
    missing = [field for field in required_fields if field not in parts]
    if missing:
        raise ValueError(f"Missing required fields in model spec: {missing}")

    # Alias is optional - derive from upstream if not provided
    alias = parts.get('alias')

    return ModelSpec(
        key=parts['key'],
        alias=alias,
        upstream_model=parts['upstream'],
        upstream_base=parts.get('base'),
        reasoning_effort=parts.get('reasoning'),
        provider=parts.get('provider'),
        api_key=parts.get('api_key'),
    )


def discover_model_keys(env: Mapping[str, str] | None = None) -> List[str]:
    """Discover logical model keys by scanning MODEL_<KEY>_UPSTREAM_MODEL env vars."""
    source = os.environ if env is None else env
    keys = {
        match.group(1)
        for name in source.keys()
        if (match := MODEL_ENV_PATTERN.match(name))
    }
    return sorted(keys, key=str.lower)  # Deterministic alphabetical ordering


def _warn_if_proxy_keys_present(env: Mapping[str, str]) -> None:
    """Emit a warning when deprecated PROXY_MODEL_KEYS is still defined."""
    global _proxy_warning_emitted
    if _proxy_warning_emitted or "PROXY_MODEL_KEYS" not in env:
        return

    print(
        "WARNING: PROXY_MODEL_KEYS is ignored; declare MODEL_<KEY>_UPSTREAM_MODEL variables instead.",
        file=sys.stderr,
    )
    _proxy_warning_emitted = True


def load_model_specs_from_env(env: Mapping[str, str] | None = None) -> List[ModelSpec]:
    """Load model specifications from environment variables using autodiscovery."""
    source = os.environ if env is None else env
    keys = discover_model_keys(source)
    _warn_if_proxy_keys_present(source)

    if not keys:
        raise ValueError(
            "No model definitions found. "
            "Set at least one MODEL_<KEY>_UPSTREAM_MODEL environment variable."
        )

    model_specs: List[ModelSpec] = []

    for key in keys:
        prefix = f"MODEL_{key}_"

        # Check for legacy alias variables and fail fast
        alias_env_var = f"{prefix}ALIAS"
        if source.get(alias_env_var):
            raise ValueError(
                f"Legacy environment variable '{alias_env_var}' detected. "
                f"Please remove it and use only MODEL_{key}_UPSTREAM_MODEL. "
                f"The alias will be automatically derived from the upstream model name."
            )

        upstream_model = source.get(f"{prefix}UPSTREAM_MODEL")
        upstream_base = source.get(f"{prefix}UPSTREAM_BASE")
        reasoning_effort = source.get(f"{prefix}REASONING_EFFORT")
        provider = source.get(f"{prefix}PROVIDER")
        per_model_api_key = source.get(f"{prefix}API_KEY")

        if not upstream_model:
            raise ValueError(f"Missing environment variable: {prefix}UPSTREAM_MODEL")

        model_specs.append(
            ModelSpec(
                key=key.lower(),
                alias=None,  # Let ModelSpec derive alias from upstream_model
                upstream_model=upstream_model,
                upstream_base=upstream_base,  # None unless explicitly set per-model
                reasoning_effort=reasoning_effort,
                provider=provider,
                api_key=per_model_api_key,
            )
        )

    return model_specs


def load_model_specs_from_cli(model_spec_args: List[str] | None) -> List[ModelSpec]:
    """Load model specifications from CLI --model-spec arguments."""
    if not model_spec_args:
        return []

    return [parse_model_spec(spec_str) for spec_str in model_spec_args]


def _collect_provider_api_keys(
    env: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Collect API keys for all known providers from environment variables.

    For each provider, the priority is:
      1. <PROVIDER>_API_KEYS (comma-separated multi-key)
      2. <PROVIDER>_API_KEY containing commas (auto-split)
      3. <PROVIDER>_API_KEY (single key)

    When ANTHROPIC_API_KEY(S) is not set, falls back to OPENAI_API_KEY(S)
    since unified proxies like agentrouter.org use a single key for all
    providers.

    Returns:
        Dict mapping provider name to list of API keys.
    """
    from .rendering import parse_api_keys

    source = os.environ if env is None else env

    providers = {
        PROVIDER_OPENAI: ("OPENAI_API_KEYS", "OPENAI_API_KEY"),
        PROVIDER_ANTHROPIC: ("ANTHROPIC_API_KEYS", "ANTHROPIC_API_KEY"),
    }

    result: dict[str, list[str]] = {}
    for provider, (multi_var, single_var) in providers.items():
        keys = parse_api_keys(source.get(multi_var))
        if not keys:
            single_str = source.get(single_var, "")
            if "," in single_str:
                keys = parse_api_keys(single_str)
            elif single_str.strip():
                keys = [single_str.strip()]
        if keys:
            result[provider] = keys

    # Fallback: use OpenAI keys for Anthropic when no Anthropic keys are set.
    # Unified proxies (e.g. agentrouter.org) accept the same key for all providers.
    if PROVIDER_ANTHROPIC not in result and PROVIDER_OPENAI in result:
        result[PROVIDER_ANTHROPIC] = list(result[PROVIDER_OPENAI])

    return result


def prepare_config(args) -> tuple[str, bool]:
    """Prepare configuration from args, returning (config_text, is_generated).

    Args:
        args: Parsed CLI arguments with attributes like config, model_specs, etc.

    Returns:
        Tuple of (config_text, is_generated) where:
        - config_text: YAML configuration string
        - is_generated: True if config was generated from specs/env, False if from file
    """
    from pathlib import Path
    import sys
    from .rendering import render_config

    # If config file is provided, read and return it
    if getattr(args, 'config', None):
        config_path = Path(args.config)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {args.config}")

        return config_path, False

    # Otherwise generate config from model specs or environment
    model_specs = getattr(args, 'model_specs', None)

    if not model_specs:
        # Try loading from environment
        try:
            model_specs = load_model_specs_from_env()
            # Store model specs back into args for consistency
            setattr(args, 'model_specs', model_specs)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)

    # Get configuration parameters from args with defaults
    # If a custom upstream_base is provided via CLI, use it directly (disable Node proxy routing)
    custom_upstream_base = getattr(args, 'upstream_base', None)
    node_proxy_base = None
    if custom_upstream_base:
        global_upstream_base = custom_upstream_base
    else:
        # Otherwise, check if Node proxy is enabled (default: True)
        node_proxy_enabled = getattr(args, "node_upstream_proxy_enabled", True)
        if node_proxy_enabled:
            global_upstream_base = "http://127.0.0.1:4000/v1"  # Node proxy always uses port 4000
            # Anthropic api_base uses the proxy without /v1 suffix
            # (LiteLLM's Anthropic provider appends /v1/messages itself)
            node_proxy_base = "http://127.0.0.1:4000"
        else:
            global_upstream_base = "https://agentrouter.org/v1"
    master_key = None if getattr(args, 'no_master_key', False) else getattr(args, 'master_key', None) or os.environ.get("LITELLM_MASTER_KEY", "sk-local-master")
    drop_params = getattr(args, 'drop_params', True)
    streaming = getattr(args, 'streaming', True)

    # Collect API keys for all providers
    provider_api_keys = _collect_provider_api_keys()

    # Generate configuration
    config_text = render_config(
        model_specs=model_specs,
        global_upstream_base=global_upstream_base,
        master_key=master_key,
        drop_params=drop_params,
        streaming=streaming,
        provider_api_keys=provider_api_keys if provider_api_keys else None,
        node_proxy_base=node_proxy_base,
    )

    return config_text, True
