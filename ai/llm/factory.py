"""Client construction.

One client per process: the underlying HTTP client pools connections, and
rebuilding it per call would add a TCP and TLS handshake to every email.
"""

from __future__ import annotations

from functools import lru_cache

from ai.config import LLMConfig
from ai.llm.base import LLMClient
from ai.llm.openrouter import OpenRouterClient


@lru_cache(maxsize=1)
def get_client() -> LLMClient:
    """The shared client, configured from the environment."""
    return OpenRouterClient(LLMConfig.from_env())


def build_client(config: LLMConfig) -> LLMClient:
    """An explicitly configured client, for tests and overrides."""
    return OpenRouterClient(config)


def reset_client() -> None:
    """Drop the cached client so a configuration change takes effect."""
    get_client.cache_clear()
