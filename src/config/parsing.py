#!/usr/bin/env python3
"""
Configuration parsing functionality for LiteLLM proxy launcher.
"""

from __future__ import annotations

import os
import re
import sys
from typing import List, Mapping

from .models import ModelSpec

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
    )


def discover_model_keys(env: Mapping[str, str] | None = None) -> List[str]:
    """Discover logical model keys by scanning MODEL_<KEY>_UPSTREAM_MODEL env vars."""
    source = env or os.environ
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
    source = env or os.environ
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

        if not upstream_model:
            raise ValueError(f"Missing environment variable: {prefix}UPSTREAM_MODEL")

        model_specs.append(
            ModelSpec(
                key=key.lower(),
                alias=None,  # Let ModelSpec derive alias from upstream_model
                upstream_model=upstream_model,
                upstream_base=upstream_base,  # None unless explicitly set per-model
                reasoning_effort=reasoning_effort,
            )
        )

    return model_specs


def load_model_specs_from_cli(model_spec_args: List[str] | None) -> List[ModelSpec]:
    """Load model specifications from CLI --model-spec arguments."""
    if not model_spec_args:
        return []

    return [parse_model_spec(spec_str) for spec_str in model_spec_args]


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
    if custom_upstream_base:
        global_upstream_base = custom_upstream_base
    else:
        # Otherwise, check if Node proxy is enabled (default: True)
        node_proxy_enabled = getattr(args, "node_upstream_proxy_enabled", True)
        if node_proxy_enabled:
            global_upstream_base = "http://127.0.0.1:4000/v1"  # Node proxy always uses port 4000
        else:
            global_upstream_base = "https://agentrouter.org/v1"
    master_key = None if getattr(args, 'no_master_key', False) else getattr(args, 'master_key', "sk-local-master")
    drop_params = getattr(args, 'drop_params', True)
    streaming = getattr(args, 'streaming', True)

    # Collect API keys: prefer OPENAI_API_KEYS (comma-separated) over single OPENAI_API_KEY
    # Also detect comma-separated keys in OPENAI_API_KEY for convenience
    from .rendering import parse_api_keys

    api_keys_str = os.environ.get("OPENAI_API_KEYS")
    api_keys = parse_api_keys(api_keys_str)

    if not api_keys:
        # Fallback: if OPENAI_API_KEY contains commas, treat it as multiple keys
        single_str = os.environ.get("OPENAI_API_KEY", "")
        if "," in single_str:
            api_keys = parse_api_keys(single_str)

    single_api_key = os.environ.get("OPENAI_API_KEY") if not api_keys else None

    # Generate configuration
    config_text = render_config(
        model_specs=model_specs,
        global_upstream_base=global_upstream_base,
        master_key=master_key,
        drop_params=drop_params,
        streaming=streaming,
        api_key=single_api_key,
        api_keys=api_keys if api_keys else None,
    )

    return config_text, True
