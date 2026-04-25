#!/usr/bin/env python3
from __future__ import annotations

from types import SimpleNamespace

from src.middleware.registry import install_middlewares
from src.config.models import ModelSpec


class TestRegistryBranches:
    """Test uncovered branches in middleware registry."""

    def test_install_middlewares_with_empty_model_specs(self):
        """install_middlewares should handle empty model specs."""
        app = SimpleNamespace()
        app.add_middleware = lambda *args, **kwargs: None
        app.state = SimpleNamespace()

        # Should not raise with empty list
        install_middlewares(app, [])

        # Should set empty alias lookup
        assert hasattr(app.state, "litellm_telemetry_alias_lookup")
        assert app.state.litellm_telemetry_alias_lookup == {}

    def test_install_middlewares_with_none_model_specs(self):
        """install_middlewares should handle None model specs."""
        app = SimpleNamespace()
        app.add_middleware = lambda *args, **kwargs: None
        app.state = SimpleNamespace()

        # Should not raise with None
        install_middlewares(app, None)

        # Should set empty alias lookup
        assert hasattr(app.state, "litellm_telemetry_alias_lookup")
        assert app.state.litellm_telemetry_alias_lookup == {}

    def test_install_middlewares_with_model_specs(self):
        """install_middlewares should create alias lookup from model specs."""
        app = SimpleNamespace()
        middlewares_added = []

        def track_middleware(middleware_class, **kwargs):
            middlewares_added.append((middleware_class, kwargs))

        app.add_middleware = track_middleware
        app.state = SimpleNamespace()

        model_specs = [
            ModelSpec(
                key="gpt4",
                upstream_model="openai/gpt-4",
                alias="gpt-4"
            ),
            ModelSpec(
                key="claude",
                upstream_model="anthropic/claude-3",
                alias="claude-3"
            )
        ]

        install_middlewares(app, model_specs)

        # Should add both middlewares
        assert len(middlewares_added) == 2

        # Should create alias lookup
        assert hasattr(app.state, "litellm_telemetry_alias_lookup")
        alias_lookup = app.state.litellm_telemetry_alias_lookup
        # Alias lookup uses the alias (public name), not the key
        assert "gpt-4" in alias_lookup
        assert "claude-3" in alias_lookup
        # Verify provider-aware prefixes
        assert alias_lookup["gpt-4"] == "openai/gpt-4"
        assert alias_lookup["claude-3"] == "anthropic/claude-3"

    def test_alias_resolver_fallback_no_hardcoded_prefix(self):
        """Alias resolver fallback should NOT hardcode openai/ prefix."""
        app = SimpleNamespace()
        config_captured = None

        def capture_middleware(middleware_class, **kwargs):
            nonlocal config_captured
            if "config" in kwargs:
                config_captured = kwargs["config"]

        app.add_middleware = capture_middleware
        app.state = SimpleNamespace()

        install_middlewares(app, [])

        if config_captured:
            # Unknown alias should be returned as-is, not prefixed with openai/
            result = config_captured.alias_resolver("unknown-model")
            assert result == "unknown-model"
            assert not result.startswith("openai/")

    def test_always_on_toggle_enabled(self):
        """AlwaysOnToggle should always return True."""
        from src.middleware.registry import install_middlewares

        app = SimpleNamespace()
        config_captured = None

        def capture_middleware(middleware_class, **kwargs):
            nonlocal config_captured
            if "config" in kwargs:
                config_captured = kwargs["config"]

        app.add_middleware = capture_middleware
        app.state = SimpleNamespace()

        install_middlewares(app, [])

        # Check that toggle is always enabled
        if config_captured:
            from fastapi import Request
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/test",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
                "app": app,
            }
            request = Request(scope)
            assert config_captured.toggle.enabled(request) is True

    def test_noop_reasoning_policy_apply(self):
        """NoOpReasoningPolicy should return request unchanged."""
        from src.middleware.registry import install_middlewares

        app = SimpleNamespace()
        config_captured = None

        def capture_middleware(middleware_class, **kwargs):
            nonlocal config_captured
            if "config" in kwargs:
                config_captured = kwargs["config"]

        app.add_middleware = capture_middleware
        app.state = SimpleNamespace()

        install_middlewares(app, [])

        # Check that reasoning policy is no-op
        if config_captured:
            from fastapi import Request
            scope = {
                "type": "http",
                "method": "POST",
                "path": "/test",
                "headers": [],
                "query_string": b"",
                "client": ("127.0.0.1", 12345),
                "app": app,
            }
            request = Request(scope)
            result_request, metadata = config_captured.reasoning_policy.apply(request)
            assert result_request is request
            assert metadata == {}
