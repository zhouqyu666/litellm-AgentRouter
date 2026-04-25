#!/usr/bin/env python3
"""
JWT authentication for admin management panel.
Uses python-jose (transitive dependency of litellm) for JWT.
Falls back to HMAC-based tokens if jose is not available.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import base64
from typing import Any, Dict, Optional


def _get_jwt_secret() -> str:
    """Get JWT secret from env, defaulting to LITELLM_MASTER_KEY."""
    secret = os.getenv("ADMIN_JWT_SECRET") or os.getenv("LITELLM_MASTER_KEY")
    if not secret:
        raise ValueError(
            "ADMIN_JWT_SECRET or LITELLM_MASTER_KEY must be set for admin authentication"
        )
    return secret


def is_auth_enabled() -> bool:
    """Return True if both ADMIN_USERNAME and ADMIN_PASSWORD are set."""
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "").strip()
    return bool(username and password)


def get_admin_credentials() -> tuple:
    """Return (username, password) from env."""
    return (
        os.getenv("ADMIN_USERNAME", "").strip(),
        os.getenv("ADMIN_PASSWORD", "").strip(),
    )


def _hash_password(password: str) -> str:
    """Hash password using SHA-256."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_credentials(username: str, password: str) -> bool:
    """Verify username and password against env configuration."""
    if not is_auth_enabled():
        return True
    expected_user, expected_pass = get_admin_credentials()
    return (
        username == expected_user
        and hmac.compare_digest(
            _hash_password(password), _hash_password(expected_pass)
        )
    )


def create_token(username: str, expires_hours: int = 24) -> str:
    """Create an authentication token."""
    secret = _get_jwt_secret()
    payload = {
        "sub": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_hours * 3600,
    }

    try:
        from jose import jwt
        return jwt.encode(payload, secret, algorithm="HS256")
    except ImportError:
        return _create_hmac_token(payload, secret)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a token. Returns payload or None."""
    secret = _get_jwt_secret()

    try:
        from jose import jwt, JWTError
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"])
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except JWTError:
            return None
    except ImportError:
        return _verify_hmac_token(token, secret)


def _create_hmac_token(payload: Dict, secret: str) -> str:
    """Create HMAC-based token as fallback when jose is not available."""
    payload_json = json.dumps(payload, sort_keys=True)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode()
    signature = hmac.new(
        secret.encode(), payload_b64.encode(), hashlib.sha256
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def _verify_hmac_token(token: str, secret: str) -> Optional[Dict[str, Any]]:
    """Verify HMAC-based token."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, signature = parts
        expected_sig = hmac.new(
            secret.encode(), payload_b64.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected_sig):
            return None
        payload_json = base64.urlsafe_b64decode(payload_b64).decode()
        payload = json.loads(payload_json)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None
