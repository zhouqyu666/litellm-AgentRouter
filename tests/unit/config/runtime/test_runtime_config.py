#!/usr/bin/env python3
"""Unit tests for RuntimeConfig centralized configuration object."""

from __future__ import annotations

import os

import pytest

from src.config.config import MissingSettingError, RuntimeConfig, runtime_config


class TestRuntimeConfigBasics:
    """Test basic RuntimeConfig initialization and accessors."""

    def test_get_str_returns_env_value(self, monkeypatch):
        """Test get_str retrieves string values from environment."""
        monkeypatch.setenv("TEST_KEY", "test_value")
        config = RuntimeConfig()
        assert config.get_str("TEST_KEY") == "test_value"

    def test_get_str_returns_default_when_missing(self):
        """Test get_str returns default when key is missing."""
        config = RuntimeConfig()
        assert config.get_str("NONEXISTENT_KEY", "default") == "default"

    def test_get_str_returns_none_when_missing_no_default(self):
        """Test get_str returns None when key missing and no default."""
        config = RuntimeConfig()
        assert config.get_str("NONEXISTENT_KEY") is None

    def test_get_int_returns_integer(self, monkeypatch):
        """Test get_int parses integer values."""
        monkeypatch.setenv("TEST_PORT", "8080")
        config = RuntimeConfig()
        assert config.get_int("TEST_PORT") == 8080

    def test_get_int_returns_default_when_missing(self):
        """Test get_int returns default when key is missing."""
        config = RuntimeConfig()
        assert config.get_int("NONEXISTENT_PORT", 3000) == 3000

    def test_get_int_raises_on_invalid_int(self, monkeypatch):
        """Test get_int raises ValueError for non-integer values."""
        monkeypatch.setenv("BAD_INT", "not_a_number")
        config = RuntimeConfig()
        with pytest.raises(ValueError, match="invalid literal"):
            config.get_int("BAD_INT")

    def test_get_bool_returns_true_for_truthy_values(self, monkeypatch):
        """Test get_bool recognizes truthy string values."""
        for value in ["1", "true", "TRUE", "yes", "YES", "on", "ON"]:
            monkeypatch.setenv("TEST_BOOL", value)
            config = RuntimeConfig()
            assert config.get_bool("TEST_BOOL") is True

    def test_get_bool_returns_false_for_falsy_values(self, monkeypatch):
        """Test get_bool recognizes falsy string values."""
        for value in ["0", "false", "FALSE", "no", "NO", "off", "OFF", ""]:
            monkeypatch.setenv("TEST_BOOL", value)
            config = RuntimeConfig()
            assert config.get_bool("TEST_BOOL") is False

    def test_get_bool_returns_default_when_missing(self):
        """Test get_bool returns default when key is missing."""
        config = RuntimeConfig()
        assert config.get_bool("NONEXISTENT_BOOL", True) is True
        assert config.get_bool("NONEXISTENT_BOOL", False) is False

    def test_require_returns_value_when_present(self, monkeypatch):
        """Test require returns value when key exists."""
        monkeypatch.setenv("REQUIRED_KEY", "required_value")
        config = RuntimeConfig()
        assert config.require("REQUIRED_KEY") == "required_value"

    def test_require_raises_missing_setting_error(self):
        """Test require raises MissingSettingError when key absent."""
        config = RuntimeConfig()
        with pytest.raises(MissingSettingError, match="MISSING_REQUIRED_KEY"):
            config.require("MISSING_REQUIRED_KEY")

    def test_require_with_cast_int(self, monkeypatch):
        """Test require with integer cast."""
        monkeypatch.setenv("REQUIRED_INT", "42")
        config = RuntimeConfig()
        assert config.require("REQUIRED_INT", cast=int) == 42

    def test_as_dict_returns_environment_dict(self, monkeypatch):
        """Test as_dict returns effective environment as dictionary."""
        monkeypatch.setenv("KEY1", "value1")
        monkeypatch.setenv("KEY2", "value2")
        config = RuntimeConfig()
        env_dict = config.as_dict()
        assert isinstance(env_dict, dict)
        assert env_dict["KEY1"] == "value1"
        assert env_dict["KEY2"] == "value2"


