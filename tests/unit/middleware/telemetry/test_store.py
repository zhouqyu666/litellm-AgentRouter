#!/usr/bin/env python3
"""Tests for telemetry request store."""

from __future__ import annotations

from src.middleware.telemetry.store import TelemetryStore


def test_store_records_completed_request_and_summary():
    store = TelemetryStore(max_events=10, db_path=":memory:")

    store.record({
        "event_type": "RequestReceived",
        "timestamp": "Fri, 19 Jun 2026 12:00:00 +0800",
        "method": "POST",
        "path": "/v1/chat/completions",
        "model_alias": "gpt-5",
        "client_request_id": "req-1",
        "remote_addr": "127.0.0.1",
    })
    store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "Fri, 19 Jun 2026 12:00:01 +0800",
        "duration_s": 1.25,
        "status_code": 200,
        "model_alias": "gpt-5",
        "upstream_model": "openai/gpt-5",
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 20,
            "reasoning_tokens": 5,
        },
        "streaming": False,
        "client_request_id": "req-1",
        "remote_addr": "127.0.0.1",
    })

    requests = store.list_requests()
    assert len(requests) == 1
    assert requests[0]["model_alias"] == "gpt-5"
    assert requests[0]["usage"]["total_tokens"] == 20

    summary = store.summary()
    assert summary["total_requests"] == 1
    assert summary["total_tokens"] == 20
    assert summary["models"][0]["model_alias"] == "gpt-5"
    assert summary["models"][0]["request_count"] == 1
    assert summary["models"][0]["total_tokens"] == 20


def test_store_caps_request_history():
    store = TelemetryStore(max_events=1, db_path=":memory:")

    store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "one",
        "status_code": 200,
        "model_alias": "first",
        "usage": {"total_tokens": 1},
    })
    store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "two",
        "status_code": 200,
        "model_alias": "second",
        "usage": {"total_tokens": 2},
    })

    requests = store.list_requests()
    assert len(requests) == 1
    assert requests[0]["model_alias"] == "second"


def test_store_records_error_request_with_zero_usage():
    store = TelemetryStore(max_events=10, db_path=":memory:")

    store.record({
        "event_type": "ErrorRaised",
        "timestamp": "Fri, 19 Jun 2026 12:00:00 +0800",
        "status_code": 500,
        "model_alias": "gpt-5",
        "upstream_model": "openai/gpt-5",
        "error_type": "RuntimeError",
    })

    requests = store.list_requests()
    assert requests[0]["status_code"] == 500
    assert requests[0]["usage"]["total_tokens"] == 0

    summary = store.summary()
    assert summary["total_requests"] == 1
    assert summary["total_tokens"] == 0


def test_store_persists_requests_across_instances(tmp_path):
    db_path = tmp_path / "telemetry.sqlite3"
    first_store = TelemetryStore(max_events=10, db_path=str(db_path))
    first_store.record({
        "event_type": "ResponseCompleted",
        "timestamp": "Fri, 19 Jun 2026 12:00:00 +0800",
        "status_code": 200,
        "model_alias": "persisted-model",
        "upstream_model": "openai/persisted-model",
        "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
    })

    second_store = TelemetryStore(max_events=10, db_path=str(db_path))
    requests = second_store.list_requests()

    assert len(requests) == 1
    assert requests[0]["model_alias"] == "persisted-model"
    assert second_store.summary()["total_tokens"] == 5
