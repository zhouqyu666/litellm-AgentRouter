#!/usr/bin/env python3
"""
Main entry point for LiteLLM proxy launcher.
"""

from __future__ import annotations

import os
import sys
from typing import NoReturn
from pathlib import Path

from .cli import parse_args
from .config.config import runtime_config
from .config.parsing import prepare_config
from .config.parsing import auto_migrate_from_env_if_db_empty
from .config.parsing import sync_db_to_environ
from .utils import (
    attach_signal_handlers,
    create_temp_config_if_needed,
    register_node_proxy_cleanup,
    validate_prereqs,
    env_bool,
)
from .proxy import start_proxy


def _start_node_proxy_process():
    """Start the Node upstream proxy subprocess if needed.

    Returns:
        Tuple of (node_process, node_base_url) or (None, None) if not started.
    """
    # Check if Node proxy is enabled
    if not env_bool("NODE_UPSTREAM_PROXY_ENABLE", True):
        return None, None

    # Check if we're in docker-compose mode with external node-proxy service
    import socket
    try:
        socket.gethostbyname('node-proxy')
        # External Node proxy service is available
        node_base_url = "http://node-proxy:4000/v1"
        print(f"Using external Node proxy service at {node_base_url}")
        return None, node_base_url
    except socket.gaierror:
        # No external service, start as subprocess
        pass

    # Start Node proxy as subprocess
    from .node.process import NodeProxyProcess
    try:
        node_process = NodeProxyProcess()
        proc = node_process.start()
        os.environ["NODE_UPSTREAM_PROXY_PID"] = str(proc.pid)
        node_base_url = "http://127.0.0.1:4000/v1"
        print(f"Routing LiteLLM upstream through Node helper at {node_base_url}")
        return node_process, node_base_url
    except RuntimeError as exc:
        print(f"WARNING: Failed to start Node upstream proxy: {exc}", file=sys.stderr)
        print("Falling back to direct upstream connection.", file=sys.stderr)
        return None, None


def get_startup_message(args) -> str:
    """Generate startup message with model information."""
    host_port = f"{args.host}:{args.port}"
    model_specs = getattr(args, "model_specs", None) or []

    if args.config:
        # Using config file
        return f"Starting LiteLLM proxy on {host_port} using config file {args.config}"

    if model_specs:
        alias_info = ", ".join(f"{spec.alias} ({spec.upstream_model})" for spec in model_specs)
        return f"Starting LiteLLM proxy on {host_port} with {len(model_specs)} model(s): {alias_info}"

    # Should not happen: prepare_config enforces presence of model specs.
    return (
        f"Starting LiteLLM proxy on {host_port} with generated config "
        "(no model specifications found)"
    )


def main(argv: list[str] | None = None) -> NoReturn:
    """Main entry point for the LiteLLM proxy launcher."""
    runtime_config.ensure_loaded()
    validate_prereqs()
    register_node_proxy_cleanup()
    args = parse_args(argv)
    attach_signal_handlers()

    if not args.config and os.getenv("CONFIG_BACKEND", "db").lower() != "env":
        migration_summary = auto_migrate_from_env_if_db_empty()
        if migration_summary:
            print(f"Migrated config from .env to SQLite: {migration_summary}")
        sync_db_to_environ()

    # Start Node upstream proxy if needed (before prepare_config which uses it)
    node_process = None
    if not args.config and getattr(args, "node_upstream_proxy_enabled", True):
        node_process, node_base_url = _start_node_proxy_process()
        # If Node proxy failed to start, disable it in args so prepare_config falls back
        if node_process is None and node_base_url is None:
            args.node_upstream_proxy_enabled = False

    config_data, is_generated = prepare_config(args)

    # Handle --print-config flag: print config and exit
    if getattr(args, 'print_config', False) is True:
        if node_process:
            node_process.stop()
        if is_generated:
            print(config_data)
        else:
            config_path = Path(config_data)
            print(config_path.read_text(encoding="utf-8"))
        sys.exit(0)
        return

    with create_temp_config_if_needed(config_data, is_generated) as config_path:
        print(get_startup_message(args))
        start_proxy(args, config_path)

    # Cleanup Node proxy on exit
    if node_process:
        node_process.stop()

    # This should never be reached, but included for completeness
    sys.exit(0)


if __name__ == "__main__":
    main()
