#!/usr/bin/env python3
"""
Proxy startup and management for LiteLLM proxy launcher.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def start_proxy(args: argparse.Namespace, config_path: Path) -> None:
    """Start the LiteLLM proxy with the given configuration."""
    import sys
    import os

    # Fix Windows UTF-8 encoding for LiteLLM banner display
    if sys.platform == 'win32':
        import codecs
        # Only wrap stdout/stderr if they have a buffer attribute (not already wrapped)
        if hasattr(sys.stdout, 'buffer'):
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
        if hasattr(sys.stderr, 'buffer'):
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')
        os.environ['PYTHONIOENCODING'] = 'utf-8'

    from litellm.proxy.proxy_cli import run_server

    import logging
    logger = logging.getLogger(__name__)

    # Initialize telemetry logging regardless of model spec source
    try:
        from .middleware.registry import install_middlewares
        model_specs = getattr(args, "model_specs", None) or []
        # Import LiteLLM app and install middlewares directly
        from litellm.proxy import proxy_server
        if hasattr(proxy_server, 'app'):
            install_middlewares(proxy_server.app, model_specs)
            # Install admin management panel
            try:
                from .admin.install import install_admin
                install_admin(proxy_server.app)
            except Exception as admin_err:
                logger.warning(f"Failed to install admin routes: {admin_err}")
    except Exception as e:
        logger.warning(f"Failed to initialize middlewares: {e}")

    cli_args = [
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--num_workers",
        str(args.workers),
        "--config",
        str(config_path),
    ]

    if args.debug:
        cli_args.append("--debug")
    if args.detailed_debug:
        cli_args.append("--detailed_debug")

    try:
        run_server.main(cli_args, standalone_mode=False)
    except SystemExit as exc:  # pragma: no cover - click invocation
        if exc.code not in (0, None):
            raise
