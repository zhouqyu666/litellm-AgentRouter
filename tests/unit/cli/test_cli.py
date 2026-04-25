#!/usr/bin/env python3
"""Unit tests for cli.py."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.cli import parse_args


class TestParseArgs:
    """Test cases for parse_args function."""

    def test_parse_args_default_values(self):
        """Test parse_args with default values (no arguments)."""
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args([])

            assert args.config is None
            assert args.alias == "gpt-5"
            assert args.model == "gpt-5"
            assert args.upstream_base is None
            assert args.master_key == "sk-local-master"
            assert args.host == "0.0.0.0"
            assert args.port == 4000
            assert args.workers == 1
            assert args.debug is False
            assert args.detailed_debug is False
            assert args.no_master_key is False
            assert args.drop_params is True
            assert args.streaming is True
            assert args.print_config is False
            assert args.node_upstream_proxy_enabled is True

    def test_parse_args_with_all_arguments(self):
        """Test parse_args with all command line arguments provided."""
        argv = [
            "--config", "/path/to/config.yaml",
            "--alias", "custom-model",
            "--model", "gpt-3.5-turbo",
            "--upstream-base", "https://custom.api.com/v1",
            "--master-key", "sk-custom-master",
            "--host", "127.0.0.1",
            "--port", "8080",
            "--workers", "4",
            "--debug",
            "--detailed-debug",
            "--no-master-key",
            "--no-drop-params",
            "--no-streaming",
            "--print-config",
            "--no-node-upstream-proxy",
        ]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

            assert args.config == Path("/path/to/config.yaml")
            assert args.alias == "custom-model"
            assert args.model == "gpt-3.5-turbo"
            assert args.upstream_base == "https://custom.api.com/v1"
            assert args.master_key == "sk-custom-master"
            assert args.host == "127.0.0.1"
            assert args.port == 8080
            assert args.workers == 4
            assert args.debug is True
            assert args.detailed_debug is True
            assert args.no_master_key is True
            assert args.drop_params is False
            assert args.streaming is False
            assert args.print_config is True
            assert args.node_upstream_proxy_enabled is False

    def test_parse_args_config_from_env(self):
        """Test parse_args with config - LITELLM_CONFIG is now retired (hardcoded to None)."""
        with patch.dict(os.environ, {"LITELLM_CONFIG": "/env/config.yaml"}):
            args = parse_args([])

            # LITELLM_CONFIG is now retired, should always be None
            assert args.config is None

    def test_parse_args_alias_from_env(self):
        """Test parse_args with alias - LITELLM_MODEL_ALIAS is now retired (hardcoded to 'gpt-5')."""
        with patch.dict(os.environ, {"LITELLM_MODEL_ALIAS": "env-model"}):
            args = parse_args([])

            # LITELLM_MODEL_ALIAS is now retired, should always be 'gpt-5'
            assert args.alias == "gpt-5"

    def test_parse_args_model_from_env(self):
        """Test parse_args with model from environment variable."""
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-3.5-turbo"}):
            args = parse_args([])

            assert args.model == "gpt-3.5-turbo"

    def test_parse_args_upstream_base_from_env(self):
        """upstream_base default is now None; OPENAI_BASE_URL no longer drives --upstream-base."""
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://env.api.com/v1"}):
            args = parse_args([])

            # --upstream-base default is None (env var is consumed later by prepare_config)
            assert args.upstream_base is None

    def test_parse_args_master_key_from_env(self):
        """Test parse_args with master key from environment variable."""
        with patch.dict(os.environ, {"LITELLM_MASTER_KEY": "sk-env-master"}):
            args = parse_args([])

            assert args.master_key == "sk-env-master"

    def test_parse_args_host_from_env(self):
        """Test parse_args with host - LITELLM_HOST is now retired (hardcoded to '0.0.0.0')."""
        with patch.dict(os.environ, {"LITELLM_HOST": "127.0.0.1"}):
            args = parse_args([])

            # LITELLM_HOST is now retired, should always be '0.0.0.0'
            assert args.host == "0.0.0.0"

    def test_parse_args_port_from_env(self):
        """Test parse_args with port from environment variable."""
        with patch.dict(os.environ, {"PORT": "8080"}):
            args = parse_args([])

            assert args.port == 8080

    def test_parse_args_workers_from_env(self):
        """Test parse_args with workers - LITELLM_WORKERS is now retired (hardcoded to 1)."""
        with patch.dict(os.environ, {"LITELLM_WORKERS": "4"}):
            args = parse_args([])

            # LITELLM_WORKERS is now retired, should always be 1
            assert args.workers == 1

    def test_parse_args_debug_from_env_true(self):
        """Test parse_args with debug - LITELLM_DEBUG is now retired (hardcoded to False)."""
        with patch.dict(os.environ, {"LITELLM_DEBUG": "1"}):
            args = parse_args([])

            # LITELLM_DEBUG is now retired, should always be False
            assert args.debug is False

    def test_parse_args_debug_from_env_false(self):
        """Test parse_args with debug from environment variable (false)."""
        with patch.dict(os.environ, {"LITELLM_DEBUG": "0"}):
            args = parse_args([])

            assert args.debug is False

    def test_parse_args_detailed_debug_from_env(self):
        """Test parse_args with detailed debug - LITELLM_DETAILED_DEBUG is now retired (hardcoded to False)."""
        with patch.dict(os.environ, {"LITELLM_DETAILED_DEBUG": "true"}):
            args = parse_args([])

            # LITELLM_DETAILED_DEBUG is now retired, should always be False
            assert args.detailed_debug is False

    def test_parse_args_drop_params_from_env_true(self):
        """Test parse_args with drop_params from environment variable (true)."""
        with patch.dict(os.environ, {"LITELLM_DROP_PARAMS": "yes"}):
            args = parse_args([])

            assert args.drop_params is True

    def test_parse_args_drop_params_from_env_false(self):
        """Test parse_args with drop_params - LITELLM_DROP_PARAMS is now retired (hardcoded to True)."""
        with patch.dict(os.environ, {"LITELLM_DROP_PARAMS": "no"}):
            args = parse_args([])

            # LITELLM_DROP_PARAMS is now retired, should always be True
            assert args.drop_params is True

    def test_parse_args_streaming_from_env_true(self):
        """Test parse_args with streaming from environment variable (true)."""
        with patch.dict(os.environ, {"STREAMING_ENABLE": "true"}):
            args = parse_args([])
            assert args.streaming is True

    def test_parse_args_streaming_from_env_false(self):
        """Test parse_args with streaming from environment variable (false)."""
        with patch.dict(os.environ, {"STREAMING_ENABLE": "false"}):
            args = parse_args([])
            assert args.streaming is False

    def test_parse_args_streaming_from_env_various_formats(self):
        """Test parse_args with various boolean string formats for STREAMING_ENABLE."""
        test_cases = [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("TRUE", True),
            ("FALSE", False),
            ("Yes", True),
            ("No", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(os.environ, {"STREAMING_ENABLE": env_value}):
                args = parse_args([])
                assert args.streaming is expected, f"Failed for env value: {env_value}"

    def test_parse_args_node_proxy_env_disable(self):
        """Ensure NODE_UPSTREAM_PROXY_ENABLE disables the Node proxy via env."""
        with patch.dict(os.environ, {"NODE_UPSTREAM_PROXY_ENABLE": "0"}):
            args = parse_args([])
            assert args.node_upstream_proxy_enabled is False

    def test_parse_args_streaming_flag(self):
        """Test parse_args with --streaming flag."""
        argv = ["--streaming"]
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)
            assert args.streaming is True

    def test_parse_args_no_streaming_flag(self):
        """Test parse_args with --no-streaming flag."""
        argv = ["--no-streaming"]
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)
            assert args.streaming is False

    def test_parse_args_streaming_flag_overrides_env(self):
        """Test that --streaming flag overrides STREAMING_ENABLE environment variable."""
        env_vars = {"STREAMING_ENABLE": "false"}
        argv = ["--streaming"]

        with patch.dict(os.environ, env_vars):
            args = parse_args(argv)
            assert args.streaming is True

    def test_parse_args_no_streaming_flag_overrides_env(self):
        """Test that --no-streaming flag overrides STREAMING_ENABLE environment variable."""
        env_vars = {"STREAMING_ENABLE": "true"}
        argv = ["--no-streaming"]

        with patch.dict(os.environ, env_vars):
            args = parse_args(argv)
            assert args.streaming is False

    def test_parse_args_cli_overrides_env(self):
        """Test that CLI arguments override environment variables."""
        env_vars = {
            "LITELLM_CONFIG": "/env/config.yaml",
            "LITELLM_MODEL_ALIAS": "env-model",
            "OPENAI_MODEL": "gpt-3.5-turbo",
            "OPENAI_BASE_URL": "https://env.api.com/v1",
            "LITELLM_MASTER_KEY": "sk-env-master",
            "LITELLM_HOST": "127.0.0.1",
            "PORT": "8080",
            "STREAMING_ENABLE": "false",
        }

        argv = [
            "--config", "/cli/config.yaml",
            "--alias", "cli-model",
            "--model", "gpt-4",
            "--upstream-base", "https://cli.api.com/v1",
            "--master-key", "sk-cli-master",
            "--host", "localhost",
            "--port", "9000",
            "--workers", "2",
            "--no-drop-params",
            "--streaming",
        ]

        with patch.dict(os.environ, env_vars):
            args = parse_args(argv)

            # CLI arguments should take precedence
            assert args.config == Path("/cli/config.yaml")
            assert args.alias == "cli-model"
            assert args.model == "gpt-4"
            assert args.upstream_base == "https://cli.api.com/v1"
            assert args.master_key == "sk-cli-master"
            assert args.host == "localhost"
            assert args.port == 9000
            assert args.workers == 2
            assert args.drop_params is False  # overridden by --no-drop-params
            assert args.streaming is True  # overridden by --streaming (env was false)

            # Debug and detailed_debug are now hardcoded to False

    def test_parse_args_no_drop_params_flag(self):
        """Test --no-drop-params flag behavior."""
        argv = ["--no-drop-params"]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

            assert args.drop_params is False

    def test_parse_args_drop_params_flag_overrides_env(self):
        """Test --drop-params flag overrides environment variable."""
        env_vars = {"LITELLM_DROP_PARAMS": "no"}
        argv = ["--drop-params"]

        with patch.dict(os.environ, env_vars):
            args = parse_args(argv)

            assert args.drop_params is True

    def test_parse_args_no_master_key_flag(self):
        """Test --no-master-key flag behavior."""
        argv = ["--no-master-key"]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

            assert args.no_master_key is True

    def test_parse_args_print_config_flag(self):
        """Test --print-config flag behavior."""
        argv = ["--print-config"]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

            assert args.print_config is True

    def test_parse_args_debug_and_detailed_debug_flags(self):
        """Test --debug and --detailed-debug flags."""
        argv = ["--debug", "--detailed-debug"]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

            assert args.debug is True
            assert args.detailed_debug is True

    def test_parse_args_with_none_argv(self):
        """Test parse_args with None as argv (should use sys.argv)."""
        # This tests the default behavior when no argv is provided
        with patch("sys.argv", ["script", "--alias", "test-model"]):
            with patch.dict(os.environ, {}, clear=True):
                args = parse_args(None)
                assert args.alias == "test-model"

    def test_parse_args_help_message(self):
        """Test that help message contains expected content."""
        with patch("sys.argv", ["script", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                parse_args(["--help"])

        assert exc_info.value.code == 0

    def test_parse_args_invalid_port(self):
        """Test parse_args with invalid port value."""
        with pytest.raises(SystemExit):
            with patch.dict(os.environ, {}, clear=True):
                parse_args(["--port", "invalid"])

    def test_parse_args_invalid_workers(self):
        """Test parse_args with invalid workers value."""
        with pytest.raises(SystemExit):
            with patch.dict(os.environ, {}, clear=True):
                parse_args(["--workers", "invalid"])

    def test_parse_args_mixed_case_booleans(self):
        """Test parse_args with various boolean string formats - LITELLM_DEBUG is now retired (hardcoded to False)."""
        test_cases = [
            ("1", False),  # Should be False now, not True
            ("true", False),
            ("True", False),
            ("TRUE", False),
            ("yes", False),
            ("Yes", False),
            ("YES", False),
            ("on", False),
            ("On", False),
            ("ON", False),
            ("0", False),
            ("false", False),
            ("False", False),
            ("FALSE", False),
            ("no", False),
            ("No", False),
            ("NO", False),
            ("off", False),
            ("Off", False),
            ("OFF", False),
        ]

        for env_value, expected in test_cases:
            with patch.dict(os.environ, {"LITELLM_DEBUG": env_value}):
                args = parse_args([])
                # LITELLM_DEBUG is now retired, should always be False
                assert args.debug is False, f"Failed for env value: {env_value}"

    def test_parse_args_complex_combinations(self):
        """Test complex flag combinations from integration tests."""
        test_cases = [
            {
                "args": ["--model", "gpt-5", "--workers", "2", "--debug"],
                "expected_model": "gpt-5",
                "expected_workers": 2,
                "expected_debug": True
            },
            {
                "args": ["--upstream-base", "https://custom.api.com", "--drop-params"],
                "expected_base": "https://custom.api.com",
                "expected_drop_params": True
            },
            {
                "args": ["--model", "gpt-5", "--no-master-key", "--alias", "no-auth-model"],
                "expected_model": "gpt-5",
                "expected_no_master_key": True,
                "expected_alias": "no-auth-model"
            }
        ]

        for test_config in test_cases:
            with patch.dict(os.environ, {}, clear=True):
                args = parse_args(test_config["args"])

                if "expected_model" in test_config:
                    assert args.model == test_config["expected_model"]
                if "expected_workers" in test_config:
                    assert args.workers == test_config["expected_workers"]
                if "expected_debug" in test_config:
                    assert args.debug == test_config["expected_debug"]
                if "expected_base" in test_config:
                    assert args.upstream_base == test_config["expected_base"]
                if "expected_drop_params" in test_config:
                    assert args.drop_params == test_config["expected_drop_params"]
                if "expected_no_master_key" in test_config:
                    assert args.no_master_key == test_config["expected_no_master_key"]
                if "expected_alias" in test_config:
                    assert args.alias == test_config["expected_alias"]

    def test_parse_args_model_spec_single(self):
        """Test parsing --model-spec argument with single model."""
        argv = ["--model-spec", "key=test,alias=test-model,upstream=gpt-5"]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

        assert len(args.model_specs) == 1
        assert args.model_specs[0].key == "test"
        assert args.model_specs[0].alias == "test-model"
        assert args.model_specs[0].upstream_model == "gpt-5"

    def test_parse_args_model_spec_multiple(self):
        """Test parsing --model-spec argument with multiple models."""
        argv = [
            "--model-spec", "key=gpt5,alias=gpt-5,upstream=gpt-5,reasoning=high",
            "--model-spec", "key=deepseek,alias=deepseek-v3.2,upstream=deepseek-v3.2,reasoning=none",
        ]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

        assert len(args.model_specs) == 2
        gpt5_spec = next(s for s in args.model_specs if s.key == "gpt5")
        deepseek_spec = next(s for s in args.model_specs if s.key == "deepseek")

        assert gpt5_spec.alias == "gpt-5"
        assert gpt5_spec.reasoning_effort == "high"
        assert deepseek_spec.alias == "deepseek-v3.2"
        assert deepseek_spec.reasoning_effort == "none"

    def test_parse_args_model_spec_invalid_format(self):
        """Test that invalid model spec format raises error."""
        argv = ["--model-spec", "invalid-format"]

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                parse_args(argv)

        assert exc_info.value.code != 0  # argparse should exit with error code

    def test_parse_args_model_spec_missing_fields(self):
        """Test that model spec with missing fields raises error."""
        argv = ["--model-spec", "key=test,alias=test-model"]  # missing upstream

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                parse_args(argv)

        assert exc_info.value.code != 0

    def test_parse_args_model_spec_with_other_args(self):
        """Test --model-spec combined with other arguments."""
        argv = [
            "--model-spec", "key=test,alias=test-model,upstream=gpt-5",
            "--port", "8080",
            "--no-drop-params",
            "--master-key", "sk-custom",
        ]

        with patch.dict(os.environ, {}, clear=True):
            args = parse_args(argv)

        assert len(args.model_specs) == 1
        assert args.port == 8080
        assert args.drop_params is False
        assert args.master_key == "sk-custom"
