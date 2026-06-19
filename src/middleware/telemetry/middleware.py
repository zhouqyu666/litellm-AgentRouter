#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, AsyncIterator

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .config import TelemetryConfig
from .request_context import apply_reasoning_policy
from .store import telemetry_store
from .usage import parse_usage_from_response, parse_usage_from_stream_chunk, to_usage_tokens


class TelemetryMiddleware(BaseHTTPMiddleware):
    """New telemetry middleware per PRD using explicit dependency injection.

    Behavior confirmed with user:
    - When toggle.enabled(request) is False: pass-through (call downstream) and emit no telemetry/logs.
    - Logger sink will use json.dumps for serialization (handled by sink, not here).

    Compatibility shim (temporary): supports legacy (alias_lookup) signature to keep existing tests green.
    """

    def __init__(self, app, config: TelemetryConfig | None = None, alias_lookup: dict | None = None):
        super().__init__(app)
        # Compatibility path: allow legacy alias_lookup usage while respecting env var
        if config is None and alias_lookup is not None:
            from .config import TelemetryConfig

            # Respect TELEMETRY_ENABLE environment variable
            try:
                from ..utils import env_bool
                enabled = env_bool("TELEMETRY_ENABLE", True)
            except ImportError:
                # Fallback for import path issues in some contexts
                import os
                enabled = os.environ.get("TELEMETRY_ENABLE", "1") in ("1", "true", "True", "yes", "on")

            class EnvToggle:
                def enabled(self, request: Request) -> bool:
                    return enabled

            class NoOpReasoningPolicy:
                def apply(self, request):
                    return request, {}

            config = TelemetryConfig(
                toggle=EnvToggle(),
                alias_resolver=lambda alias: alias_lookup.get(alias, f"openai/{alias}"),
                sinks=[],  # Default empty to avoid breaking test expectations
                reasoning_policy=NoOpReasoningPolicy(),
            )

        if config is None:
            raise ValueError("Either config or alias_lookup must be provided")

        self.config = config
        # Provide a stable logger for any internal diagnostics (not event logging)
        self.logger = logging.getLogger("litellm_launcher.telemetry")
        if self.logger.level == logging.NOTSET:
            self.logger.setLevel(logging.INFO)
        if not self.logger.handlers and not logging.getLogger().handlers:
            # Ensure logs are visible even if host hasn't configured logging yet
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            self.logger.addHandler(handler)

    async def dispatch(self, request: Request, call_next) -> Response:
        # Toggle off ⇒ pass-through, no emissions
        try:
            enabled = self.config.toggle.enabled(request)
        except Exception:
            # Fail-safe: if toggle errors, treat as enabled to avoid hiding behavior
            enabled = True

        if not enabled:
            # Explicit: no sink emissions, no debug logs
            return await call_next(request)

        # Reasoning policy and context extraction (mutates request and produces debug metadata)
        request, reasoning_metadata = apply_reasoning_policy(self.config.reasoning_policy, request)

        # Build basic request context
        method = request.method
        path = request.url.path if hasattr(request, "url") and hasattr(request.url, "path") else "/"
        client_request_id = request.headers.get("x-request-id")
        remote_addr = self._get_remote_addr(request)

        # RFC1123 timestamp for events
        timestamp = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")

        request_event = {
            "event_type": "RequestReceived",
            "timestamp": timestamp,
            "method": method,
            "path": path,
            "client_request_id": client_request_id,
            "remote_addr": remote_addr,
            "reasoning_metadata": reasoning_metadata,
        }

        # Extract model alias early (after reasoning policy mutation)
        try:
            request_body = await request.json()
            model_alias = request_body.get("model", "unknown")
            streaming = request_body.get("stream", False)
        except Exception:
            request_body = None
            model_alias = "unknown"
            streaming = False

        request_event["model_alias"] = model_alias
        request_event["streaming"] = streaming
        self._publish_event(request_event)

        upstream_model = self.config.alias_resolver(model_alias)

        # Dispatch with timing
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
            end_time = time.perf_counter()
            duration_s = end_time - start_time

            # Emit ResponseCompleted if successful
            status_code = getattr(response, "status_code", 200)
            usage_dict = None
            parse_error = False
            missing_usage = False

            # Extract usage and ensure stream replay
            if streaming:
                response, usage_dict = await self._extract_streaming_usage(response)
            else:
                response, usage_dict, parse_error = await self._extract_non_streaming_usage(response)
                if not usage_dict:
                    missing_usage = True

            usage = to_usage_tokens(usage_dict)

            completion_event = {
                "event_type": "ResponseCompleted",
                "timestamp": timestamp,
                "duration_s": duration_s,
                "status_code": status_code,
                "method": method,
                "path": path,
                "model_alias": model_alias,
                "upstream_model": upstream_model,
                "usage": usage,
                "streaming": streaming,
                "parse_error": parse_error,
                "missing_usage": missing_usage,
                "client_request_id": client_request_id,
                "remote_addr": remote_addr,
            }
            telemetry_store.record(completion_event)
            self._publish_event(completion_event)
            return response

        except Exception as e:
            end_time = time.perf_counter()
            duration_s = end_time - start_time
            status_code = getattr(e, "status_code", 500)

            error_event = {
                "event_type": "ErrorRaised",
                "timestamp": timestamp,
                "duration_s": duration_s,
                "status_code": status_code,
                "method": method,
                "path": path,
                "model_alias": model_alias,
                "upstream_model": upstream_model,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "streaming": streaming,
                "client_request_id": client_request_id,
                "remote_addr": remote_addr,
            }
            telemetry_store.record(error_event)
            self._publish_event(error_event)
            raise

    def _publish_event(self, event: dict) -> None:
        """Publish event through pipeline if present; compatibility fallback."""
        if hasattr(self.config, "pipeline") and self.config.pipeline:
            self.config.pipeline.publish(event)
        elif hasattr(self.config, "sinks"):
            # Fallback for compatibility shim where sinks is a list
            from .pipeline import TelemetryPipeline
            pipeline = TelemetryPipeline(self.config.sinks)
            pipeline.publish(event)

    def _get_remote_addr(self, request: Request) -> str:
        """Extract remote address respecting forwarded headers."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        if request.client and hasattr(request.client, "host"):
            return request.client.host
        return "unknown"

    async def _extract_streaming_usage(self, response: Any) -> tuple[Any, dict | None]:
        """Extract usage from streaming responses and ensure replayable stream."""
        usage_dict = None
        chunks = []

        async def consume(iterator: AsyncIterator[bytes]) -> None:
            nonlocal usage_dict
            async for chunk in iterator:
                chunks.append(chunk)
                if usage_dict is None:
                    chunk_text = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, bytes) else str(chunk)
                    usage_dict = parse_usage_from_stream_chunk(chunk_text)

        async def replay_chunks():
            """Async generator to replay collected chunks."""
            for chunk in chunks:
                yield chunk

        try:
            if hasattr(response, "body_iterator"):
                await consume(response.body_iterator)
                # Make stream replayable with async generator
                response.body_iterator = replay_chunks()
            elif hasattr(response, "__aiter__"):
                await consume(response)
                response = replay_chunks()
        except Exception:
            # If extraction fails, return response unchanged
            pass

        return response, usage_dict

    async def _extract_non_streaming_usage(self, response: Any) -> tuple[Any, dict | None, bool]:
        """Extract usage from non-streaming response."""
        usage_dict = None
        parse_error = False

        try:
            # For Starlette Response objects, we need to read the body_iterator
            if hasattr(response, "body_iterator"):
                chunks = []
                async for chunk in response.body_iterator:
                    chunks.append(chunk)

                # Reconstruct the body
                response_body = b"".join(chunks)

                # Make the response replayable by creating a new iterator
                async def replay_body():
                    yield response_body

                response.body_iterator = replay_body()

                # Parse the body for usage
                if response_body:
                    response_text = response_body.decode("utf-8", errors="ignore")
                    try:
                        response_json = json.loads(response_text)
                        usage_dict = parse_usage_from_response(response_json)
                    except json.JSONDecodeError:
                        parse_error = True
            elif hasattr(response, "body"):
                # Fallback for direct body attribute
                response_body = response.body
                if isinstance(response_body, bytes):
                    response_text = response_body.decode("utf-8", errors="ignore")
                else:
                    response_text = str(response_body)
                try:
                    response_json = json.loads(response_text)
                    usage_dict = parse_usage_from_response(response_json)
                except json.JSONDecodeError:
                    parse_error = True
        except Exception:
            # Broad safety: any extraction issue flags parse error
            parse_error = True

        return response, usage_dict, parse_error
