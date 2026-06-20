#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

from fastapi import Request, Response
import pytest

from src.middleware.telemetry.middleware import TelemetryMiddleware
from src.middleware.telemetry.config import TelemetryConfig
from src.middleware.telemetry.sinks.inmemory import InMemorySink
from src.middleware.telemetry.request_context import NoOpReasoningPolicy


class EnabledToggle:
    def enabled(self, request):
        return True


class DisabledToggle:
    def enabled(self, request):
        return False


class TestMiddlewareBranches:
    """Test uncovered branches in TelemetryMiddleware."""

    def setup_method(self):
        self.mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        self.in_memory = InMemorySink()

    def _make_request(self, method="POST", path="/v1/chat/completions", json_body=None, headers=None):
        default_headers = [(b"content-type", b"application/json")]
        if headers:
            default_headers.extend(headers)

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": default_headers,
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

    def _make_response(self, status_code=200, json_body=None):
        content = (json.dumps(json_body) if json_body else "{}").encode()
        resp = Response(content=content, media_type="application/json")
        resp.status_code = status_code
        resp.body = content
        return resp

    async def test_toggle_exception_defaults_to_enabled(self):
        """If toggle.enabled() raises, should default to enabled."""
        class FailingToggle:
            def enabled(self, request):
                raise RuntimeError("Toggle failure")

        config = TelemetryConfig(
            toggle=FailingToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(json_body={"model": "test"})
        response = self._make_response(200, {"usage": {"prompt_tokens": 5, "completion_tokens": 10}})

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)

        assert result is response
        assert len(self.in_memory.get_events()) > 0

    async def test_request_without_json_body(self):
        """Ignore non-model endpoints instead of logging noisy telemetry."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(method="GET", path="/health")
        response = self._make_response(200)

        async def call_next(req):
            return response

        result = await middleware.dispatch(request, call_next)

        assert result is response
        assert self.in_memory.get_events() == []

    async def test_request_with_x_forwarded_for_header(self):
        """Extract remote address from x-forwarded-for header."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(
            json_body={"model": "test"},
            headers=[(b"x-forwarded-for", b"192.168.1.1, 10.0.0.1")]
        )
        response = self._make_response(200)

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        request_event = next(e for e in events if e.get("event_type") == "RequestReceived")
        assert request_event["remote_addr"] == "192.168.1.1"

    async def test_request_with_x_real_ip_header(self):
        """Extract remote address from x-real-ip header."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(
            json_body={"model": "test"},
            headers=[(b"x-real-ip", b"203.0.113.42")]
        )
        response = self._make_response(200)

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        request_event = next(e for e in events if e.get("event_type") == "RequestReceived")
        assert request_event["remote_addr"] == "203.0.113.42"

    async def test_request_without_client_info(self):
        """Handle request without client information."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "client": None,
            "app": self.mock_app,
        }
        request = Request(scope)

        async def receive():
            return {"type": "http.request", "body": json.dumps({"model": "test"}).encode(), "more_body": False}
        request._receive = receive

        response = self._make_response(200)

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        request_event = next(e for e in events if e.get("event_type") == "RequestReceived")
        assert request_event["remote_addr"] == "unknown"

    async def test_streaming_response_without_usage(self):
        """Handle streaming response that doesn't contain usage."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(json_body={"model": "test", "stream": True})

        async def stream_generator():
            yield b'data: {"choices": [{"delta": {"content": "test"}}]}\n\n'
            yield b'data: [DONE]\n\n'

        response = Response(content=b"", media_type="text/event-stream")
        response.body_iterator = stream_generator()

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        completion_event = next(e for e in events if e.get("event_type") == "ResponseCompleted")
        assert completion_event["streaming"] is True
        assert completion_event["missing_usage"] is True

    async def test_response_without_body_attribute(self):
        """Handle response without body attribute."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(json_body={"model": "test", "stream": False})

        response = Response(content=b"test")
        delattr(response, "body")

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        completion_event = next(e for e in events if e.get("event_type") == "ResponseCompleted")
        assert completion_event["missing_usage"] is True

    async def test_response_with_non_json_body(self):
        """Handle response with non-JSON body."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        request = self._make_request(json_body={"model": "test", "stream": False})

        response = Response(content=b"not json", media_type="text/plain")
        response.body = b"not json"

        async def call_next(req):
            return response

        await middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        completion_event = next(e for e in events if e.get("event_type") == "ResponseCompleted")
        assert completion_event["parse_error"] is True


class TestMiddlewareToggle:
    """Test telemetry toggle pass-through behavior."""

    def setup_method(self):
        self.log_records = []
        handler = logging.Handler()
        handler.setLevel(logging.DEBUG)
        handler.emit = lambda record: self.log_records.append(record)
        logging.getLogger("litellm_launcher.telemetry").addHandler(handler)

        self.mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        self.sink = InMemorySink()

        self.config = TelemetryConfig(
            toggle=DisabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.sink],
            reasoning_policy=NoOpReasoningPolicy(),
        )

        self.middleware = TelemetryMiddleware(app=self.mock_app, config=self.config)

    def teardown_method(self):
        logger = logging.getLogger("litellm_launcher.telemetry")
        for h in list(logger.handlers):
            if h.__class__ is logging.Handler:
                logger.removeHandler(h)

    def _make_request(self, method="POST", path="/v1/chat/completions", body: bytes = b"") -> Request:
        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "app": self.mock_app,
        }
        req = Request(scope)

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        req._receive = receive
        return req

    def test_toggle_false_pass_through(self):
        """Middleware must pass-through when toggle is disabled."""
        request = self._make_request(body=b'{"model":"x","messages":[],"stream":false}')
        response = Response(content=b'{"ok":true}', media_type="application/json")
        response.body = response.body if hasattr(response, "body") else response.body

        async def call_next(req: Request):
            return response

        result = asyncio.run(self.middleware.dispatch(request, call_next))

        assert result is response, "Middleware must pass-through when toggle is disabled"
        assert len(self.sink.get_events()) == 0, "No events should be emitted when toggle=false"
        assert len(self.log_records) == 0, "No logger output expected when toggle=false"


class TestMiddlewareIsolation:
    """Verify new telemetry pipeline works independently without shared class state."""

    async def test_new_middleware_with_explicit_config(self):
        """TelemetryMiddleware works with explicit TelemetryConfig."""
        mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        sink = InMemorySink()
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[sink],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(app=mock_app, config=config)

        request = self._make_request()

        async def call_next(req):
            return Response(content=b'{"ok":true}')

        from unittest.mock import patch
        with patch("time.perf_counter") as mock_time:
            mock_time.side_effect = [0.0, 0.100]
            result = await middleware.dispatch(request, call_next)

        assert result is not None
        events = sink.get_events()
        assert any(e.get("event_type") == "RequestReceived" for e in events)
        assert any(e.get("event_type") == "ResponseCompleted" for e in events)

    def _make_request(self, json_body=None):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(json.dumps(json_body or {}))).encode())],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
        }
        req = Request(scope)
        if json_body:
            async def receive():
                return {"type": "http.request", "body": json.dumps(json_body).encode(), "more_body": False}
            req._receive = receive
        return req


class TestReasoningPolicyIntegration:
    """Test reasoning policy mutation and debug metadata."""

    def setup_method(self):
        self.mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        self.in_memory = InMemorySink()
        self.policy = DropReasoningPolicy()
        self.config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=self.policy,
        )
        self.middleware = TelemetryMiddleware(self.mock_app, config=self.config)

    async def test_reasoning_policy_mutates_and_emits_metadata(self):
        """Policy should drop reasoning field and emit debug metadata."""
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/v1/chat/completions",
            "headers": [(b"content-type", b"application/json"), (b"content-length", b'{"model":"test","reasoning":"dropme"}')],
            "query_string": b"",
            "client": ("127.0.0.1", 12345),
            "app": self.mock_app,
        }
        request = Request(scope)

        async def receive():
            return {"type": "http.request", "body": b'{"model":"test","reasoning":"dropme"}', "more_body": False}
        request._receive = receive

        async def call_next(req):
            return Response(content=b'{"ok":true}')

        result = await self.middleware.dispatch(request, call_next)

        events = self.in_memory.get_events()
        req_event = next((e for e in events if e.get("event_type") == "RequestReceived"))
        assert req_event is not None
        assert "dropped_param" in req_event.get("reasoning_metadata", {})
        assert result is not None


class DropReasoningPolicy:
    def apply(self, request: Request):
        return request, {"dropped_param": "reasoning"}


class TestMiddlewareErrorHandling:
    """Test error handling paths without over-testing every exception type."""

    def setup_method(self):
        self.mock_app = SimpleNamespace(state=SimpleNamespace(litellm_telemetry_alias_lookup={}))
        self.in_memory = InMemorySink()
        self.config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )

    def test_config_and_alias_lookup_none_raises_error(self):
        """Should raise ValueError when both config and alias_lookup are None."""
        with pytest.raises(ValueError, match="Either config or alias_lookup must be provided"):
            TelemetryMiddleware(self.mock_app)

    async def test_extract_streaming_usage_with_body_iterator(self):
        """Test streaming usage extraction with body_iterator attribute."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        response = Response(content=b"", media_type="text/event-stream")

        async def mock_stream():
            yield b'data: {"usage": {"prompt_tokens": 5}}\n\n'

        response.body_iterator = mock_stream()

        result, usage = await middleware._extract_streaming_usage(response)

        assert result is not None
        assert usage is not None
        assert hasattr(result, "body_iterator")

    async def test_extract_streaming_usage_with_aiter(self):
        """Test streaming usage extraction with __aiter__ attribute."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        async def mock_stream():
            yield b'data: {"usage": {"prompt_tokens": 10}}\n\n'

        response = mock_stream()

        result, usage = await middleware._extract_streaming_usage(response)

        assert result is not None
        assert usage is not None

    async def test_extract_streaming_usage_extraction_failure(self):
        """Test graceful handling when streaming usage extraction fails."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        response = Response(content=b"", media_type="text/event-stream")

        # Mock a failing body_iterator
        async def failing_stream():
            raise RuntimeError("Stream error")

        response.body_iterator = failing_stream()

        original_response = response
        result, usage = await middleware._extract_streaming_usage(response)

        # Should return original response unchanged and no usage
        assert result is original_response
        assert usage is None

    async def test_extract_non_streaming_usage_with_body_iterator(self):
        """Test non-streaming usage extraction with body_iterator."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        response = Response(content=b'{"usage": {"prompt_tokens": 5}}', media_type="application/json")

        async def mock_body():
            yield b'{"usage": {"prompt_tokens": 5}}'

        response.body_iterator = mock_body()

        result, usage, parse_error = await middleware._extract_non_streaming_usage(response)

        assert result is not None
        assert usage is not None
        assert parse_error is False

    async def test_extract_non_streaming_usage_json_decode_error(self):
        """Test JSON decode error handling."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        response = Response(content=b'invalid json', media_type="application/json")
        response.body = b'invalid json'

        result, usage, parse_error = await middleware._extract_non_streaming_usage(response)

        assert result is not None
        assert usage is None
        assert parse_error is True

    async def test_extract_non_streaming_usage_extraction_exception(self):
        """Test broad exception handling in usage extraction."""
        config = TelemetryConfig(
            toggle=EnabledToggle(),
            alias_resolver=lambda alias: f"openai/{alias}",
            sinks=[self.in_memory],
            reasoning_policy=NoOpReasoningPolicy(),
        )
        middleware = TelemetryMiddleware(self.mock_app, config=config)

        response = Response(content=b'{"usage": {}}')

        # Mock body_iterator that raises exception
        async def failing_body():
            raise RuntimeError("Body extraction error")

        response.body_iterator = failing_body()

        result, usage, parse_error = await middleware._extract_non_streaming_usage(response)

        # Should handle exception gracefully
        assert result is response
        assert usage is None
        assert parse_error is True

    async def test_publish_event_with_pipeline_attribute(self):
        """Test event publishing when config has pipeline attribute."""
        from unittest.mock import Mock, MagicMock

        # Create mock config with pipeline attribute
        config = MagicMock()
        config.toggle = EnabledToggle()
        config.alias_resolver = lambda alias: f"openai/{alias}"
        config.sinks = []
        config.reasoning_policy = NoOpReasoningPolicy()

        mock_pipeline = Mock()
        config.pipeline = mock_pipeline
        # Mock hasattr to return True for pipeline attribute
        config.__contains__ = lambda self, item: item == 'pipeline'
        config.__getattribute__ = lambda self, name: mock_pipeline if name == 'pipeline' else object.__getattribute__(self, name)

        middleware = TelemetryMiddleware(self.mock_app, config=config)

        test_event = {"event_type": "Test", "data": "value"}
        middleware._publish_event(test_event)

        mock_pipeline.publish.assert_called_once_with(test_event)

    async def test_publish_event_fallback_to_sinks(self):
        """Test event publishing fallback to sinks list."""
        middleware = TelemetryMiddleware(self.mock_app, config=self.config)

        test_event = {"event_type": "Test", "data": "value"}
        middleware._publish_event(test_event)

        events = self.in_memory.get_events()
        assert test_event in events
