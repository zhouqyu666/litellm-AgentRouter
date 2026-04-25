"""Tests for admin auth module."""

import os
import time

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Clean admin env vars before each test."""
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET", "LITELLM_MASTER_KEY"):
        monkeypatch.delenv(k, raising=False)


class TestIsAuthEnabled:
    def test_enabled_when_both_set(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "admin")
        monkeypatch.setenv("ADMIN_PASSWORD", "pass")
        from src.admin.auth import is_auth_enabled
        assert is_auth_enabled() is True

    def test_disabled_when_no_username(self, monkeypatch):
        monkeypatch.setenv("ADMIN_PASSWORD", "pass")
        from src.admin.auth import is_auth_enabled
        assert is_auth_enabled() is False

    def test_disabled_when_no_password(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "admin")
        from src.admin.auth import is_auth_enabled
        assert is_auth_enabled() is False

    def test_disabled_when_empty(self):
        from src.admin.auth import is_auth_enabled
        assert is_auth_enabled() is False


class TestVerifyCredentials:
    def test_correct_credentials(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "admin")
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        from src.admin.auth import verify_credentials
        assert verify_credentials("admin", "secret") is True

    def test_wrong_username(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "admin")
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        from src.admin.auth import verify_credentials
        assert verify_credentials("wrong", "secret") is False

    def test_wrong_password(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USERNAME", "admin")
        monkeypatch.setenv("ADMIN_PASSWORD", "secret")
        from src.admin.auth import verify_credentials
        assert verify_credentials("admin", "wrong") is False

    def test_no_auth_always_true(self):
        from src.admin.auth import verify_credentials
        assert verify_credentials("any", "any") is True


class TestTokenRoundTrip:
    def test_create_and_verify_token(self, monkeypatch):
        monkeypatch.setenv("ADMIN_JWT_SECRET", "test-secret")
        from src.admin.auth import create_token, verify_token
        token = create_token("admin")
        payload = verify_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"

    def test_expired_token_returns_none(self, monkeypatch):
        monkeypatch.setenv("ADMIN_JWT_SECRET", "test-secret")
        from src.admin.auth import create_token, verify_token
        token = create_token("admin", expires_hours=-1)
        assert verify_token(token) is None

    def test_invalid_token_returns_none(self, monkeypatch):
        monkeypatch.setenv("ADMIN_JWT_SECRET", "test-secret")
        from src.admin.auth import verify_token
        assert verify_token("invalid.token.here") is None

    def test_wrong_secret_returns_none(self, monkeypatch):
        monkeypatch.setenv("ADMIN_JWT_SECRET", "secret-a")
        from src.admin.auth import create_token
        token = create_token("admin")
        monkeypatch.setenv("ADMIN_JWT_SECRET", "secret-b")
        from src.admin.auth import verify_token
        assert verify_token(token) is None

    def test_defaults_to_master_key(self, monkeypatch):
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-master-key")
        from src.admin.auth import create_token, verify_token
        token = create_token("admin")
        assert verify_token(token) is not None

    def test_no_secret_raises_error(self):
        from src.admin.auth import _get_jwt_secret
        with pytest.raises(ValueError, match="ADMIN_JWT_SECRET"):
            _get_jwt_secret()
