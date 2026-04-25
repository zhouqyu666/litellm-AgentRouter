#!/usr/bin/env python3
"""
Docker entrypoint module for LiteLLM proxy launcher.

This module replaces the bash entrypoint.sh script with Python implementation,
providing better testability and maintainability.
"""

from __future__ import annotations

import os
import re
import sys
from typing import NoReturn

from .config import runtime_config
from ..node.process import NodeProxyProcess
from .parsing import discover_model_keys, load_model_specs_from_env, _collect_provider_api_keys
from .rendering import render_config


def validate_environment() -> None:
    """Validate required environment variables.

    Raises:
        SystemExit: If no MODEL_<KEY>_UPSTREAM_MODEL variables are defined
    """
    runtime_config.ensure_loaded()

    if not discover_model_keys():
        print(
            "ERROR: Define at least one MODEL_<KEY>_UPSTREAM_MODEL environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)


def mask_sensitive_value(value: str, visible_chars: int = 4, visible_suffix: int = 2) -> str:
    """Partially mask a sensitive value for logging.

    Args:
        value: The sensitive value to mask
        visible_chars: Number of characters to show at start
        visible_suffix: Number of characters to show at end

    Returns:
        Partially masked string (e.g., "sk-1***ef")
    """
    if len(value) <= visible_chars + visible_suffix:
        return value[:visible_chars] + "***"
    return value[:visible_chars] + "***" + value[-visible_suffix:]


def mask_config_output(config_text: str) -> str:
    """Mask sensitive values in YAML configuration for logging.

    Args:
        config_text: The YAML configuration text

    Returns:
        Configuration with api_key and master_key values partially masked
    """
    # Mask api_key values
    config_text = re.sub(
        r'(api_key:\s*["\']?)([^\s"\']+)(["\']?)',
        lambda m: m.group(1) + mask_sensitive_value(m.group(2)) + m.group(3),
        config_text
    )
    # Mask master_key values
    config_text = re.sub(
        r'(master_key:\s*["\']?)([^\s"\']+)(["\']?)',
        lambda m: m.group(1) + mask_sensitive_value(m.group(2)) + m.group(3),
        config_text
    )
    return config_text


def write_config_file(config_text: str, path: str) -> None:
    """Write configuration to file.

    Args:
        config_text: The YAML configuration text
        path: File path to write to
    """
    with open(path, 'w') as f:
        f.write(config_text)


def main() -> NoReturn:
    """Main entrypoint function for Docker container startup.

    Flow:
        1. Print startup message
        2. Validate environment variables
        3. Load model specs from environment
        4. Generate YAML configuration
        5. Write configuration to file
        6. Print masked configuration
        7. Execute src.main with generated config
    """
    print("Starting LiteLLM proxy launcher (Python entrypoint)...")

    # Validate environment
    validate_environment()

    # Determine Node upstream configuration
    node_proxy_enabled = runtime_config.get_bool("NODE_UPSTREAM_PROXY_ENABLE", True)
    node_base_url = None
    node_process: NodeProxyProcess | None = None

    if node_proxy_enabled:
        # Try to detect if running in docker-compose by checking for 'node-proxy' hostname
        # In docker-compose, services can reach each other by service name
        import socket
        try:
            socket.gethostbyname('node-proxy')
            # If we can resolve 'node-proxy', we're in docker-compose with separate services
            # Node proxy always listens on port 4000 inside the container
            node_base_url = "http://node-proxy:4000/v1"
            print(f"Using external Node proxy service at {node_base_url}")
        except socket.gaierror:
            # Can't resolve 'node-proxy', so start it as subprocess (single-container mode)
            node_process = NodeProxyProcess()
            try:
                node_proc = node_process.start()
            except RuntimeError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)

            os.environ["NODE_UPSTREAM_PROXY_PID"] = str(node_proc.pid)
            # Node proxy listens on port 4000 by default
            node_base_url = "http://127.0.0.1:4000/v1"
            print(f"Routing LiteLLM upstream through Node helper at {node_base_url}")

    # Load model specs from environment
    try:
        model_specs = load_model_specs_from_env()
    except ValueError as e:
        if node_process:
            node_process.stop()
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate configuration
    runtime_config.ensure_loaded()
    global_upstream_base = node_base_url or runtime_config.get_str("OPENAI_BASE_URL", "https://agentrouter.org/v1")
    master_key = runtime_config.get_str("LITELLM_MASTER_KEY", "sk-local-master")

    # Derive node_proxy_base for Anthropic routing (strip /v1 suffix)
    node_proxy_base = None
    if node_base_url:
        node_proxy_base = node_base_url.rstrip("/")
        if node_proxy_base.endswith("/v1"):
            node_proxy_base = node_proxy_base[:-3]

    # Collect API keys for all providers
    provider_api_keys = _collect_provider_api_keys()

    try:
        config_text = render_config(
            model_specs=model_specs,
            global_upstream_base=global_upstream_base,
            master_key=master_key,
            drop_params=True,
            streaming=True,
            provider_api_keys=provider_api_keys if provider_api_keys else None,
            node_proxy_base=node_proxy_base,
        )
    except Exception as e:
        if node_process:
            node_process.stop()
        print(f"ERROR: Failed to generate configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Write configuration to file (allow override for tests/development)
    config_path = runtime_config.get_str("GENERATED_CONFIG_PATH", "/app/generated-config.yaml")
    try:
        write_config_file(config_text, config_path)
    except Exception as e:
        if node_process:
            node_process.stop()
        print(f"ERROR: Failed to write configuration file: {e}", file=sys.stderr)
        sys.exit(1)

    # Print masked configuration
    print("\nGenerated configuration:")
    print("=" * 80)
    print(mask_config_output(config_text))
    print("=" * 80)

    # Get host and port configuration
    host = runtime_config.get_str("LITELLM_HOST", "0.0.0.0")
    container_port = 4000
    host_port = runtime_config.get_str("PORT", "4000")

    print(f"\nContainer listening on port {container_port}; host publishes {host_port} -> {container_port}")
    print(f"Starting LiteLLM proxy on {host}:{container_port}...\n")

    # Short-circuit for test harnesses so they can inspect generated configs
    if runtime_config.get_bool("ENTRYPOINT_TEST_MODE", False):
        if node_process:
            node_process.stop()
        print("ENTRYPOINT_TEST_MODE enabled; skipping server startup.")
        sys.exit(0)

    # Execute src.main with generated config
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "src.main",
            "--config",
            config_path,
            "--host",
            host,
            "--port",
            str(container_port),
        ]
    )


if __name__ == "__main__":  # pragma: no cover
    main()
