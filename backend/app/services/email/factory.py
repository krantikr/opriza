"""Selects the configured email source.

Note what this deliberately does *not* do: if Gmail is configured but not
authorized, it does not quietly fall back to reading local files. A poller that
silently switches to sample data would report healthy runs while the real
mailbox went unread.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.services.email.gmail_client import GmailClient
from app.services.email.gmail_source import GmailSource
from app.services.email.local_source import LocalFileSource
from app.services.email.source import EmailSource

logger = get_logger(__name__)


def build_gmail_client() -> GmailClient:
    return GmailClient(
        credentials_path=settings.gmail_credentials_path,
        token_path=settings.gmail_token_path,
    )


def get_email_source(override: str | None = None) -> EmailSource:
    """Return the configured source. `override` accepts 'gmail' or 'local'."""
    choice = (override or settings.email_source).strip().lower()

    if choice == "gmail":
        source = GmailSource(build_gmail_client(), query=settings.gmail_query)
        if not source.is_available():
            logger.warning(
                "EMAIL_SOURCE=gmail but no valid token at %s. "
                "Run: uv run python scripts/gmail_auth.py",
                settings.gmail_token_path,
            )
        return source

    return LocalFileSource(settings.local_email_path)
