#!/usr/bin/env python3
"""
Hot reload via LiteLLM management API.
Calls /model/new and /model/delete to update the running proxy without restart.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)


def _get_proxy_base_url() -> str:
    """Get the LiteLLM proxy base URL for management API calls."""
    return os.getenv("ADMIN_PROXY_BASE_URL", "http://127.0.0.1:4000")


def _get_master_key() -> str:
    """Get the master key for authenticating with LiteLLM API."""
    return os.getenv("LITELLM_MASTER_KEY", "")


def _make_request(
    method: str,
    path: str,
    body: Optional[Dict] = None,
) -> Optional[Dict[str, Any]]:
    """Make an HTTP request to the LiteLLM proxy."""
    url = f"{_get_proxy_base_url()}{path}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_get_master_key()}",
    }

    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(req, timeout=10) as resp:
            response_data = resp.read().decode("utf-8")
            if response_data:
                return json.loads(response_data)
            return {"status": "ok"}
    except URLError as e:
        logger.warning(f"LiteLLM API call failed: {method} {path} - {e}")
        return None
    except Exception as e:
        logger.warning(f"Unexpected error calling LiteLLM API: {e}")
        return None


def get_current_models() -> List[Dict[str, Any]]:
    """Get the current model list from LiteLLM proxy."""
    result = _make_request("GET", "/v1/models")
    if result and "data" in result:
        return result["data"]

    # Fallback: try /model/info endpoint
    result = _make_request("GET", "/model/info")
    if result and "data" in result:
        return result["data"]
    return []


def add_model(model_params: Dict[str, Any]) -> bool:
    """Add a model to the running LiteLLM proxy via /model/new."""
    result = _make_request("POST", "/model/new", body=model_params)
    return result is not None


def delete_model(model_id: str) -> bool:
    """Delete a model from the running LiteLLM proxy via /model/delete."""
    result = _make_request("POST", "/model/delete", body={"id": model_id})
    return result is not None


def delete_model_by_name(model_name: str) -> bool:
    """Delete all model entries matching a model name."""
    current = get_current_models()
    deleted_any = False
    for model in current:
        if model.get("model_name") == model_name or model.get("id") == model_name:
            model_id = model.get("model_info", {}).get("id", model.get("id"))
            if model_id:
                if delete_model(model_id):
                    deleted_any = True
    return deleted_any


def add_model_entry(
    model_name: str,
    litellm_params: Dict[str, Any],
) -> bool:
    """Add a single model entry to LiteLLM proxy."""
    payload = {
        "model_name": model_name,
        "litellm_params": litellm_params,
    }
    return add_model(payload)


def full_reload(model_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Perform a full model list reload.

    1. Get current models from LiteLLM
    2. Delete all existing models
    3. Add all desired models
    4. Return summary
    """
    current = get_current_models()

    # Delete all current models
    deleted_count = 0
    for model in current:
        model_id = model.get("model_info", {}).get("id", model.get("id"))
        if model_id and delete_model(model_id):
            deleted_count += 1

    # Add all desired models
    added_count = 0
    failed_count = 0
    for entry in model_entries:
        if add_model(entry):
            added_count += 1
        else:
            failed_count += 1

    return {
        "deleted": deleted_count,
        "added": added_count,
        "failed": failed_count,
        "requires_restart": failed_count > 0,
    }


def build_model_entry(
    model_name: str,
    provider: str,
    api_base: str,
    api_key: str,
    upstream_model: str,
    reasoning_effort: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a LiteLLM model entry dict."""
    from src.config.models import PROVIDER_ANTHROPIC

    litellm_params: Dict[str, Any] = {}

    if provider == PROVIDER_ANTHROPIC:
        litellm_params["model"] = f"anthropic/{upstream_model}"
        litellm_params["api_base"] = api_base
        litellm_params["api_key"] = api_key
    else:
        litellm_params["model"] = f"openai/{upstream_model}"
        litellm_params["api_base"] = api_base
        litellm_params["api_key"] = api_key
        litellm_params["custom_llm_provider"] = "openai"

    if reasoning_effort and reasoning_effort.lower() != "none":
        litellm_params["reasoning_effort"] = reasoning_effort

    return {
        "model_name": model_name,
        "litellm_params": litellm_params,
    }
