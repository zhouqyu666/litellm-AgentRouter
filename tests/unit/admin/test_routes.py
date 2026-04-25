"""Tests for admin API routes."""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.admin.env_manager import EnvFile

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

    app = FastAPI()
    app.include_router(admin_router)
    set_env_file(EnvFile(str(env_file)))

    client = TestClient(app)
    yield client

    set_env_file(None)


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
    def test_auth_status_disabled(self, client):
        resp = client.get("/admin/api/auth/status")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_login_no_auth(self, client):
        resp = client.post("/admin/api/login", json={"username": "", "password": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data


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

        # Verify .env was updated
        ef = EnvFile(str(env_file))
        assert ef.get("MODEL_GPT5_UPSTREAM_MODEL") == "gpt-5"

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

    @patch("src.admin.routes.delete_model_by_name")
    def test_delete_model(self, mock_delete, client, env_file):
        mock_delete.return_value = True
        resp = client.delete("/admin/api/models/DEEPSEEK")
        assert resp.status_code == 200

        # Verify .env was cleaned
        ef = EnvFile(str(env_file))
        assert ef.get("MODEL_DEEPSEEK_UPSTREAM_MODEL") is None
        assert ef.get("MODEL_DEEPSEEK_REASONING_EFFORT") is None

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
    @patch("src.admin.routes.do_full_reload")
    def test_update_keys(self, mock_reload, client, env_file):
        mock_reload.return_value = {"deleted": 0, "added": 2, "failed": 0}
        resp = client.put("/admin/api/keys/openai", json={
            "keys": ["sk-new1", "sk-new2"]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

        ef = EnvFile(str(env_file))
        assert ef.get("OPENAI_API_KEYS") == "sk-new1,sk-new2"

    @patch("src.admin.routes.do_full_reload")
    def test_add_key(self, mock_reload, client, env_file):
        mock_reload.return_value = {"deleted": 0, "added": 3, "failed": 0}
        resp = client.post("/admin/api/keys/openai", json={"key": "sk-new3"})
        assert resp.status_code == 200

        ef = EnvFile(str(env_file))
        keys = ef.get("OPENAI_API_KEYS")
        assert "sk-new3" in keys

    @patch("src.admin.routes.do_full_reload")
    def test_remove_key(self, mock_reload, client, env_file):
        mock_reload.return_value = {"deleted": 2, "added": 1, "failed": 0}
        resp = client.delete("/admin/api/keys/openai/0")
        assert resp.status_code == 200

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
