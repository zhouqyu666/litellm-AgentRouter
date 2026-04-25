#!/usr/bin/env python3
"""
Unit tests for Docker entrypoint module.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest

from src.config.entrypoint import (
    main,
    mask_config_output,
    mask_sensitive_value,
    validate_environment,
    write_config_file,
)


class TestValidateEnvironment:
    """Tests for validate_environment function."""

    def test_validate_environment_success(self, monkeypatch):
        """Test that validation passes when at least one model is defined."""
        for key in list(os.environ.keys()):
            if key.startswith("MODEL_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MODEL_GPT5_UPSTREAM_MODEL", "gpt-5")
        # Should not raise
        validate_environment()

    def test_validate_environment_missing_models(self, monkeypatch, capsys):
        """Test that validation fails when no MODEL_* vars are defined."""
        # Skip .env file loading to prevent MODEL_* vars from being reloaded
        monkeypatch.setenv("SKIP_DOTENV", "1")

        for key in list(os.environ.keys()):
            if key.startswith("MODEL_"):
                monkeypatch.delenv(key, raising=False)

        with pytest.raises(SystemExit) as exc_info:
            validate_environment()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "MODEL_<KEY>_UPSTREAM_MODEL" in captured.err


class TestMaskSensitiveValue:
    """Tests for mask_sensitive_value function."""

    def test_mask_long_value(self):
        """Test masking a long sensitive value."""
        result = mask_sensitive_value("sk-1234567890abcdef")
        assert result == "sk-1***ef"

    def test_mask_short_value(self):
        """Test masking a short sensitive value."""
        result = mask_sensitive_value("short")
        assert result == "shor***"

    def test_mask_very_short_value(self):
        """Test masking a very short value."""
        result = mask_sensitive_value("abc")
        assert result == "abc***"

    def test_mask_custom_visible_chars(self):
        """Test masking with custom visible character counts."""
        result = mask_sensitive_value("sk-1234567890abcdef", visible_chars=6, visible_suffix=4)
        assert result == "sk-123***cdef"


class TestMaskConfigOutput:
    """Tests for mask_config_output function."""

    def test_mask_api_key_values(self):
        """Test that api_key values are masked in YAML."""
        config = """
model_list:
  - model_name: "gpt-5"
    litellm_params:
      api_key: "sk-1234567890abcdef"
"""
        result = mask_config_output(config)
        assert "sk-1***ef" in result
        assert "sk-1234567890abcdef" not in result

    def test_mask_master_key_values(self):
        """Test that master_key values are masked in YAML."""
        config = """
general_settings:
  master_key: "master-key-secret"
"""
        result = mask_config_output(config)
        assert "mast***et" in result
        assert "master-key-secret" not in result

    def test_mask_config_preserves_structure(self):
        """Test that YAML structure is preserved after masking."""
        config = """
model_list:
  - model_name: "gpt-5"
    litellm_params:
      api_key: "sk-1234567890abcdef"
general_settings:
  master_key: "master-key-secret"
