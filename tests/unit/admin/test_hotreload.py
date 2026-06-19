"""Tests for LiteLLM admin hot reload helpers."""

from __future__ import annotations

from src.admin.hotreload import _get_proxy_base_url


def test_proxy_base_url_defaults_to_port_env(monkeypatch):
    monkeypatch.delenv("ADMIN_PROXY_BASE_URL", raising=False)
    monkeypatch.setenv("PORT", "8000")

    assert _get_proxy_base_url() == "http://127.0.0.1:8000"


def test_proxy_base_url_can_be_overridden(monkeypatch):
    monkeypatch.setenv("ADMIN_PROXY_BASE_URL", "http://127.0.0.1:9000")
    monkeypatch.setenv("PORT", "8000")

    assert _get_proxy_base_url() == "http://127.0.0.1:9000"
