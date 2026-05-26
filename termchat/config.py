"""Configuration management — API keys, defaults, and paths."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(os.environ.get("TERMCHAT_CONFIG_DIR", Path.home() / ".config" / "termchat"))
CONFIG_FILE = CONFIG_DIR / "config.json"
DB_FILE = CONFIG_DIR / "termchat.db"

# ── Defaults ─────────────────────────────────────────────────────────────────

PROVIDER_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-6",
}

CONTEXT_CHAR_LIMIT = 50_000   # auto-compress threshold
CONTEXT_KEEP_RECENT = 6       # messages to always preserve from compression


# ── Low-level helpers ────────────────────────────────────────────────────────

def _load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))
    # Restrict to owner read/write only (no group/world access for the key file)
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ── Public API ───────────────────────────────────────────────────────────────

def get_api_key(provider: str = "anthropic") -> str | None:
    """Return the API key for *provider*, checking env vars first."""
    env_var = f"{provider.upper()}_API_KEY"
    if key := os.environ.get(env_var):
        return key
    return _load().get("api_keys", {}).get(provider)


def set_api_key(provider: str, key: str) -> None:
    data = _load()
    data.setdefault("api_keys", {})[provider] = key
    _save(data)


def get_default_model(provider: str = "anthropic") -> str:
    stored = _load().get("default_models", {}).get(provider)
    return stored or PROVIDER_DEFAULTS.get(provider, "claude-sonnet-4-6")


def set_default_model(provider: str, model: str) -> None:
    data = _load()
    data.setdefault("default_models", {})[provider] = model
    _save(data)


def get_default_provider() -> str:
    return _load().get("default_provider", "anthropic")


def set_default_provider(provider: str) -> None:
    data = _load()
    data["default_provider"] = provider
    _save(data)


def all_settings() -> dict:
    data = _load()
    # Redact keys
    if "api_keys" in data:
        data["api_keys"] = {k: "***" for k in data["api_keys"]}
    return data


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
