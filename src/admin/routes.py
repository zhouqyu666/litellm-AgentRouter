#!/usr/bin/env python3
"""
Admin API routes for AgentRouter management panel.

Data is persisted to SQLite via ConfigStore for models, API keys, and
admin credentials.  Basic infrastructure settings (PORT, base URLs,
feature toggles) remain in .env for container-level configuration.
"""

from __future__ import annotations

import os
import re
import socket
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from .auth import is_auth_enabled, verify_credentials, verify_token
from .config_store import get_config_store
from .env_manager import EnvFile
from .hotreload import (
    add_model_entry,
    build_model_entry,
    delete_model_by_name,
    full_reload as do_full_reload,
)
from src.config.config import runtime_config

admin_router = APIRouter(prefix="/admin/api", tags=["admin"])
security = HTTPBearer(auto_error=False)

_env_file: Optional[EnvFile] = None


def _get_env_file() -> EnvFile:
    """Get or create the EnvFile singleton (for reading basic settings)."""
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


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str


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


class MasterKeyUpdateRequest(BaseModel):
    master_key: str


class UpstreamProxyUpdateRequest(BaseModel):
    proxy_url: str


# ---------------------------------------------------------------------------
# Helpers — sync DB → os.environ so hot-reload & downstream code see changes
# ---------------------------------------------------------------------------


def _sync_db_to_environ() -> None:
    """Push models and keys from DB into os.environ."""
    from src.config.parsing import sync_db_to_environ as do_sync
    do_sync()


def _schedule_full_hot_reload(background_tasks: BackgroundTasks) -> None:
    """Schedule a full LiteLLM hot reload after the response is sent."""
    background_tasks.add_task(_do_full_hot_reload)


def _store():
    """Return the active configuration store."""
    return get_config_store()


# --- Auth Endpoints ---


@admin_router.post("/login")
async def login(req: LoginRequest):
    if not is_auth_enabled():
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


@admin_router.put("/auth/password")
async def change_password(req: PasswordChangeRequest, _auth=Depends(require_auth)):
    from .auth import get_admin_credentials

    username, _password = get_admin_credentials()
    if not verify_credentials(username, req.old_password):
        raise HTTPException(status_code=401, detail="Old password is incorrect")

    new_password = req.new_password.strip()
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    _store().set_setting("ADMIN_PASSWORD", new_password)
    os.environ["ADMIN_PASSWORD"] = new_password

    return {"message": "Password updated"}


# --- Config Read Endpoints ---


@admin_router.get("/config")
async def get_config(_auth=Depends(require_auth)):
    models_list = _parse_models()
    api_keys = _parse_api_keys()
    settings = _parse_settings()

    return {
        "models": models_list,
        "api_keys": api_keys,
        "settings": settings,
    }


@admin_router.get("/models")
async def get_models(_auth=Depends(require_auth)):
    return {"models": _parse_models()}


@admin_router.get("/keys/{provider}")
async def get_keys(provider: str, _auth=Depends(require_auth)):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    keys = _store().get_api_keys(provider)
    return {"provider": provider, "keys": [_mask_key(k) for k in keys]}


# --- Telemetry Endpoints ---


@admin_router.get("/telemetry/requests")
async def get_telemetry_requests(limit: int = 100, _auth=Depends(require_auth)):
    from src.middleware.telemetry.store import telemetry_store

    safe_limit = max(1, min(limit, 1000))
    return {"requests": telemetry_store.list_requests(limit=safe_limit)}


@admin_router.get("/telemetry/summary")
async def get_telemetry_summary(_auth=Depends(require_auth)):
    from src.middleware.telemetry.store import telemetry_store

    return {"summary": telemetry_store.summary()}


# --- Model CRUD Endpoints ---


