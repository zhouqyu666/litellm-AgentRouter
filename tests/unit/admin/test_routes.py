"""Tests for admin API routes."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.admin.env_manager import EnvFile
from src.admin.config_store import ConfigStore
from src.admin.config_store import set_config_store

# We need to set env before importing routes
os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test-master")


@pytest.fixture
def env_file(tmp_path):
    """Create a temp .env file for testing."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "PORT=4000\n"
        "LITELLM_MASTER_KEY=sk-test-master\n"
        "MODEL_DEEPSEEK_UPSTREAM_MODEL=deepseek-v3.2\n"
        "MODEL_DEEPSEEK_REASONING_EFFORT=medium\n"
        "MODEL_GLM_UPSTREAM_MODEL=glm-4.6\n"
        "OPENAI_API_KEYS=sk-key1,sk-key2\n"
    )
    return env_path


@pytest.fixture
def client(env_file):
    """Create a test client with a temp .env file."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.admin.routes import admin_router, set_env_file
    from src.admin.env_manager import EnvFile

    store = ConfigStore(str(env_file.parent / "config.sqlite3"))
    store.migrate_from_env(EnvFile(str(env_file)).read())
    set_config_store(store)

    app = FastAPI()
    app.include_router(admin_router)
    set_env_file(EnvFile(str(env_file)))

    client = TestClient(app)
    login_response = client.post(
        "/admin/api/login",
        json={"username": "admin", "password": "changeme"},
    )
    token = login_response.json()["token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client

    set_env_file(None)
    set_config_store(ConfigStore(":memory:"))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-master")


class TestHealthEndpoint:
    def test_health_no_auth_required(self, client):
        resp = client.get("/admin/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestAuthEndpoint:
    def test_auth_status_enabled_by_default(self, client):
        resp = client.get("/admin/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_login_default_credentials(self, client):
        resp = client.post("/admin/api/login", json={"username": "admin", "password": "changeme"})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data

    def test_login_rejects_empty_credentials(self, client):
        client.headers.pop("Authorization", None)
        resp = client.post("/admin/api/login", json={"username": "", "password": ""})
        assert resp.status_code == 401

    def test_change_password_updates_sqlite(self, client, env_file):
        resp = client.put("/admin/api/auth/password", json={
            "old_password": "changeme",
            "new_password": "new-secret-123",
        })

        assert resp.status_code == 200
        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert ef.get("ADMIN_PASSWORD") is None
        assert get_config_store().get_setting("ADMIN_PASSWORD") == "new-secret-123"

    def test_change_password_rejects_wrong_old_password(self, client, env_file):
        resp = client.put("/admin/api/auth/password", json={
            "old_password": "wrong",
            "new_password": "new-secret-123",
        })

        assert resp.status_code == 401
        ef = EnvFile(str(env_file))
        assert ef.get("ADMIN_PASSWORD") is None

    def test_change_password_rejects_short_password(self, client):
        resp = client.put("/admin/api/auth/password", json={
            "old_password": "changeme",
            "new_password": "short",
        })

        assert resp.status_code == 400


class TestConfigEndpoint:
    def test_get_config(self, client):
        resp = client.get("/admin/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "models" in data
        assert "api_keys" in data
        assert "settings" in data

    def test_get_models(self, client):
        resp = client.get("/admin/api/models")
        assert resp.status_code == 200
        models = resp.json()["models"]
        assert len(models) == 2
        keys = [m["key"] for m in models]
        assert "DEEPSEEK" in keys
        assert "GLM" in keys

    def test_get_keys(self, client):
        resp = client.get("/admin/api/keys/openai")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "openai"
        assert len(data["keys"]) == 2

    def test_get_keys_invalid_provider(self, client):
        resp = client.get("/admin/api/keys/invalid")
        assert resp.status_code == 400


class TestSettingsManagement:
    def test_update_master_key_saves_sqlite_and_requires_restart(self, client, env_file):
        resp = client.put("/admin/api/settings/master-key", json={
            "master_key": "sk-zhouhuozhou",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_restart"] is True
        assert data["setting"]["key"] == "LITELLM_MASTER_KEY"
        assert data["setting"]["value"] == "sk-z...zhou"

        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert ef.get("LITELLM_MASTER_KEY") == "sk-test-master"
        assert get_config_store().get_setting("LITELLM_MASTER_KEY") == "sk-zhouhuozhou"

    def test_update_master_key_rejects_short_value(self, client):
        resp = client.put("/admin/api/settings/master-key", json={
            "master_key": "short",
        })

        assert resp.status_code == 400

    @patch("src.admin.node_proxy.urlopen")
    def test_update_upstream_proxy_saves_sqlite_and_syncs_node(self, mock_urlopen, client, env_file):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"upstream_proxy_enabled":true}'
        )

        resp = client.put("/admin/api/settings/upstream-proxy", json={
            "proxy_url": "socks5://user:pass@64.188.8.141:1186",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["requires_restart"] is False
        assert data["setting"]["key"] == "UPSTREAM_PROXY_URL"
        assert data["setting"]["value"] == "socks5://***:***@64.188.8.141:1186"

        from src.admin.config_store import get_config_store
        assert get_config_store().get_setting("UPSTREAM_PROXY_URL") == (
            "socks5://user:pass@64.188.8.141:1186"
        )
        assert mock_urlopen.called

    def test_update_upstream_proxy_rejects_invalid_scheme(self, client):
        resp = client.put("/admin/api/settings/upstream-proxy", json={
            "proxy_url": "ftp://proxy.example.com:21",
        })

        assert resp.status_code == 400


class TestModelCRUD:
    @patch("src.admin.routes.add_model_entry")
    def test_create_model(self, mock_add, client, env_file):
        mock_add.return_value = True
        resp = client.post("/admin/api/models", json={
            "key": "GPT5",
            "upstream_model": "gpt-5",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["model"]["key"] == "GPT5"

        # Verify SQLite was updated and .env remains infrastructure-only.
        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert ef.get("MODEL_GPT5_UPSTREAM_MODEL") is None
        assert get_config_store().get_model("GPT5")["upstream_model"] == "gpt-5"

    def test_create_model_duplicate_key(self, client):
        resp = client.post("/admin/api/models", json={
            "key": "DEEPSEEK",
            "upstream_model": "deepseek-v3.2",
        })
        assert resp.status_code == 409

    def test_create_model_invalid_key(self, client):
        resp = client.post("/admin/api/models", json={
            "key": "bad key!",
            "upstream_model": "model",
        })
        assert resp.status_code == 400
        assert "模型 Key" in resp.json()["detail"]

    @patch("src.admin.routes.delete_model_by_name")
    def test_delete_model(self, mock_delete, client, env_file):
        mock_delete.return_value = True
        resp = client.delete("/admin/api/models/DEEPSEEK")
        assert resp.status_code == 200

        # Verify SQLite was updated and .env remains unchanged.
        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert ef.get("MODEL_DEEPSEEK_UPSTREAM_MODEL") == "deepseek-v3.2"
        assert get_config_store().get_model("DEEPSEEK") is None

    def test_delete_nonexistent_model(self, client):
        resp = client.delete("/admin/api/models/NONEXISTENT")
        assert resp.status_code == 404

    @patch("src.admin.routes.delete_model_by_name")
    @patch("src.admin.routes.add_model_entry")
    def test_update_model(self, mock_add, mock_delete, client, env_file):
        mock_add.return_value = True
        mock_delete.return_value = True
        resp = client.put("/admin/api/models/DEEPSEEK", json={
            "reasoning_effort": "high",
        })
        assert resp.status_code == 200


class TestKeyManagement:
    @patch("src.admin.routes._schedule_full_hot_reload")
    def test_update_keys(self, mock_schedule, client, env_file):
        resp = client.put("/admin/api/keys/openai", json={
            "keys": ["sk-new1", "sk-new2"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["reload"] == {"scheduled": True}
        mock_schedule.assert_called_once()

        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert ef.get("OPENAI_API_KEYS") == "sk-key1,sk-key2"
        assert get_config_store().get_api_keys("openai") == ["sk-new1", "sk-new2"]

    @patch("src.admin.routes._schedule_full_hot_reload")
    def test_add_key(self, mock_schedule, client, env_file):
        resp = client.post("/admin/api/keys/openai", json={"key": "sk-new3"})
        assert resp.status_code == 200
        assert resp.json()["reload"] == {"scheduled": True}
        mock_schedule.assert_called_once()

        from src.admin.config_store import get_config_store
        ef = EnvFile(str(env_file))
        assert "sk-new3" not in ef.get("OPENAI_API_KEYS")
        assert "sk-new3" in get_config_store().get_api_keys("openai")

    @patch("src.admin.routes._schedule_full_hot_reload")
    def test_remove_key(self, mock_schedule, client, env_file):
        resp = client.delete("/admin/api/keys/openai/0")
        assert resp.status_code == 200
        assert resp.json()["reload"] == {"scheduled": True}
        mock_schedule.assert_called_once()

    def test_remove_key_invalid_index(self, client):
        resp = client.delete("/admin/api/keys/openai/99")
        assert resp.status_code == 400


class TestReloadEndpoint:
    @patch("src.admin.routes.do_full_reload")
    def test_reload(self, mock_reload, client):
        mock_reload.return_value = {"deleted": 2, "added": 2, "failed": 0}
        resp = client.post("/admin/api/reload")
        assert resp.status_code == 200
        data = resp.json()
        assert "deleted" in data
        assert "added" in data


class TestAdminHotReloadApiBase:
    @patch("src.admin.routes.socket.gethostbyname")
    def test_get_api_base_uses_docker_node_proxy_for_openai(self, mock_gethostbyname, monkeypatch):
        mock_gethostbyname.return_value = "172.18.0.2"
        monkeypatch.delenv("ADMIN_NODE_PROXY_BASE_URL", raising=False)
        monkeypatch.setenv("NODE_UPSTREAM_PROXY_ENABLE", "1")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://agentrouter.org/v1")

        from src.admin.routes import _get_api_base

        assert _get_api_base("openai") == "http://node-proxy:4000/v1"

    def test_get_api_base_prefers_admin_node_proxy_base(self, monkeypatch):
        monkeypatch.setenv("ADMIN_NODE_PROXY_BASE_URL", "http://node-proxy:4000/")
        monkeypatch.setenv("NODE_UPSTREAM_PROXY_ENABLE", "1")

        from src.admin.routes import _get_api_base

        assert _get_api_base("openai") == "http://node-proxy:4000/v1"
        assert _get_api_base("anthropic") == "http://node-proxy:4000"

    def test_get_api_base_uses_direct_upstream_when_node_proxy_disabled(self, monkeypatch):
        monkeypatch.setenv("NODE_UPSTREAM_PROXY_ENABLE", "0")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://direct.example/v1")

        from src.admin.routes import _get_api_base

        assert _get_api_base("openai") == "https://direct.example/v1"
