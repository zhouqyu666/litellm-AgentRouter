"""Tests for admin env_manager module."""

import os
import pytest
from pathlib import Path

from src.admin.env_manager import EnvFile


@pytest.fixture
def env_file(tmp_path):
    """Create a temp .env file for testing."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# Test config\n"
        "PORT=4000\n"
        "LITELLM_MASTER_KEY=sk-master\n"
        "\n"
        "MODEL_DEEPSEEK_UPSTREAM_MODEL=deepseek-v3.2\n"
        "MODEL_DEEPSEEK_REASONING_EFFORT=medium\n"
        "\n"
        "MODEL_GLM_UPSTREAM_MODEL=glm-4.6\n"
        "\n"
        "OPENAI_API_KEYS=sk-key1,sk-key2,sk-key3\n"
    )
    return EnvFile(str(env_path))


class TestRead:
    def test_reads_all_keys(self, env_file):
        data = env_file.read()
        assert data["PORT"] == "4000"
        assert data["LITELLM_MASTER_KEY"] == "sk-master"
        assert data["MODEL_DEEPSEEK_UPSTREAM_MODEL"] == "deepseek-v3.2"

    def test_empty_file_returns_empty(self, tmp_path):
        ef = EnvFile(str(tmp_path / ".env"))
        assert ef.read() == {}


class TestGet:
    def test_get_existing_key(self, env_file):
        assert env_file.get("PORT") == "4000"

    def test_get_missing_key_returns_none(self, env_file):
        assert env_file.get("NONEXISTENT") is None


class TestSet:
    def test_update_existing_key(self, env_file):
        env_file.set("PORT", "8080")
        assert env_file.get("PORT") == "8080"

    def test_add_new_key(self, env_file):
        env_file.set("NEW_KEY", "new_value")
        assert env_file.get("NEW_KEY") == "new_value"

    def test_preserves_comments(self, env_file):
        env_file.set("PORT", "8080")
        raw = env_file.read_raw()
        assert "# Test config" in raw

    def test_set_many(self, env_file):
        env_file.set_many({"PORT": "9000", "NEW_VAR": "val"})
        assert env_file.get("PORT") == "9000"
        assert env_file.get("NEW_VAR") == "val"


class TestDelete:
    def test_delete_by_prefix(self, env_file):
        deleted = env_file.delete("MODEL_DEEPSEEK_")
        assert "MODEL_DEEPSEEK_UPSTREAM_MODEL" in deleted
        assert "MODEL_DEEPSEEK_REASONING_EFFORT" in deleted
        assert env_file.get("MODEL_DEEPSEEK_UPSTREAM_MODEL") is None
        # Other models should remain
        assert env_file.get("MODEL_GLM_UPSTREAM_MODEL") == "glm-4.6"

    def test_delete_exact_key(self, env_file):
        result = env_file.delete_key("PORT")
        assert result is True
        assert env_file.get("PORT") is None

    def test_delete_nonexistent_key(self, env_file):
        result = env_file.delete_key("NONEXISTENT")
        assert result is False


class TestBackup:
    def test_backup_creates_file(self, env_file):
        backup_path = env_file.backup()
        assert backup_path != ""
        assert Path(backup_path).is_file()

    def test_backup_preserves_content(self, env_file):
        original = env_file.read_raw()
        env_file.backup()
        assert env_file.read_raw() == original


class TestAtomicWrite:
    def test_no_tmp_file_left(self, env_file):
        env_file.set("TEST", "value")
        parent = env_file.path.parent
        tmp_files = list(parent.glob("*.tmp"))
        assert len(tmp_files) == 0
