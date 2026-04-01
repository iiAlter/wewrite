#!/usr/bin/env python3
"""
Config loader with environment variable support.
Reads config.yaml but allows environment variables to override sensitive values.

Environment variables:
  WEWRITE_WECHAT_APPID
  WEWRITE_WECHAT_SECRET
  WEWRITE_LLM_API_KEY
  WEWRITE_IMAGE_API_KEY
  WEWRITE_CONFIG_PATH  (optional, path to config.yaml)
"""

import os
from pathlib import Path
from functools import lru_cache

import yaml


# Config file search order
CONFIG_PATHS = [
    Path.cwd() / "config.yaml",
    Path(__file__).parent.parent / "config.yaml",
    Path(__file__).parent / "config.yaml",
    Path.home() / ".config" / "wewrite" / "config.yaml",
    os.environ.get("WEWRITE_CONFIG_PATH", ""),
]

# Env var overrides
ENV_OVERRIDES = {
    ("wechat", "appid"): "WEWRITE_WECHAT_APPID",
    ("wechat", "secret"): "WEWRITE_WECHAT_SECRET",
    ("llm", "api_key"): "WEWRITE_LLM_API_KEY",
    ("image", "api_key"): "WEWRITE_IMAGE_API_KEY",
}


def _load_yaml() -> dict:
    for p in CONFIG_PATHS:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    return {}


def _apply_env_overrides(cfg: dict) -> dict:
    """Override config values with environment variables."""
    for (section, key), env_var in ENV_OVERRIDES.items():
        value = os.environ.get(env_var)
        if value:
            if section not in cfg:
                cfg[section] = {}
            cfg[section][key] = value
    return cfg


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Load config with env var overrides. Cached."""
    cfg = _load_yaml()
    return _apply_env_overrides(cfg)


def get(section: str, key: str, default=None):
    """Get a config value, checking env vars first."""
    env_key = f"WEWRITE_{section.upper()}_{key.upper()}"
    if env_key in os.environ:
        return os.environ[env_key]
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)
