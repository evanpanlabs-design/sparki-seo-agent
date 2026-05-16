"""LLM configuration and client for Master Agent.

Allows users to provide their own LLM API credentials.
"""

import json
import logging
import os
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class LLMConfig(TypedDict):
    """LLM configuration."""
    api_url: str
    api_key: str
    model: str
    max_tokens: int


class LLMClient:
    """LLM client with user-provided credentials."""

    def __init__(self, config_path: str | None = None):
        self.config_path = Path(config_path) if config_path else Path("configs/config.local.yaml")
        self._config: LLMConfig | None = None

    def configure(self, api_url: str, api_key: str, model: str = "gpt-4o-mini", max_tokens: int = 2048) -> bool:
        """Configure LLM credentials."""
        self._config = LLMConfig(
            api_url=api_url,
            api_key=api_key,
            model=model,
            max_tokens=max_tokens
        )
        return self._save_config()

    def _save_config(self) -> bool:
        """Save config to file."""
        try:
            config_dir = self.config_path.parent
            config_dir.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "llm": dict(self._config)
                }, f, ensure_ascii=False, indent=2)
            logger.info("LLM config saved")
            return True
        except Exception as e:
            logger.error(f"Failed to save LLM config: {e}")
            return False

    def load_config(self) -> bool:
        """Load config from file."""
        if not self.config_path.exists():
            return False
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                llm_config = data.get("llm", {})
                self._config = LLMConfig(
                    api_url=llm_config.get("api_url", ""),
                    api_key=llm_config.get("api_key", ""),
                    model=llm_config.get("model", "gpt-4o-mini"),
                    max_tokens=llm_config.get("max_tokens", 2048)
                )
                return True
        except Exception as e:
            logger.error(f"Failed to load LLM config: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if LLM is configured."""
        return self._config is not None and bool(self._config["api_url"] and self._config["api_key"])

    def generate(self, prompt: str, system: str = "") -> str | None:
        """Generate text using configured LLM (Anthropic-compatible API)."""
        if not self.is_configured():
            logger.error("LLM not configured")
            return None

        try:
            import requests
            headers = {
                "Authorization": f"Bearer {self._config['api_key']}",
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01"
            }

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            # Use /messages endpoint (Anthropic-native format)
            url = f"{self._config['api_url'].rstrip('/')}/messages"

            resp = requests.post(
                url,
                headers=headers,
                json={
                    "model": self._config["model"],
                    "messages": messages,
                    "max_tokens": self._config["max_tokens"]
                },
                timeout=60
            )

            if resp.status_code == 200:
                data = resp.json()
                # Extract text from response content blocks
                content = data.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            return block["text"]
                return str(content)
            else:
                logger.error(f"LLM request failed: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return None


_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    """Get global LLM client instance."""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
        _llm_client.load_config()
    return _llm_client