"""
        result = mask_config_output(config)
        assert "model_list:" in result
        assert "model_name:" in result
        assert "litellm_params:" in result
        assert "general_settings:" in result

    def test_mask_quoted_values(self):
        """Test masking of quoted sensitive values."""
        config = 'api_key: "sk-1234567890abcdef"'
        result = mask_config_output(config)
        assert "sk-1***ef" in result

    def test_mask_unquoted_values(self):
        """Test masking of unquoted sensitive values."""
        config = "api_key: sk-1234567890abcdef"
        result = mask_config_output(config)
        assert "sk-1***ef" in result


class TestWriteConfigFile:
    """Tests for write_config_file function."""

    def test_write_config_file_creates_file(self):
        """Test that configuration is written to file correctly."""
        config_text = "test: config\ndata: value"
        path = "/tmp/test-config.yaml"

        with patch("builtins.open", mock_open()) as mock_file:
            write_config_file(config_text, path)

            mock_file.assert_called_once_with(path, 'w')
            mock_file().write.assert_called_once_with(config_text)


class TestMain:
    """Tests for main entrypoint function."""

    @patch("src.config.entrypoint.os.execvp")
    @patch("src.config.entrypoint.write_config_file")
    @patch("src.config.entrypoint.render_config")
    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_integration_flow(
        self,
        mock_node_cls,
        mock_validate,
        mock_load_specs,
        mock_render,
        mock_write,
        mock_execvp,
        monkeypatch,
        capsys,
    ):
        """Test the full main() integration flow with mocked dependencies."""
        # Setup environment
        monkeypatch.setenv("OPENAI_BASE_URL", "https://agentrouter.org/v1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-api-key-1234567890")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-local-master")
        monkeypatch.setenv("LITELLM_HOST", "0.0.0.0")
        monkeypatch.setenv("PORT", "4000")

        # Setup mocks
        mock_node_instance = MagicMock()
        mock_node_instance.start.return_value.pid = 1234
        mock_node_cls.return_value = mock_node_instance
        mock_model_spec = MagicMock()
        mock_load_specs.return_value = [mock_model_spec]
        mock_render.return_value = "api_key: sk-1234567890abcdef\nmaster_key: master-key-secret"

        # Call main - execvp is mocked so it won't actually replace the process
        main()

        # Verify calls
        mock_validate.assert_called_once()
        mock_load_specs.assert_called_once()
        mock_node_instance.start.assert_called_once()
        mock_node_instance.stop.assert_not_called()
        assert os.environ.get("NODE_UPSTREAM_PROXY_PID") == "1234"
        mock_render.assert_called_once_with(
            model_specs=[mock_model_spec],
            global_upstream_base="http://127.0.0.1:4000/v1",
            master_key="sk-local-master",
            drop_params=True,
            streaming=True,
            provider_api_keys={"openai": ["sk-test-api-key-1234567890"]},
            node_proxy_base="http://127.0.0.1:4000",
        )
        mock_write.assert_called_once_with(
            "api_key: sk-1234567890abcdef\nmaster_key: master-key-secret",
            "/app/generated-config.yaml"
        )

        # Verify execvp was called with correct arguments
        mock_execvp.assert_called_once()
        args = mock_execvp.call_args[0]
        assert args[0] == sys.executable
        assert args[1] == [
            sys.executable,
            "-m",
            "src.main",
            "--config",
            "/app/generated-config.yaml",
            "--host",
            "0.0.0.0",
            "--port",
            "4000",
        ]

        # Verify output contains masked values and cleanup
        captured = capsys.readouterr()
        assert "sk-1***ef" in captured.out
        assert "mast***et" in captured.out
        assert "sk-1234567890abcdef" not in captured.out
        assert "master-key-secret" not in captured.out
        monkeypatch.delenv("NODE_UPSTREAM_PROXY_PID", raising=False)

    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_exits_on_load_specs_error(
        self,
        mock_node_cls,
        mock_validate,
        mock_load_specs,
        monkeypatch,
        capsys,
    ):
        """Test that main exits with error when load_model_specs_from_env fails."""
        mock_node_instance = MagicMock()
        mock_node_instance.start.return_value.pid = 5678
        mock_node_cls.return_value = mock_node_instance
        mock_load_specs.side_effect = ValueError("Missing MODEL_GPT5_UPSTREAM_MODEL")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR: Missing MODEL_GPT5_UPSTREAM_MODEL" in captured.err
        mock_node_instance.stop.assert_called_once()
        monkeypatch.delenv("NODE_UPSTREAM_PROXY_PID", raising=False)

    @patch("src.config.entrypoint.render_config")
    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_exits_on_render_error(
        self,
        mock_node_cls,
        mock_validate,
        mock_load_specs,
        mock_render,
        monkeypatch,
        capsys,
    ):
        """Test that main exits with error when render_config fails."""
        mock_node_instance = MagicMock()
        mock_node_instance.start.return_value.pid = 9012
        mock_node_cls.return_value = mock_node_instance
        mock_load_specs.return_value = [MagicMock()]
        mock_render.side_effect = Exception("Render failed")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR: Failed to generate configuration: Render failed" in captured.err
        mock_node_instance.stop.assert_called_once()
        monkeypatch.delenv("NODE_UPSTREAM_PROXY_PID", raising=False)

    @patch("src.config.entrypoint.os.execvp")
    @patch("src.config.entrypoint.write_config_file")
    @patch("src.config.entrypoint.render_config")
    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("socket.gethostbyname")
    def test_main_docker_compose_mode(
        self,
        mock_gethostbyname,
        mock_validate,
        mock_load_specs,
        mock_render,
        mock_write,
        mock_execvp,
        monkeypatch,
        capsys,
    ):
        """Test main() in docker-compose mode where node-proxy hostname resolves."""
        monkeypatch.setenv("NODE_UPSTREAM_PROXY_ENABLE", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-dc-test-1234567890")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-local-master")
        monkeypatch.setenv("LITELLM_HOST", "0.0.0.0")
        monkeypatch.setenv("PORT", "4000")

        mock_gethostbyname.return_value = "172.18.0.2"
        mock_model_spec = MagicMock()
        mock_load_specs.return_value = [mock_model_spec]
        mock_render.return_value = "api_key: sk-dc-test-1234567890"

        main()

        mock_gethostbyname.assert_called_once_with("node-proxy")
        mock_render.assert_called_once()
        render_kwargs = mock_render.call_args[1]
        assert render_kwargs["global_upstream_base"] == "http://node-proxy:4000/v1"
        assert render_kwargs["node_proxy_base"] == "http://node-proxy:4000"

        captured = capsys.readouterr()
        assert "external Node proxy service" in captured.out

    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_node_start_runtime_error(
        self,
        mock_node_cls,
        mock_validate,
        monkeypatch,
        capsys,
    ):
        """Test main exits when NodeProxyProcess.start() raises RuntimeError."""
        mock_node_instance = MagicMock()
        mock_node_instance.start.side_effect = RuntimeError("Node.js runtime not available")
        mock_node_cls.return_value = mock_node_instance

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "Node.js runtime not available" in captured.err

    @patch("src.config.entrypoint.write_config_file")
    @patch("src.config.entrypoint.render_config")
    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_test_mode_stops_node_process(
        self,
        mock_node_cls,
        mock_validate,
        mock_load_specs,
        mock_render,
        mock_write,
        monkeypatch,
        capsys,
    ):
        """Test ENTRYPOINT_TEST_MODE stops node process and exits cleanly."""
        monkeypatch.setenv("ENTRYPOINT_TEST_MODE", "1")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-tm-1234567890")
        monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-local-master")
        monkeypatch.setenv("LITELLM_HOST", "0.0.0.0")
        monkeypatch.setenv("PORT", "4000")

        mock_node_instance = MagicMock()
        mock_node_instance.start.return_value.pid = 7777
        mock_node_cls.return_value = mock_node_instance
        mock_load_specs.return_value = [MagicMock()]
        mock_render.return_value = "api_key: sk-test-tm-1234567890"

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 0
        mock_node_instance.stop.assert_called_once()
        captured = capsys.readouterr()
        assert "ENTRYPOINT_TEST_MODE" in captured.out
        monkeypatch.delenv("NODE_UPSTREAM_PROXY_PID", raising=False)

    @patch("src.config.entrypoint.write_config_file")
    @patch("src.config.entrypoint.render_config")
    @patch("src.config.entrypoint.load_model_specs_from_env")
    @patch("src.config.entrypoint.validate_environment")
    @patch("src.config.entrypoint.NodeProxyProcess")
    def test_main_exits_on_write_error(
        self,
        mock_node_cls,
        mock_validate,
        mock_load_specs,
        mock_render,
        mock_write,
        monkeypatch,
        capsys,
    ):
        """Test that main exits with error when write_config_file fails."""
        mock_node_instance = MagicMock()
        mock_node_instance.start.return_value.pid = 2023
        mock_node_cls.return_value = mock_node_instance
        mock_load_specs.return_value = [MagicMock()]
        mock_render.return_value = "config: data"
        mock_write.side_effect = Exception("Write failed")

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR: Failed to write configuration file: Write failed" in captured.err
        mock_node_instance.stop.assert_called_once()
        monkeypatch.delenv("NODE_UPSTREAM_PROXY_PID", raising=False)