@admin_router.post("/models", status_code=201)
async def create_model(req: ModelCreateRequest, _auth=Depends(require_auth)):
    key = req.key.upper().strip()
    if not re.match(r"^[A-Z0-9_]+$", key):
        raise HTTPException(
            status_code=400,
            detail=(
                "模型 Key 只能使用英文字母、数字、下划线，例如 GPT5_4；"
                "API Key 请在 API Key 管理里添加。"
            ),
        )

    if not req.upstream_model.strip():
        raise HTTPException(status_code=400, detail="upstream_model is required")

    existing = _store().get_model(key)
    if existing:
        raise HTTPException(status_code=409, detail=f"Model key {key} already exists")

    from src.config.models import detect_provider
    provider = req.provider or detect_provider(req.upstream_model)

    _store().save_model(
        key=key,
        upstream_model=req.upstream_model.strip(),
        upstream_base=req.upstream_base,
        provider=req.provider,
        reasoning_effort=req.reasoning_effort,
    )

    _sync_db_to_environ()
    await run_in_threadpool(
        _hot_add_model,
        key,
        req.upstream_model,
        provider,
        req.reasoning_effort,
    )

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
    existing = _store().get_model(key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model key {key} not found")

    old_model_name = existing["upstream_model"]

    new_upstream = req.upstream_model or existing["upstream_model"]
    new_provider = req.provider or existing.get("provider")

    new_reasoning = req.reasoning_effort
    if new_reasoning is None:
        new_reasoning = existing.get("reasoning_effort")
    elif new_reasoning == "":
        new_reasoning = None

    new_base = req.upstream_base
    if new_base is None:
        new_base = existing.get("upstream_base")
    elif new_base == "":
        new_base = None

    _store().save_model(
        key=key,
        upstream_model=new_upstream,
        upstream_base=new_base,
        provider=new_provider,
        reasoning_effort=new_reasoning,
    )

    _sync_db_to_environ()

    from src.config.models import derive_alias, detect_provider
    old_alias = derive_alias(old_model_name)
    await run_in_threadpool(delete_model_by_name, old_alias)

    provider = new_provider or detect_provider(new_upstream)
    await run_in_threadpool(_hot_add_model, key, new_upstream, provider, new_reasoning)

    return {"message": "Model updated", "key": key}


@admin_router.delete("/models/{key}")
async def delete_model(key: str, _auth=Depends(require_auth)):
    key = key.upper().strip()
    existing = _store().get_model(key)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Model key {key} not found")

    from src.config.models import derive_alias
    alias = derive_alias(existing["upstream_model"])

    _store().delete_model(key)
    _sync_db_to_environ()
    await run_in_threadpool(delete_model_by_name, alias)

    return {"message": "Model removed", "key": key, "alias": alias}


# --- API Key Management Endpoints ---


@admin_router.put("/keys/{provider}")
async def update_keys(
    provider: str,
    req: KeysUpdateRequest,
    background_tasks: BackgroundTasks,
    _auth=Depends(require_auth),
):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    _store().set_api_keys(provider, req.keys)
    _sync_db_to_environ()
    _schedule_full_hot_reload(background_tasks)

    return {"message": "Keys updated", "count": len(req.keys), "reload": {"scheduled": True}}


@admin_router.post("/keys/{provider}")
async def add_key(
    provider: str,
    req: KeyAddRequest,
    background_tasks: BackgroundTasks,
    _auth=Depends(require_auth),
):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    count = _store().add_api_key(provider, req.key)
    _sync_db_to_environ()
    _schedule_full_hot_reload(background_tasks)

    return {"message": "Key added", "count": count, "reload": {"scheduled": True}}


@admin_router.delete("/keys/{provider}/{index}")
async def remove_key(
    provider: str,
    index: int,
    background_tasks: BackgroundTasks,
    _auth=Depends(require_auth),
):
    provider = provider.lower()
    if provider not in ("openai", "anthropic"):
        raise HTTPException(status_code=400, detail="Provider must be 'openai' or 'anthropic'")

    keys = _store().get_api_keys(provider)
    if index < 0 or index >= len(keys):
        raise HTTPException(status_code=400, detail=f"Index {index} out of range (0-{len(keys)-1})")

    removed = _store().remove_api_key(provider, index)
    _sync_db_to_environ()
    _schedule_full_hot_reload(background_tasks)

    return {
        "message": "Key removed",
        "removed_key": _mask_key(removed or ""),
        "count": len(keys) - 1,
        "reload": {"scheduled": True},
    }


# --- Settings Management Endpoints ---


@admin_router.put("/settings/master-key")
async def update_master_key(
    req: MasterKeyUpdateRequest,
    _auth=Depends(require_auth),
):
    master_key = req.master_key.strip()
    if len(master_key) < 8:
        raise HTTPException(status_code=400, detail="Master Key must be at least 8 characters")

    _store().set_setting("LITELLM_MASTER_KEY", master_key)

    return {
        "message": "Master Key saved",
        "requires_restart": True,
        "setting": {
            "key": "LITELLM_MASTER_KEY",
            "value": _mask_key(master_key),
        },
    }


@admin_router.put("/settings/upstream-proxy")
async def update_upstream_proxy(
    req: UpstreamProxyUpdateRequest,
    _auth=Depends(require_auth),
):
    proxy_url = req.proxy_url.strip()
    if proxy_url:
        if not re.match(r"^(https?|socks4a?|socks5h?|socks)://", proxy_url, re.IGNORECASE):
            raise HTTPException(
                status_code=400,
                detail="Proxy URL must start with http://, https://, socks://, socks4://, or socks5://",
            )
        _store().set_setting("UPSTREAM_PROXY_URL", proxy_url)
    else:
        _store().delete_setting("UPSTREAM_PROXY_URL")

    os.environ["UPSTREAM_PROXY_URL"] = proxy_url
    from .node_proxy import sync_upstream_proxy
    node_result = sync_upstream_proxy(proxy_url)

    return {
        "message": "Upstream proxy saved",
        "requires_restart": False,
        "node_proxy": node_result,
        "setting": {
            "key": "UPSTREAM_PROXY_URL",
            "value": _mask_proxy_url(proxy_url) if proxy_url else "",
        },
    }


# --- System Endpoints ---


@admin_router.post("/reload")
async def reload_config(_auth=Depends(require_auth)):
    result = await run_in_threadpool(_do_full_hot_reload)
    return {"message": "Configuration reloaded", **result}


@admin_router.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _parse_models() -> List[Dict[str, Any]]:
    """Parse model entries from ConfigStore."""
    from src.config.models import detect_provider

    models: List[Dict[str, Any]] = []
    for m in _store().get_all_models():
        provider = m.get("provider") or detect_provider(m["upstream_model"])
        models.append({
            "key": m["key"],
            "upstream_model": m["upstream_model"],
            "provider": provider,
            "reasoning_effort": m.get("reasoning_effort"),
            "upstream_base": m.get("upstream_base"),
            "api_key": None,
        })
    return models


def _parse_api_keys() -> Dict[str, List[str]]:
    """Parse API keys from ConfigStore."""
    result: Dict[str, List[str]] = {}
    for provider in ("openai", "anthropic"):
        keys = _store().get_api_keys(provider)
        result[provider] = [_mask_key(k) for k in keys]
    return result


def _parse_settings() -> Dict[str, str]:
    """Parse general settings from .env and ConfigStore."""
    env = _get_env_file()
    data = env.read()

    result: Dict[str, str] = {}
    for k in (
        "PORT", "LITELLM_MASTER_KEY", "OPENAI_BASE_URL",
        "STREAMING_ENABLE", "TELEMETRY_ENABLE",
        "NODE_UPSTREAM_PROXY_ENABLE", "REASONING_EFFORT",
        "MAX_TOKENS", "UPSTREAM_PROXY_URL",
    ):
        if k in data:
            if "KEY" in k:
                result[k] = _mask_key(data[k])
            else:
                result[k] = data[k]

    # Admin-managed settings from ConfigStore (fall back to .env).
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "LITELLM_MASTER_KEY", "UPSTREAM_PROXY_URL"):
        val = _store().get_setting(k) or data.get(k, "")
        if val:
            if k == "UPSTREAM_PROXY_URL":
                result[k] = _mask_proxy_url(val)
            else:
                result[k] = _mask_key(val) if "PASSWORD" in k or "KEY" in k else val

    return result