class TestRuntimeConfigDotenvLoading:
    """Test .env file loading behavior."""

    def test_ensure_loaded_loads_dotenv_once(self, tmp_path, monkeypatch):
        """Test ensure_loaded loads .env file idempotently."""
        env_file = tmp_path / ".env"
        env_file.write_text("DOTENV_TEST=loaded\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DOTENV_TEST", raising=False)

        config = RuntimeConfig()
        assert config._loaded is False

        config.ensure_loaded()
        assert config._loaded is True
        assert os.getenv("DOTENV_TEST") == "loaded"

        # Second call should not reload
        env_file.write_text("DOTENV_TEST=reloaded\n")
        config.ensure_loaded()
        assert os.getenv("DOTENV_TEST") == "loaded"  # Still original value

    def test_ensure_loaded_skips_when_skip_dotenv_set(self, tmp_path, monkeypatch):
        """Test ensure_loaded respects SKIP_DOTENV environment variable."""
        env_file = tmp_path / ".env"
        env_file.write_text("SHOULD_NOT_LOAD=true\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SKIP_DOTENV", "1")
        monkeypatch.delenv("SHOULD_NOT_LOAD", raising=False)

        config = RuntimeConfig()
        config.ensure_loaded()

        assert os.getenv("SHOULD_NOT_LOAD") is None
        assert config._loaded is True  # Marked as loaded even though skipped

    def test_ensure_loaded_searches_multiple_paths(self, tmp_path, monkeypatch):
        """Test ensure_loaded checks both script dir and cwd for .env."""
        # Create .env in current directory
        cwd_env = tmp_path / ".env"
        cwd_env.write_text("CWD_VAR=from_cwd\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("CWD_VAR", raising=False)

        config = RuntimeConfig()
        config.ensure_loaded()

        assert os.getenv("CWD_VAR") == "from_cwd"

    def test_dotenv_does_not_override_existing_env(self, tmp_path, monkeypatch):
        """Test .env values don't override existing environment variables."""
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_VAR=from_dotenv\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EXISTING_VAR", "from_env")

        config = RuntimeConfig()
        config.ensure_loaded()

        assert os.getenv("EXISTING_VAR") == "from_env"


class TestRuntimeConfigOverrides:
    """Test config override mechanisms for testing."""

    def test_with_overrides_returns_new_config(self, monkeypatch):
        """Test with_overrides creates new config with temporary values."""
        monkeypatch.setenv("ORIGINAL", "original_value")
        base_config = RuntimeConfig()

        override_config = base_config.with_overrides(
            ORIGINAL="overridden",
            NEW_KEY="new_value"
        )

        # Override config sees overridden values
        assert override_config.get_str("ORIGINAL") == "overridden"
        assert override_config.get_str("NEW_KEY") == "new_value"

        # Original config unchanged
        assert base_config.get_str("ORIGINAL") == "original_value"
        assert base_config.get_str("NEW_KEY") is None

    def test_override_context_manager(self, monkeypatch):
        """Test override context manager temporarily modifies config."""
        monkeypatch.setenv("TEST_VAR", "original")
        config = RuntimeConfig()

        assert config.get_str("TEST_VAR") == "original"

        with config.override({"TEST_VAR": "temporary"}):
            assert config.get_str("TEST_VAR") == "temporary"

        # Restored after context
        assert config.get_str("TEST_VAR") == "original"

    def test_override_context_manager_with_new_keys(self):
        """Test override context manager adds temporary keys."""
        config = RuntimeConfig()

        assert config.get_str("TEMP_KEY") is None

        with config.override({"TEMP_KEY": "temp_value"}):
            assert config.get_str("TEMP_KEY") == "temp_value"

        assert config.get_str("TEMP_KEY") is None


class TestRuntimeConfigSingleton:
    """Test runtime_config singleton behavior."""

    def test_runtime_config_singleton_exists(self):
        """Test runtime_config singleton is accessible."""
        assert runtime_config is not None
        assert isinstance(runtime_config, RuntimeConfig)

    def test_runtime_config_is_shared_instance(self):
        """Test runtime_config is shared across imports."""
        from src.config.config import runtime_config as imported_again
        assert runtime_config is imported_again

    def test_runtime_config_ensure_loaded_is_idempotent(self, tmp_path, monkeypatch):
        """Test calling ensure_loaded multiple times on singleton is safe."""
        env_file = tmp_path / ".env"
        env_file.write_text("SINGLETON_TEST=value\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("SINGLETON_TEST", raising=False)

        # Clear loaded state for test
        runtime_config._loaded = False

        runtime_config.ensure_loaded()
        runtime_config.ensure_loaded()
        runtime_config.ensure_loaded()

        assert os.getenv("SINGLETON_TEST") == "value"


class TestMissingSettingError:
    """Test MissingSettingError exception."""

    def test_missing_setting_error_message(self):
        """Test MissingSettingError includes key name in message."""
        error = MissingSettingError("MY_REQUIRED_KEY")
        assert "MY_REQUIRED_KEY" in str(error)

    def test_missing_setting_error_is_exception(self):
        """Test MissingSettingError is an Exception."""
        error = MissingSettingError("KEY")
        assert isinstance(error, Exception)

    def test_as_dict_with_overrides_merges(self):
        """Test as_dict includes override values merged with environment."""
        config = RuntimeConfig(overrides={"OVERRIDE_X": "val_x"})
        env_dict = config.as_dict()
        assert env_dict["OVERRIDE_X"] == "val_x"

    def test_override_with_existing_overrides(self):
        """Test override() merges with pre-existing overrides."""
        config = RuntimeConfig(overrides={"PRE_EXISTING": "original"})
        with config.override({"NEW_TEMP": "temp_value"}):
            assert config.get_str("PRE_EXISTING") == "original"
            assert config.get_str("NEW_TEMP") == "temp_value"
        assert config.get_str("NEW_TEMP") is None

    def test_override_context_manager_cleanup_on_exception(self):
        """Test that override context manager cleans up properly on exception."""
        config = RuntimeConfig()

        with pytest.raises(RuntimeError):
            with config.override({"TEST_KEY": "test_value"}):
                raise RuntimeError("Test exception")

        # After exception, should return to original state
        assert config.get_str("TEST_KEY") is None
