"""Tests for config.py — API key and settings management."""

from __future__ import annotations

import json

import pytest

import termchat.config as cfg


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect all config I/O to a temp directory for every test."""
    config_dir = tmp_path / "config"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(cfg, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg, "CONFIG_FILE", config_file)
    # Clear any env-var overrides that could bleed in from the real environment
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


class TestApiKey:
    def test_get_api_key_returns_none_when_absent(self):
        assert cfg.get_api_key("anthropic") is None

    def test_set_then_get_api_key(self):
        cfg.set_api_key("anthropic", "sk-test-123")
        assert cfg.get_api_key("anthropic") == "sk-test-123"

    def test_env_var_takes_precedence(self, monkeypatch):
        cfg.set_api_key("anthropic", "from-file")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        assert cfg.get_api_key("anthropic") == "from-env"

    def test_multiple_providers_isolated(self):
        cfg.set_api_key("anthropic", "ant-key")
        cfg.set_api_key("openai", "oai-key")
        assert cfg.get_api_key("anthropic") == "ant-key"
        assert cfg.get_api_key("openai") == "oai-key"

    def test_config_file_created_on_set(self, tmp_path):
        cfg.set_api_key("anthropic", "key")
        assert cfg.CONFIG_FILE.exists()

    def test_config_file_is_valid_json(self):
        cfg.set_api_key("anthropic", "key")
        data = json.loads(cfg.CONFIG_FILE.read_text())
        assert "api_keys" in data


class TestDefaultModel:
    def test_returns_provider_default_when_unset(self):
        model = cfg.get_default_model("anthropic")
        assert model == cfg.PROVIDER_DEFAULTS["anthropic"]

    def test_set_then_get_default_model(self):
        cfg.set_default_model("anthropic", "claude-opus-4-7")
        assert cfg.get_default_model("anthropic") == "claude-opus-4-7"

    def test_unknown_provider_fallback(self):
        model = cfg.get_default_model("unknown-provider")
        assert model == "claude-sonnet-4-6"

    def test_multiple_providers_isolated(self):
        cfg.set_default_model("anthropic", "model-a")
        cfg.set_default_model("openai", "model-b")
        assert cfg.get_default_model("anthropic") == "model-a"
        assert cfg.get_default_model("openai") == "model-b"


class TestDefaultProvider:
    def test_returns_anthropic_when_unset(self):
        assert cfg.get_default_provider() == "anthropic"

    def test_set_then_get_provider(self):
        cfg.set_default_provider("openai")
        assert cfg.get_default_provider() == "openai"


class TestAllSettings:
    def test_api_keys_redacted(self):
        cfg.set_api_key("anthropic", "super-secret-key")
        settings = cfg.all_settings()
        assert settings["api_keys"]["anthropic"] == "***"

    def test_returns_empty_dict_when_no_config(self):
        assert cfg.all_settings() == {}

    def test_model_not_redacted(self):
        cfg.set_default_model("anthropic", "claude-opus-4-7")
        settings = cfg.all_settings()
        assert settings["default_models"]["anthropic"] == "claude-opus-4-7"


class TestCorruptConfig:
    def test_corrupt_json_returns_empty(self, tmp_path):
        cfg.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cfg.CONFIG_FILE.write_text("not valid json {{{")
        assert cfg.get_api_key("anthropic") is None
        assert cfg.get_default_provider() == "anthropic"
