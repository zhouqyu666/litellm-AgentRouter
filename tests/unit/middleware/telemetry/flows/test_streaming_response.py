#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import Request, Response

from src.middleware.telemetry.middleware import TelemetryMiddleware
from src.middleware.telemetry.config import TelemetryConfig
from src.middleware.telemetry.sinks.inmemory import InMemorySink
from src.middleware.telemetry.request_context import NoOpReasoningPolicy


class EnabledToggle:
    def enabled(self, request):
        return True


class TestStreamingResponseFlow:
    """Test streaming response with replayable iterator and usage extraction."""

    def setup_method(self):
        self.log_records = []
        handler = logging.Handler()
        handler.setLevel(logging.DEBUG)
        handler.emit = lambda rec: self.log_records.append(rec)
        self.logger = logging.getLogger("litellm.telemetry")
        self.logger.addHandler(handler)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

        self.mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        self.in_memory = InMemorySink()
        self.config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        self.middleware = TelemetryMiddleware(self.mock_app, config=self.config)

    def teardown_method(self):
        if self.log_records:
            self.logger.removeHandler(self.log_records[0])

    def _make_request(self, method="POST", path="/v1/chat/completions", json_body=None):
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(json.dumps({}))).encode())],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "app": self.mock_app,
        }
        req = Request(scope)
        if json_body:
            async def receive():
                return {"type": "http.request", "body": json.dumps(json_body).encode(), "more_body": False}
            req._receive = receive
        return req

    async def _mock_streaming_response(self):
        """Create a mock streaming response with usage in last chunk."""
        chunks = [
            b'data: {"choices": [{"delta": {"content": "Hi"}}]\n\n',
            b'data: {"choices": [{"delta": {"content": " there"}}]\n\n',
            b'data: {"usage": {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40}}\n\n',
            b'data: [DONE]\n\n',
        ]

        async def body_iterator():
            for chunk in chunks:
                yield chunk

        resp = Response()
        resp.body_iterator = body_iterator()
        setattr(resp, "status_code", 200)
        return resp

    async def test_streaming_usage_extraction_and_replay(self):
        """Test streaming response with usage extraction from chunks."""
        request = self._make_request(json_body={"model": "test-model", "stream": True})
        mock_response = await self._mock_streaming_response()

        async def call_next(req):
            return mock_response

        with patch("time.perf_counter") as mock_time:
            mock_time.side_effect = [0.0, 1.250]
            result = await self.middleware.dispatch(request, call_next)

        assert result is not None
        events = self.in_memory.get_events()
        assert len(events) >= 2, "Should have RequestReceived and ResponseCompleted (or more)"
        completion_event = next(e for e in events if e.get("event_type") == "ResponseCompleted")
        assert completion_event["duration_s"] == 1.25
        assert completion_event["missing_usage"] is False
