#!/usr/bin/env python3
"""Helpers for synchronizing settings to the Node upstream proxy."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


def get_node_proxy_base_url(default: str | None = None) -> str:
    """Return the internal Node proxy base URL without a /v1 suffix."""
    explicit = os.getenv("ADMIN_NODE_PROXY_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    if default:
        base_url = default.rstrip("/")
        return base_url[:-3] if base_url.endswith("/v1") else base_url
    return "http://127.0.0.1:4000"


def sync_upstream_proxy(proxy_url: str | None, base_url: str | None = None) -> dict[str, Any]:
    """Push the upstream proxy URL to the running Node proxy."""
    target = f"{get_node_proxy_base_url(base_url)}/__admin/upstream-proxy"
    payload = json.dumps({"proxy_url": proxy_url or ""}).encode("utf-8")
    request = Request(
        target,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urlopen(request, timeout=5) as response:
            response_data = response.read().decode("utf-8")
            return json.loads(response_data) if response_data else {"status": "ok"}
    except URLError as exc:
        logger.warning("Failed to sync upstream proxy to Node proxy: %s", exc)
        return {"error": str(exc)}
    except Exception as exc:
        logger.warning("Unexpected error syncing upstream proxy to Node proxy: %s", exc)
        return {"error": str(exc)}
