"""Tests for admin telemetry routes."""

from __future__ import annotations

import os

import pytest

from src.admin.env_manager import EnvFile
from src.middleware.telemetry.store import telemetry_store

os.environ.setdefault("LITELLM_MASTER_KEY", "sk-test-master")


@pytest.fixture
def client(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.admin.routes import admin_router, set_env_file

    env_path = tmp_path / ".env"
    env_path.write_text("LITELLM_MASTER_KEY=sk-test-master\n")

    app = FastAPI()
    app.include_router(admin_router)
    set_env_file(EnvFile(str(env_path)))
    telemetry_store.clear()

    test_client = TestClient(app)
    login_response = test_client.post(
        "/admin/api/login",
        json={"username": "admin", "password": "changeme"},
    )
    token = login_response.json()["token"]
    test_client.headers.update({"Authorization": f"Bearer {token}"})
    yield test_client

    telemetry_store.clear()
    set_env_file(None)


@pytest.fixture(autouse=True)
def clean_auth(monkeypatch):
    for key in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "ADMIN_JWT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-test-master")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "changeme")


def test_get_telemetry_requests(client):
    telemetry_store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "Fri, 19 Jun 2026 12:00:00 +0800",
        "status_code": 200,
        "model_alias": "deepseek-v3.2",
        "upstream_model": "openai/deepseek-v3.2",
        "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
    })

    response = client.get("/admin/api/telemetry/requests")

    assert response.status_code == 200
    payload = response.json()
    assert payload["requests"][0]["model_alias"] == "deepseek-v3.2"
    assert payload["requests"][0]["usage"]["total_tokens"] == 7


def test_get_telemetry_summary(client):
    telemetry_store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "Fri, 19 Jun 2026 12:00:00 +0800",
        "status_code": 200,
        "model_alias": "glm-5.1",
        "upstream_model": "openai/glm-5.1",
        "usage": {"prompt_tokens": 6, "completion_tokens": 8, "total_tokens": 14},
    })

    response = client.get("/admin/api/telemetry/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["total_requests"] == 1
    assert payload["summary"]["models"][0]["model_alias"] == "glm-5.1"