def _mask_proxy_url(proxy_url: str) -> str:
    """Mask userinfo in a proxy URL for display."""
    if not proxy_url:
        return ""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(proxy_url)
        if "@" not in parts.netloc:
            return proxy_url
        host_part = parts.netloc.rsplit("@", 1)[1]
        return urlunsplit((parts.scheme, f"***:***@{host_part}", parts.path, parts.query, parts.fragment))
    except Exception:
        return "***"


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
    api_key = _get_first_provider_key(provider)

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
    node_proxy_base = _get_node_proxy_base()
    if node_proxy_base:
        if provider == "anthropic":
            return node_proxy_base
        return f"{node_proxy_base}/v1"

    if provider == "anthropic":
        return runtime_config.get_str("ANTHROPIC_BASE_URL", "https://agentrouter.org")
    return runtime_config.get_str("OPENAI_BASE_URL", "https://agentrouter.org/v1")


def _get_node_proxy_base() -> Optional[str]:
    """Return the Node proxy base URL used by admin hot reload."""
    runtime_config.ensure_loaded()
    if not runtime_config.get_bool("NODE_UPSTREAM_PROXY_ENABLE", True):
        return None

    explicit_base_url = runtime_config.get_str("ADMIN_NODE_PROXY_BASE_URL")
    if explicit_base_url:
        return _strip_v1_suffix(explicit_base_url)

    try:
        socket.gethostbyname("node-proxy")
        return "http://node-proxy:4000"
    except socket.gaierror:
        return "http://127.0.0.1:4000"


def _strip_v1_suffix(base_url: str) -> str:
    """Normalize a base URL to the Node proxy root."""
    normalized_base_url = base_url.rstrip("/")
    return normalized_base_url[:-3] if normalized_base_url.endswith("/v1") else normalized_base_url


def _get_first_provider_key(provider: str) -> str:
    """Get the first available API key for a provider from ConfigStore."""
    keys = _store().get_api_keys(provider)
    return keys[0] if keys else os.getenv(f"{provider.upper()}_API_KEY", "")


def _do_full_hot_reload() -> Dict[str, Any]:
    """Perform a full hot reload from ConfigStore state."""
    from src.config.models import detect_provider, derive_alias

    provider_keys: Dict[str, List[str]] = {}
    for provider in ("openai", "anthropic"):
        keys = _store().get_api_keys(provider)
        if keys:
            provider_keys[provider] = keys

    entries: List[Dict[str, Any]] = []
    for m in _store().get_all_models():
        alias = derive_alias(m["upstream_model"])
        provider = m.get("provider") or detect_provider(m["upstream_model"])
        api_base = _get_api_base(provider)
        reasoning = m.get("reasoning_effort")
        keys = provider_keys.get(provider, [])

        if len(keys) > 1:
            for k in keys:
                entry = build_model_entry(alias, provider, api_base, k, m["upstream_model"], reasoning)
                entries.append(entry)
        elif keys:
            entry = build_model_entry(alias, provider, api_base, keys[0], m["upstream_model"], reasoning)
            entries.append(entry)

    return do_full_reload(entries)
