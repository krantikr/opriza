"""The LLM client interface.

Everything above this line is provider-agnostic. Swapping OpenRouter for a
direct provider SDK, or adding a second gateway, means writing another subclass
- not touching the classifier, extractor or drafter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

from ai.schemas import AIOutcome

T = TypeVar("T", bound=BaseModel)

Messages = list[dict[str, str]]


class LLMError(RuntimeError):
    """Any failure calling the language model."""


class RateLimitedError(LLMError):
    """The gateway refused the call for load, not for content.

    Distinct from every other `LLMError` because the correct response is
    different in kind: nothing about the request needs changing, so retrying
    variations of it only deepens the overload. Callers should stop, leave the
    work in a retryable state, and let the next scheduled pass pick it up once
    the window has reset.
    """


class StructuredOutputError(LLMError):
    """The model could not produce output matching the required schema.

    Raised only after strict mode, JSON mode and a repair attempt have all
    failed. Callers treat this as "the enquiry needs a human", never as a
    reason to guess.
    """


class LLMClient(ABC):
    @abstractmethod
    def complete(
        self,
        *,
        task: str,
        messages: Messages,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AIOutcome[str]:
        """Free-text completion."""

    @abstractmethod
    def structured(
        self,
        *,
        task: str,
        messages: Messages,
        schema: type[T],
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> AIOutcome[T]:
        """Completion validated against a Pydantic schema."""


def system(content: str) -> dict[str, str]:
    return {"role": "system", "content": content}


def user(content: str) -> dict[str, str]:
    return {"role": "user", "content": content}


def assistant(content: str) -> dict[str, str]:
    return {"role": "assistant", "content": content}
