"""Configuration loader for Sparki SEO Blog Agent.

Loads config from configs/config.local.yaml (gitignored) with fallback to config.example.yaml.
"""

import os
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).parent.parent / "configs"
LOCAL_CONFIG = CONFIG_DIR / "config.local.yaml"
EXAMPLE_CONFIG = CONFIG_DIR / "config.example.yaml"


def load_config() -> dict[str, Any]:
    """Load configuration from YAML file.

    Priority: config.local.yaml > config.example.yaml
    """
    # Try local config first
    if LOCAL_CONFIG.exists():
        config_path = LOCAL_CONFIG
    elif EXAMPLE_CONFIG.exists():
        config_path = EXAMPLE_CONFIG
    else:
        raise FileNotFoundError(
            f"No config file found. Please create {LOCAL_CONFIG} or {EXAMPLE_CONFIG}"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Global config instance
_config: dict[str, Any] | None = None


def get_config() -> dict[str, Any]:
    """Get cached config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_gcp_config() -> dict[str, str]:
    """Get GCP configuration."""
    return get_config().get("gcp", {})


def get_gcs_bucket_name() -> str:
    """Get GCS bucket name from config."""
    gcp_config = get_gcp_config()
    bucket = gcp_config.get("gcs_bucket_name", "")
    if not bucket:
        # Fallback to env var
        bucket = os.environ.get("GCS_BUCKET_NAME", "")
    return bucket


def get_storage_config() -> dict[str, str]:
    """Get storage configuration."""
    return get_config().get("storage", {})


def get_video_config() -> dict[str, Any]:
    """Get video processing configuration."""
    return get_config().get("video", {})