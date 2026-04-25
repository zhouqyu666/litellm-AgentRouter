#!/usr/bin/env python3
from __future__ import annotations

from typing import List

from .telemetry.middleware import TelemetryMiddleware
from .telemetry.alias_lookup import create_alias_lookup
from .reasoning_filter.middleware import ReasoningFilterMiddleware
from ..config.models import ModelSpec
from ..utils import env_bool


def install_middlewares(app, model_specs: List[ModelSpec]) -> None:
    # Always install ReasoningFilterMiddleware to drop unsupported 'reasoning' param
    app.add_middleware(ReasoningFilterMiddleware)

    # Telemetry is now configured explicitly via TelemetryConfig
    alias_lookup = create_alias_lookup(model_specs) if model_specs else {}

    # Check TELEMETRY_ENABLE environment variable using centralized utility
    telemetry_enabled = env_bool("TELEMETRY_ENABLE", True)

    class EnvToggle:
        def enabled(self, request):
            return telemetry_enabled

    from .telemetry.config import TelemetryConfig
    from .telemetry.sinks.logger import LoggerSink

    # Default no-op reasoning policy
    class NoOpReasoningPolicy:
        def apply(self, request):
            return request, {}

    # Configure sinks if telemetry is enabled
    sinks = [LoggerSink()] if telemetry_enabled else []

    config = TelemetryConfig(
        toggle=EnvToggle(),
        alias_resolver=lambda alias: alias_lookup.get(alias, alias),
        sinks=sinks,
        reasoning_policy=NoOpReasoningPolicy(),
    )

    app.add_middleware(TelemetryMiddleware, config=config)
    app.state.litellm_telemetry_alias_lookup = alias_lookup
