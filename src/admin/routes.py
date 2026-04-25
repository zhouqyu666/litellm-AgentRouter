#!/usr/bin/env python3
"""
Admin API routes for AgentRouter management panel.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from .auth import is_auth_enabled, verify_credentials, verify_token
from .env_manager import EnvFile
from .hotreload import (
    add_model_entry,
    build_model_entry,
    delete_model_by_name,
    full_reload as do_full_reload,
)

admin_router = APIRouter(prefix="/admin/api", tags=["admin"])
security = HTTPBearer(auto_error=False)

_env_file: Optional[EnvFile] = None


def _get_env_file() -> EnvFile:
    """Get or create the EnvFile singleton."""
    global _env_file
    if _env_file is None:
        _env_file = EnvFile()
    return _env_file


def set_env_file(env_file: EnvFile) -> None:
    """Set a custom EnvFile (for testing)."""
    global _env_file
    _env_file = env_file


async def require_auth(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """Dependency that verifies JWT token or passes if auth is disabled."""
    if not is_auth_enabled():
        return {"sub": "anonymous"}

    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    payload = verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return payload


# --- Request/Response Models ---


class LoginRequest(BaseModel):
    username: str
    password: str


class ModelCreateRequest(BaseModel):
    key: str
    upstream_model: str
    reasoning_effort: Optional[str] = None
    upstream_base: Optional[str] = None
    provider: Optional[str] = None


class ModelUpdateRequest(BaseModel):
    upstream_model: Optional[str] = None
    reasoning_effort: Optional[str] = None
    upstream_base: Optional[str] = None
    provider: Optional[str] = None


class KeysUpdateRequest(BaseModel):
    keys: List[str]


class KeyAddRequest(BaseModel):
    key: str


# --- Auth Endpoints ---


@admin_router.post("/login")
async def login(req: LoginRequest):
    if not is_auth_enabled():
        # Auth disabled — generate a placeholder token
        from .auth import create_token
        token = create_token("anonymous")
        return {"token": token, "expires_in": 86400}

    if not verify_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    from .auth import create_token
    token = create_token(req.username)
    return {"token": token, "expires_in": 86400}


@admin_router.get("/auth/status")
async def auth_status():
    return {"enabled": is_auth_enabled()}


# --- Config Read Endpoints ---


@admin_router.get("/config")
async def get_config(_auth=Depends(require_auth)):
    env = _get_env_file()
    data = env.read()

    models_list = _parse_models(data)
    api_keys = _parse_api_keys(data)
    settings = _parse_settings(data)

    return {
        "models": models_list,
        "api_keys": api_keys,
        "settings": settings,
    }


@admin_router.get("/models")
async def get_models(_auth=Depends(require_auth)):
    env = _get_env_file()
    data = env.read()
    return {"models": _parse_models(data)}


@admin_router.get("/keys/{provider}")
async def get_keys(provider: str, _auth=Depends(require_auth)):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    env = _get_env_file()
    data = env.read()
    keys = _parse_api_keys(data).get(provider, [])
    return {"provider": provider, "keys": keys}


# --- Model CRUD Endpoints ---


@admin_router.post("/models", status_code=201)
async def create_model(req: ModelCreateRequest, _auth=Depends(require_auth)):
    key = req.key.upper().strip()
    if not re.match(r"^[A-Z0-9_]+$", key):
        raise HTTPException(status_code=400, detail="Model key must be alphanumeric/underscore")

    if not req.upstream_model.strip():
        raise HTTPException(status_code=400, detail="upstream_model is required")

    env = _get_env_file()
    existing = env.get(f"MODEL_{key}_UPSTREAM_MODEL")
    if existing:
        raise HTTPException(status_code=409, detail=f"Model key {key} already exists")

    # Detect provider
    from src.config.models import detect_provider
    provider = req.provider or detect_provider(req.upstream_model)

    items: Dict[str, str] = {
        f"MODEL_{key}_UPSTREAM_MODEL": req.upstream_model.strip(),
    }
    if req.reasoning_effort:
        items[f"MODEL_{key}_REASONING_EFFORT"] = req.reasoning_effort
    if req.upstream_base:
        items[f"MODEL_{key}_UPSTREAM_BASE"] = req.upstream_base
    if req.provider:
        items[f"MODEL_{key}_PROVIDER"] = req.provider

    env.set_many(items)

    # Update os.environ so hot reload can see the changes
    for k, v in items.items():
        os.environ[k] = v

    # Hot reload: add model to running LiteLLM
    _hot_add_model(key, req.upstream_model, provider, req.reasoning_effort)

    from src.config.models import derive_alias
    return {
        "message": "Model added",
        "model": {
            "key": key,
            "upstream_model": req.upstream_model,
            "alias": derive_alias(req.upstream_model),
            "provider": provider,
            "reasoning_effort": req.reasoning_effort,
        },
    }


@admin_router.put("/models/{key}")
async def update_model(key: str, req: ModelUpdateRequest, _auth=Depends(require_auth)):
    key = key.upper().strip()
    env = _get_env_file()
    existing = env.get(f"MODEL_{key}_UPSTREAM_MODEL")
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model key {key} not found")

    old_model_name = existing

    items: Dict[str, str] = {}
    keys_to_delete: List[str] = []
    if req.upstream_model:
        items[f"MODEL_{key}_UPSTREAM_MODEL"] = req.upstream_model
    if req.reasoning_effort is not None:
        if req.reasoning_effort:
            items[f"MODEL_{key}_REASONING_EFFORT"] = req.reasoning_effort
        else:
            keys_to_delete.append(f"MODEL_{key}_REASONING_EFFORT")
    if req.upstream_base is not None:
        if req.upstream_base:
            items[f"MODEL_{key}_UPSTREAM_BASE"] = req.upstream_base
        else:
            keys_to_delete.append(f"MODEL_{key}_UPSTREAM_BASE")
    if req.provider is not None:
        items[f"MODEL_{key}_PROVIDER"] = req.provider

    changed = bool(items or keys_to_delete)

    if items:
        env.set_many(items)
        for k, v in items.items():
            os.environ[k] = v

    for k in keys_to_delete:
        env.delete_key(k)
        os.environ.pop(k, None)

    if not changed:
        return {"message": "No changes", "key": key}

    # Hot reload: delete old, add new
    from src.config.models import derive_alias
    old_alias = derive_alias(old_model_name)
    delete_model_by_name(old_alias)

    new_model = req.upstream_model or existing
    from src.config.models import detect_provider
    provider = req.provider or detect_provider(new_model)
    _hot_add_model(key, new_model, provider, req.reasoning_effort)

    return {"message": "Model updated", "key": key}


@admin_router.delete("/models/{key}")
async def delete_model(key: str, _auth=Depends(require_auth)):
    key = key.upper().strip()
    env = _get_env_file()
    existing = env.get(f"MODEL_{key}_UPSTREAM_MODEL")
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model key {key} not found")

    from src.config.models import derive_alias
    alias = derive_alias(existing)

    # Delete all MODEL_<KEY>_* entries from .env
    env.delete(f"MODEL_{key}_")

    # Clean os.environ
    prefix = f"MODEL_{key}_"
    for k in list(os.environ.keys()):
        if k.upper().startswith(prefix):
            os.environ.pop(k, None)

    # Hot reload: remove from running LiteLLM
    delete_model_by_name(alias)

    return {"message": "Model removed", "key": key, "alias": alias}


# --- API Key Management Endpoints ---


@admin_router.put("/keys/{provider}")
async def update_keys(provider: str, req: KeysUpdateRequest, _auth=Depends(require_auth)):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    env_var = f"{provider.upper()}_API_KEYS"
    value = ",".join(req.keys)

    env = _get_env_file()
    env.set(env_var, value)
    os.environ[env_var] = value

    # Full hot reload needed when keys change
    result = _do_full_hot_reload()

    return {
        "message": "Keys updated",
        "count": len(req.keys),
        "reload": result,
    }


@admin_router.post("/keys/{provider}")
async def add_key(provider: str, req: KeyAddRequest, _auth=Depends(require_auth)):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    env_var = f"{provider.upper()}_API_KEYS"
    env = _get_env_file()
    current = env.get(env_var) or ""
    from src.config.rendering import parse_api_keys
    keys = parse_api_keys(current)
    keys.append(req.key)

    value = ",".join(keys)
    env.set(env_var, value)
    os.environ[env_var] = value

    result = _do_full_hot_reload()

    return {"message": "Key added", "count": len(keys), "reload": result}


@admin_router.delete("/keys/{provider}/{index}")
async def remove_key(provider: str, index: int, _auth=Depends(require_auth)):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    env_var = f"{provider.upper()}_API_KEYS"
    env = _get_env_file()
    current = env.get(env_var) or ""
    from src.config.rendering import parse_api_keys
    keys = parse_api_keys(current)

    if index < 0 or index >= len(keys):
        raise HTTPException(status_code=400, detail=f"Index {index} out of range (0-{len(keys)-1})")

    removed = keys.pop(index)
    value = ",".join(keys)
    env.set(env_var, value)
    os.environ[env_var] = value

    result = _do_full_hot_reload()

    return {"message": "Key removed", "removed_key": _mask_key(removed), "count": len(keys), "reload": result}


# --- System Endpoints ---


@admin_router.post("/reload")
async def reload_config(_auth=Depends(require_auth)):
    result = _do_full_hot_reload()
    return {"message": "Configuration reloaded", **result}


@admin_router.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# --- Helper Functions ---


def _parse_models(data: Dict[str, str]) -> List[Dict[str, Any]]:
    """Parse model entries from env data."""
    from src.config.models import detect_provider

    pattern = re.compile(r"^MODEL_([A-Z0-9_]+)_UPSTREAM_MODEL$")
    models: List[Dict[str, Any]] = []

    for key, value in sorted(data.items()):
        m = pattern.match(key)
        if m:
            model_key = m.group(1)
            provider = data.get(f"MODEL_{model_key}_PROVIDER") or detect_provider(value)
            models.append({
                "key": model_key,
                "upstream_model": value,
                "provider": provider,
                "reasoning_effort": data.get(f"MODEL_{model_key}_REASONING_EFFORT"),
                "upstream_base": data.get(f"MODEL_{model_key}_UPSTREAM_BASE"),
                "api_key": _mask_key(data.get(f"MODEL_{model_key}_API_KEY", "")),
            })

    return models


def _parse_api_keys(data: Dict[str, str]) -> Dict[str, List[str]]:
    """Parse API keys from env data."""
    from src.config.rendering import parse_api_keys

    result: Dict[str, List[str]] = {}
    for provider in ("openai", "anthropic"):
        keys_str = data.get(f"{provider.upper()}_API_KEYS", "")
        keys = parse_api_keys(keys_str)
        if not keys:
            single_key = data.get(f"{provider.upper()}_API_KEY", "")
            if single_key:
                keys = [single_key]
        result[provider] = [_mask_key(k) for k in keys]

    return result


def _parse_settings(data: Dict[str, str]) -> Dict[str, str]:
    """Parse general settings from env data."""
    settings_keys = [
        "PORT", "LITELLM_MASTER_KEY", "OPENAI_BASE_URL",
        "STREAMING_ENABLE", "TELEMETRY_ENABLE",
        "NODE_UPSTREAM_PROXY_ENABLE", "REASONING_EFFORT",
        "MAX_TOKENS",
    ]
    result: Dict[str, str] = {}
    for k in settings_keys:
        if k in data:
            if "KEY" in k:
                result[k] = _mask_key(data[k])
            else:
                result[k] = data[k]
    return result


def _mask_key(key: str) -> str:
    """Mask API key for display, showing first 4 and last 4 chars."""
    if not key or len(key) <= 12:
        return "***" if key else ""
    return f"{key[:4]}...{key[-4:]}"


def _hot_add_model(
    key: str,
    upstream_model: str,
    provider: str,
    reasoning_effort: Optional[str],
) -> None:
    """Add a model to running LiteLLM via management API."""
    from src.config.models import derive_alias

    alias = derive_alias(upstream_model)
    api_base = _get_api_base(provider)
    api_key = _get_provider_key(provider)

    if not api_key:
        return

    entry = build_model_entry(
        model_name=alias,
        provider=provider,
        api_base=api_base,
        api_key=api_key,
        upstream_model=upstream_model,
        reasoning_effort=reasoning_effort,
    )
    add_model_entry(alias, entry.get("litellm_params", {}))


def _get_api_base(provider: str) -> str:
    """Get the API base URL for a provider."""
    if provider == "anthropic":
        return os.getenv("ANTHROPIC_BASE_URL", "https://agentrouter.org")
    return os.getenv("OPENAI_BASE_URL", "https://agentrouter.org/v1")


def _get_provider_key(provider: str) -> str:
    """Get the first available API key for a provider."""
    env = _get_env_file()
    data = env.read()
    from src.config.rendering import parse_api_keys

    keys_str = data.get(f"{provider.upper()}_API_KEYS", "")
    keys = parse_api_keys(keys_str)
    if keys:
        return keys[0]

    return data.get(f"{provider.upper()}_API_KEY", "")


def _do_full_hot_reload() -> Dict[str, Any]:
    """Perform a full hot reload from .env state."""
    env = _get_env_file()
    data = env.read()

    from src.config.rendering import parse_api_keys
    from src.config.models import detect_provider, derive_alias, PROVIDER_ANTHROPIC

    # Collect provider keys
    provider_keys: Dict[str, List[str]] = {}
    for provider in ("openai", "anthropic"):
        keys_str = data.get(f"{provider.upper()}_API_KEYS", "")
        keys = parse_api_keys(keys_str)
        if not keys:
            single = data.get(f"{provider.upper()}_API_KEY", "")
            if single:
                keys = [single]
        if keys:
            provider_keys[provider] = keys

    # Build model entries
    pattern = re.compile(r"^MODEL_([A-Z0-9_]+)_UPSTREAM_MODEL$")
    entries: List[Dict[str, Any]] = []

    for key, value in sorted(data.items()):
        m = pattern.match(key)
        if not m:
            continue
        model_key = m.group(1)
        provider = data.get(f"MODEL_{model_key}_PROVIDER") or detect_provider(value)
        reasoning = data.get(f"MODEL_{model_key}_REASONING_EFFORT")
        alias = derive_alias(value)
        api_base = _get_api_base(provider)
        keys = provider_keys.get(provider, [])

        if len(keys) > 1:
            for k in keys:
                entry = build_model_entry(alias, provider, api_base, k, value, reasoning)
                entries.append(entry)
        elif keys:
            entry = build_model_entry(alias, provider, api_base, keys[0], value, reasoning)
            entries.append(entry)

    return do_full_reload(entries)
