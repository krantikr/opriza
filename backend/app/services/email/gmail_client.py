"""Thin, testable wrapper over the Gmail API.

Two rules shape this module:

* **Least privilege.** Only `gmail.readonly` and `gmail.send` are requested.
  The system never needs to modify or delete a customer's mail, so it never
  asks for permission to.
* **Never prompt during background work.** Interactive consent happens once,
  in `scripts/gmail_auth.py`. Everything else loads the stored token and, if it
  is missing or unrecoverable, reports the source as unavailable rather than
  blocking a poller on a browser window that nobody is looking at.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Least-privilege scopes (spec section 19). Changing this list invalidates the
# stored token and requires re-running scripts/gmail_auth.py.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailAuthError(RuntimeError):
    """Raised when Gmail credentials are absent, invalid or unrecoverable."""


def b64url_decode(data: str | None) -> bytes:
    if not data:
        return b""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


class GmailClient:
    """Authenticated access to one Gmail mailbox."""

    def __init__(
        self,
        credentials_path: Path,
        token_path: Path,
        refresh_token: str | None = None,
    ) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        #: Supplied per organisation by `get_email_source_for`. When set, it
        #: is used in preference to the token file: one shared file on disk
        #: cannot represent several desks' mailboxes.
        self.refresh_token = refresh_token
        self._service: Any = None

    # --- Credentials ------------------------------------------------------

    def load_credentials(self):
        """Load and silently refresh the stored token. Never prompts.

        Returns None when no usable credentials exist.
        """
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if self.refresh_token:
            return self._credentials_from_refresh_token()

        if not self.token_path.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
        except (ValueError, KeyError) as exc:
            logger.error("Gmail token file is malformed (%s): %s", self.token_path, exc)
            return None

        if creds.valid:
            return creds

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                logger.error("Gmail token refresh failed - re-run scripts/gmail_auth.py: %s", exc)
                return None
            self._write_token(creds)
            return creds

        return None

    def _credentials_from_refresh_token(self):
        """Build credentials for one organisation's stored refresh token.

        The client id and secret still come from the application's own
        credentials file - they identify Steel Desk to Google, and are the
        same for every desk. Only the refresh token is per-organisation.
        """
        import json

        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if not self.credentials_path.exists():
            logger.error(
                "No Google client credentials at %s; mailboxes cannot connect.",
                self.credentials_path,
            )
            return None

        try:
            blob = json.loads(self.credentials_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Google client credentials are unreadable: %s", exc)
            return None

        client = blob.get("installed") or blob.get("web") or {}
        creds = Credentials(
            token=None,
            refresh_token=self.refresh_token,
            token_uri=client.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=client.get("client_id"),
            client_secret=client.get("client_secret"),
            scopes=SCOPES,
        )
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            # Google expires refresh tokens. The desk must reconnect; saying
            # so is more useful than a stack trace in a log nobody reads.
            logger.warning("Mailbox refresh token is no longer valid: %s", exc)
            return None
        return creds

    def authorize(self, port: int = 0):
        """Run the interactive installed-app OAuth flow and store the token.

        Called only from `scripts/gmail_auth.py`.
        """
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.credentials_path.exists():
            raise GmailAuthError(
                f"OAuth client file not found: {self.credentials_path}\n"
                "Create a Google Cloud project, enable the Gmail API, create "
                "'Desktop app' OAuth client credentials, and save the downloaded "
                "JSON to that path."
            )

        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), SCOPES)
        creds = flow.run_local_server(port=port, prompt="consent")
        self._write_token(creds)
        return creds

    def _write_token(self, creds) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        # Token grants mailbox access; keep it off other users' hands where the
        # platform supports it.
        try:
            self.token_path.chmod(0o600)
        except OSError:  # pragma: no cover - Windows ACLs differ
            pass
        logger.info("Gmail token stored at %s", self.token_path)

    # --- Service ----------------------------------------------------------

    @property
    def service(self):
        if self._service is None:
            creds = self.load_credentials()
            if creds is None:
                raise GmailAuthError(
                    "Gmail is not authorized. Run: uv run python scripts/gmail_auth.py"
                )
            from googleapiclient.discovery import build

            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def is_authorized(self) -> bool:
        return self.load_credentials() is not None

    # --- Read -------------------------------------------------------------

    def get_profile(self) -> dict[str, Any]:
        return self.service.users().getProfile(userId="me").execute()

    def list_message_ids(self, query: str, max_results: int = 25) -> list[str]:
        """List message ids matching a Gmail search query, newest first."""
        response = (
            self.service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        return [m["id"] for m in response.get("messages", [])]

    def get_message(self, message_id: str) -> dict[str, Any]:
        return (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )

    def get_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = (
            self.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        return b64url_decode(response.get("data"))

    # --- Send -------------------------------------------------------------

    def send(self, mime_bytes: bytes, thread_id: str | None = None) -> dict[str, Any]:
        """Send a prepared MIME message, optionally within an existing thread."""
        body: dict[str, Any] = {"raw": b64url_encode(mime_bytes)}
        if thread_id:
            body["threadId"] = thread_id
        return self.service.users().messages().send(userId="me", body=body).execute()
