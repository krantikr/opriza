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


def get_email_source_for(mailbox) -> EmailSource:
    """The source for one organisation's mailbox.

    Per-mailbox rather than per-process: a single credential file in `.env`
    could only ever describe one desk's inbox, which stopped being sufficient
    the moment one deployment served several.

    Credentials come from the mailbox row, decrypted on use and never held on
    the model. `LOCAL` remains available so a desk can be demonstrated, and a
    development environment exercised, without connecting a real Google
    account.
    """
    from app.core.security import decrypt_credential

    if mailbox.provider == "LOCAL":
        return LocalFileSource(settings.local_email_path)

    refresh_token = decrypt_credential(mailbox.refresh_token_enc)
    if not refresh_token:
        # An unavailable source, rather than a fallback to sample data. The
        # poller turns this into "reconnect this mailbox", which is the truth.
        return GmailSource(
            GmailClient(
                credentials_path=settings.gmail_credentials_path,
                token_path=settings.gmail_token_path,
            ),
            query=settings.gmail_query,
        )

    return GmailSource(
        GmailClient(
            credentials_path=settings.gmail_credentials_path,
            token_path=settings.gmail_token_path,
            refresh_token=refresh_token,
        ),
        query=settings.gmail_query,
    )
