#!/usr/bin/env python3
"""Real integration tests that make actual Anthropic API calls."""

from __future__ import annotations

import pytest

from src.config.config import runtime_config

litellm = pytest.importorskip("litellm")


class TestRealAnthropicAPI:
    """Integration tests that make real Anthropic Claude API calls."""

    @classmethod
    def setup_class(cls):
        """Setup for all tests - load environment variables."""
        runtime_config.ensure_loaded()
        cls.api_key = (
            runtime_config.get_str("ANTHROPIC_API_KEY")
            or runtime_config.get_str("OPENAI_API_KEY")
        )
        cls.base_url = runtime_config.get_str("ANTHROPIC_BASE_URL", "https://agentrouter.org")
        cls.use_node_proxy = runtime_config.get_bool("NODE_UPSTREAM_PROXY_ENABLE", False)

        if not cls.api_key:
            pytest.skip("ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable not set")

        # If Node proxy is enabled, route through localhost
        if cls.use_node_proxy:
            # Node proxy handles Anthropic at /v1/messages
            cls.base_url = "http://127.0.0.1:4000"

        # Set drop_params for compatibility
        litellm.drop_params = True

    def _call_claude_api(self, model="anthropic/claude-opus-4-6", **kwargs):
        """Helper method to call Anthropic Claude API."""
        # Ensure streaming is disabled for this method
        if 'stream' in kwargs:
            del kwargs['stream']

        default_params = {
            'model': model,
            'api_base': self.base_url,
            'api_key': self.api_key,
            'stream': False,
        }
        default_params.update(kwargs)
        return litellm.completion(**default_params)

    def _call_claude_api_streaming(self, model="anthropic/claude-opus-4-6", **kwargs):
        """Helper method to call Anthropic Claude API with streaming."""
        default_params = {
            'model': model,
            'api_base': self.base_url,
            'api_key': self.api_key,
            'stream': True,
        }
        default_params.update(kwargs)
        return litellm.completion(**default_params)

    def test_claude_basic_completion(self):
        """Test basic Claude completion with a simple prompt."""
        response = self._call_claude_api(
            messages=[{"role": "user", "content": "Say hello in one word"}],
            max_tokens=50,
        )

        # Assert response structure
        assert response is not None
        assert hasattr(response, 'choices')
        assert len(response.choices) > 0

        # Get the message content
        message = response.choices[0].message
        assert message is not None
        assert hasattr(message, 'content')
        assert message.content is not None

        # Assert the response contains some content
        content = message.content.strip()
        assert len(content) > 0, "Response content should not be empty"

        # Assert usage information is present
        assert hasattr(response, 'usage')
        assert response.usage is not None
        assert response.usage.total_tokens > 0

    def test_claude_with_system_message(self):
        """Test Claude completion with a system message."""
        response = self._call_claude_api(
            messages=[
                {"role": "system", "content": "You are a helpful math tutor."},
                {"role": "user", "content": "What is 2+2?"}
            ],
            max_tokens=100,
        )

        # Assert response
        message = response.choices[0].message
        content = message.content.strip()

        # Should have some content
        assert len(content) > 0, "Response content should not be empty"

        # Should answer the question correctly
        assert any(word in content.lower() for word in ["4", "four"])

    def test_claude_streaming_completion(self):
        """Test Claude completion with streaming enabled."""
        response_stream = self._call_claude_api_streaming(
            messages=[{"role": "user", "content": "Count from 1 to 5"}],
            max_tokens=100,
        )

        # Assert response is a generator/iterator
        assert hasattr(response_stream, '__iter__'), "Response should be iterable for streaming"

        # Collect all chunks
        chunks = []
        content_parts = []

        for chunk in response_stream:
            chunks.append(chunk)

            # Assert chunk structure
            assert chunk is not None
            assert hasattr(chunk, 'choices')
            assert len(chunk.choices) > 0

            # Get delta content if available
            delta = chunk.choices[0].delta
            if delta and hasattr(delta, 'content') and delta.content:
                content_parts.append(delta.content)

        # Assert we received chunks
        assert len(chunks) > 0, "Should receive at least one chunk"

        # Assert we got some content
        full_content = ''.join(content_parts).strip()
        assert len(full_content) > 0, "Streaming response should contain content"

    def test_claude_haiku_model(self):
        """Test Claude Haiku model."""
        response = self._call_claude_api(
            model="anthropic/claude-haiku-4-5-20251001",
            messages=[{"role": "user", "content": "What is the capital of France?"}],
            max_tokens=50,
        )

        assert response is not None
        assert len(response.choices) > 0
        message = response.choices[0].message
        assert message.content is not None
        content = message.content.strip()
        assert len(content) > 0
        # Should mention Paris
        assert "paris" in content.lower()

    def test_claude_multi_turn_conversation(self):
        """Test Claude with multi-turn conversation."""
        response = self._call_claude_api(
            messages=[
                {"role": "user", "content": "My name is Alice. Remember this."},
                {"role": "assistant", "content": "I've noted that your name is Alice."},
                {"role": "user", "content": "What is my name?"}
            ],
            max_tokens=50,
        )

        assert response is not None
        message = response.choices[0].message
        content = message.content.strip()
        assert len(content) > 0
        # Should remember the name
        assert "alice" in content.lower()
