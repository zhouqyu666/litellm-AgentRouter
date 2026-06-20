"""Tests for Node proxy synchronization helpers."""

from urllib.error import URLError

from src.admin.node_proxy import get_node_proxy_base_url, sync_upstream_proxy


def test_get_node_proxy_base_url_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("ADMIN_NODE_PROXY_BASE_URL", "http://node-proxy:4000/")

    assert get_node_proxy_base_url("http://127.0.0.1:4000/v1") == "http://node-proxy:4000"


def test_get_node_proxy_base_url_strips_v1_suffix(monkeypatch):
    monkeypatch.delenv("ADMIN_NODE_PROXY_BASE_URL", raising=False)

    assert get_node_proxy_base_url("http://127.0.0.1:4000/v1") == "http://127.0.0.1:4000"


def test_sync_upstream_proxy_returns_error_without_raising(mocker):
    mocker.patch("src.admin.node_proxy.urlopen", side_effect=URLError("unavailable"))

    result = sync_upstream_proxy("socks5://user:pass@127.0.0.1:1080", "http://node-proxy:4000")

    assert "error" in result
