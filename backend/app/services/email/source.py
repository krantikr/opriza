"""The email source port.

Ingestion depends on this interface, never on Gmail directly. Two consequences
that matter in practice:

* The pipeline is fully runnable and demonstrable with zero credentials, using
  the local `.eml` reader.
* Adding Outlook or an IMAP mailbox later is a new implementation of this
  class, not a change to the workflow.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.enums import EmailSourceType
from app.services.email.message import RawEmail


class EmailSourceUnavailable(RuntimeError):
    """Raised when a source is selected but not usable (e.g. no OAuth token)."""


class EmailSource(ABC):
    """Fetches inbound messages from somewhere."""

    source_type: EmailSourceType

    @abstractmethod
    def fetch(self, limit: int = 25) -> list[RawEmail]:
        """Return up to `limit` messages, newest first where the source allows.

        Implementations return *everything* they see and leave deduplication to
        the ingestion service, which owns the database-level uniqueness
        guarantee.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """True if this source can be used right now without user action."""

    def describe(self) -> str:
        return self.source_type.value
