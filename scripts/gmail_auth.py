"""One-time Gmail authorisation.

Prerequisites:
  1. Create a Google Cloud project and enable the Gmail API.
  2. Create OAuth client credentials of type "Desktop app".
  3. Save the downloaded JSON to the path in GMAIL_CREDENTIALS_FILE
     (default: data/secrets/gmail_credentials.json).

Then:
  uv run python scripts/gmail_auth.py

A browser opens for consent and the resulting token is written to
GMAIL_TOKEN_FILE. Only gmail.readonly and gmail.send are requested - the system
never asks for permission to modify or delete mail.
"""

from __future__ import annotations

import sys

from app.core.config import settings
from app.core.logging import get_logger
from app.services.email.factory import build_gmail_client
from app.services.email.gmail_client import SCOPES, GmailAuthError

logger = get_logger("gmail_auth")


def main() -> int:
    client = build_gmail_client()

    print("Gmail authorisation")
    print(f"  client credentials : {settings.gmail_credentials_path}")
    print(f"  token destination  : {settings.gmail_token_path}")
    print("  scopes             :")
    for scope in SCOPES:
        print(f"      {scope}")
    print()

    if client.is_authorized():
        profile = client.get_profile()
        print(f"Already authorised as {profile.get('emailAddress')}.")
        print("Delete the token file and re-run to authorise a different account.")
        return 0

    try:
        client.authorize()
    except GmailAuthError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator
        logger.error("Authorisation failed: %s", exc)
        return 1

    profile = client.get_profile()
    print(f"\nAuthorised as {profile.get('emailAddress')}")
    print(f"Messages in mailbox: {profile.get('messagesTotal')}")
    print("\nSet EMAIL_SOURCE=gmail in .env to ingest from this mailbox.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
