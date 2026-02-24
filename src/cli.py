#!/usr/bin/env python3
"""
Command-line interface for LiteLLM proxy launcher.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .utils import env_bool
from .config.parsing import load_model_specs_from_cli


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the LiteLLM proxy."""
    parser = argparse.ArgumentParser(
        description=(
            "Start a LiteLLM proxy that exposes a local OpenAI-compatible API. "
            "By default a minimal config is generated using upstream environment "
            "variables; pass --config to supply your own config.yaml."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to an existing LiteLLM config.yaml.",
    )
    parser.add_argument(
        "--alias",
        default="gpt-5",
        help="Public model name to expose from the proxy.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-5"),
        help="Upstream provider model identifier.",
    )
    parser.add_argument(
        "--upstream-base",
        dest="upstream_base",
        default=None,
        help="Base URL for the upstream OpenAI-compatible endpoint. "
             "When set, bypasses the Node upstream proxy.",
    )
    node_proxy_default = env_bool("NODE_UPSTREAM_PROXY_ENABLE", True)
    parser.add_argument(
        "--node-upstream-proxy",
        dest="node_upstream_proxy_enabled",
        action="store_true",
        default=node_proxy_default,
        help="Enable routing through the Node upstream proxy (default: NODE_UPSTREAM_PROXY_ENABLE).",
    )
    parser.add_argument(
        "--no-node-upstream-proxy",
        dest="node_upstream_proxy_enabled",
        action="store_false",
        help="Disable routing through the Node upstream proxy.",
    )

    parser.add_argument(
        "--master-key",
        dest="master_key",
        default=os.getenv("LITELLM_MASTER_KEY", "sk-local-master"),
        help="Optional master key enforced by the proxy (Authorization bearer token).",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host interface for the proxy.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "4000")),
        help="Port for the proxy.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of worker processes to run.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable LiteLLM debug logging.",
    )
    parser.add_argument(
        "--detailed-debug",
        action="store_true",
        default=False,
        help="Enable verbose LiteLLM proxy debug logging.",
    )
    parser.add_argument(
        "--no-master-key",
        action="store_true",
        help="Disable setting a proxy master key in the generated config.",
    )
    parser.add_argument(
        "--drop-params",
        dest="drop_params",
        action="store_true",
        default=True,
        help="Enable litellm.drop_params in the generated config.",
    )
    parser.add_argument(
        "--no-drop-params",
        dest="drop_params",
        action="store_false",
        help="Disable litellm.drop_params in the generated config.",
    )
    streaming_default = env_bool("STREAMING_ENABLE", True)
    parser.add_argument(
        "--streaming",
        dest="streaming",
        action="store_true",
        default=streaming_default,
        help="Enable streaming mode in the generated config (default: from STREAMING_ENABLE env var).",
    )
    parser.add_argument(
        "--no-streaming",
        dest="streaming",
        action="store_false",
        help="Disable streaming mode in the generated config.",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="Print the generated config and exit (useful for inspection).",
    )
    reasoning_default = os.getenv("REASONING_EFFORT", "medium")
    parser.add_argument(
        "--reasoning-effort",
        dest="reasoning_effort",
        default=reasoning_default,
        choices=["none", "low", "medium", "high"],
        help=(
            "Reasoning effort level for supported models (default: from "
            "REASONING_EFFORT env var, defaults to 'medium')."
        ),
    )
    parser.add_argument(
        "--model-spec",
        dest="model_specs",
        action="append",
        help=(
            "Model specification for multi-model proxy. Format: "
            "key=xxx,alias=xxx,upstream=xxx[,base=xxx][,reasoning=xxx]. "
            "Can be used multiple times."
        ),
    )

    args = parser.parse_args(argv)

    # Parse model specs if provided
    if args.model_specs:
        try:
            args.model_specs = load_model_specs_from_cli(args.model_specs)
        except ValueError as e:
            parser.error(f"Invalid model specification: {e}")

    return args
