"""Outbound email.

Correct threading is the detail that separates a reply from a stray new
message. Gmail groups by `threadId`, but the customer's mail client groups by
the `In-Reply-To` and `References` headers, so both are set. Without them the
customer sees an unconnected email that does not sit under their own enquiry.

Like ingestion, sending goes through a port. `LocalFileSender` writes the
message to disk instead, so the approve-and-send path is exercisable end to end
without Gmail credentials and without mailing a real customer during a demo.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.core.paths import DATA_DIR
from app.models import Email
from app.services.email.gmail_client import GmailAuthError, GmailClient

logger = get_logger(__name__)


@dataclass(slots=True)
class SendResult:
    sent: bool
    message_id: str | None = None
    thread_id: str | None = None
    error: str | None = None
    destination: str | None = None


@dataclass(slots=True)
class Attachment:
    """A file to send alongside the body."""

    filename: str
    content: bytes
    mime_type: str = "application/pdf"


def build_reply(
    *,
    to_address: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[Attachment] | None = None,
) -> EmailMessage:
    """Build a reply that threads correctly.

    With `html_body` the message goes out as `multipart/alternative`: the plain
    text is what the reviewer approved and remains the real content, and the
    HTML is the same thing with the item table drawn as a table. Clients that
    refuse HTML - and anyone reading on a watch or a screen reader - still get
    a body with every figure in it, in aligned columns.
    """
    message = EmailMessage()
    message["To"] = to_address
    message["From"] = formataddr((settings.company_name, settings.company_email))
    message["Subject"] = subject
    message["Message-ID"] = make_msgid()
    message["Date"] = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S +0000")

    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        # References accumulates the thread; append rather than replace.
        message["References"] = f"{references} {in_reply_to}".strip() if references else in_reply_to

    message.set_content(body)
    if html_body:
        # add_alternative orders the parts text-then-html, which is what the
        # MIME spec asks for: the richest acceptable part is the last one.
        message.add_alternative(html_body, subtype="html")

    # Attachments go on *after* the alternatives. Adding one promotes the
    # message to multipart/mixed with the text/html pair intact underneath;
    # attaching first would leave the body as a sibling of the file rather
    # than as the message the file belongs to.
    for item in attachments or []:
        maintype, _, subtype = item.mime_type.partition("/")
        message.add_attachment(
            item.content,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=item.filename,
        )
    return message


class EmailSender(ABC):
    @abstractmethod
    def send(self, message: EmailMessage, thread_id: str | None = None) -> SendResult: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    def describe(self) -> str:
        return type(self).__name__


class GmailSender(EmailSender):
    def __init__(self, client: GmailClient) -> None:
        self.client = client

    def is_available(self) -> bool:
        return self.client.is_authorized()

    def describe(self) -> str:
        return "Gmail"

    def send(self, message: EmailMessage, thread_id: str | None = None) -> SendResult:
        try:
            response = self.client.send(message.as_bytes(), thread_id=thread_id)
        except GmailAuthError as exc:
            return SendResult(sent=False, error=f"Gmail is not authorised: {exc}")
        except Exception as exc:  # noqa: BLE001 - reported to the reviewer, not raised
            logger.error("Gmail send failed: %s", exc)
            return SendResult(sent=False, error=str(exc))

        return SendResult(
            sent=True,
            message_id=response.get("id"),
            thread_id=response.get("threadId"),
            destination="Gmail",
        )


class LocalFileSender(EmailSender):
    """Writes the message to `data/sent/` instead of transmitting it.

    Used when EMAIL_SOURCE is local. A demo that "sends" should not put mail in
    a real customer's inbox, and a developer should be able to read exactly what
    would have gone out.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or (DATA_DIR / "sent")

    def is_available(self) -> bool:
        return True

    def describe(self) -> str:
        return f"local files in {self.directory}"

    def send(self, message: EmailMessage, thread_id: str | None = None) -> SendResult:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        path = self.directory / f"{stamp}.eml"
        path.write_bytes(message.as_bytes())
        logger.info("Wrote outbound message to %s", path)
        return SendResult(
            sent=True,
            message_id=message["Message-ID"],
            thread_id=thread_id,
            destination=str(path),
        )


def get_sender(override: str | None = None) -> EmailSender:
    """Pick the sender matching the configured email source."""
    choice = (override or settings.email_source).strip().lower()
    if choice == "gmail":
        from app.services.email.factory import build_gmail_client

        return GmailSender(build_gmail_client())
    return LocalFileSender()


def reply_to(
    email: Email,
    *,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[Attachment] | None = None,
    sender: EmailSender,
) -> SendResult:
    """Send a reply to an ingested email, on its original thread."""
    if not email.sender_email:
        return SendResult(sent=False, error="The original email has no sender address.")

    message = build_reply(
        to_address=email.sender_email,
        subject=subject,
        body=body,
        html_body=html_body,
        attachments=attachments,
        in_reply_to=email.rfc822_message_id,
        references=email.rfc822_message_id,
    )
    return sender.send(message, thread_id=email.thread_id)
