"""Sending a follow-up nudge on a quotation that already went out.

Mirrors the guardrail shape in `approval.py`: the only function that sends a
follow-up is `FollowUpService.send`, and it refuses anything that is not
already `SENT`. There is no draft/approve step here - a follow-up is a
low-stakes nudge on a quote a human already approved once, not a new offer -
but it still records what was sent and threads onto the original
conversation rather than starting a new one.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models import FollowUp, QuotationRequest, QuotationStatus
from app.services import audit
from app.services.email.sender import EmailSender, SendResult, get_sender, reply_to

logger = get_logger(__name__)


class FollowUpError(RuntimeError):
    """The requested follow-up is not valid for this quotation's current state."""


def default_subject(quotation: QuotationRequest) -> str:
    original = quotation.email.subject if quotation.email else None
    if original and not original.lower().startswith("re:"):
        return f"Re: {original}"
    return original or f"Following up on {quotation.quotation_number}"


def default_body(quotation: QuotationRequest) -> str:
    from app.core.config import settings

    name = quotation.customer_name_raw or quotation.customer_company_raw or "there"
    sent_date = quotation.sent_at.strftime("%d %b %Y") if quotation.sent_at else "recently"

    return (
        f"Dear {name},\n\n"
        f"Following up on quotation {quotation.quotation_number}, sent on {sent_date}. "
        "Wanted to check if you had a chance to review it and see if you have any "
        "questions, or would like to go ahead.\n\n"
        "Happy to help with anything you need.\n\n"
        "Regards,\n"
        f"{settings.company_signatory}\n"
        f"{settings.company_name}"
    )


@dataclass(slots=True)
class FollowUpResult:
    follow_up: FollowUp
    send: SendResult

    @property
    def sent(self) -> bool:
        return self.send.sent


class FollowUpService:
    def __init__(self, db: Session, sender: EmailSender | None = None) -> None:
        self.db = db
        self.sender = sender or get_sender()

    def send(
        self,
        quotation: QuotationRequest,
        *,
        user_id: int | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> FollowUpResult:
        if quotation.status != QuotationStatus.SENT:
            raise FollowUpError(
                f"{quotation.quotation_number} is {quotation.status.value}, not SENT. "
                "A follow-up can only be sent after the quotation itself has gone out."
            )

        final_subject = subject if subject is not None else default_subject(quotation)
        final_body = body if body is not None else default_body(quotation)

        result = reply_to(
            quotation.email, subject=final_subject, body=final_body, sender=self.sender
        )

        follow_up = FollowUp(
            quotation_request_id=quotation.id,
            user_id=user_id,
            subject=final_subject,
            body=final_body,
            sent=result.sent,
            sent_message_id=result.message_id,
            error=result.error,
        )
        self.db.add(follow_up)

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="FOLLOW_UP_SENT" if result.sent else "FOLLOW_UP_FAILED",
            user_id=user_id,
            details={
                "quotation_number": quotation.quotation_number,
                "destination": result.destination,
                "sent_message_id": result.message_id,
                "error": result.error,
            },
        )
        self.db.commit()

        logger.info(
            "%s follow-up %s via %s",
            quotation.quotation_number,
            "sent" if result.sent else f"FAILED ({result.error})",
            self.sender.describe(),
        )
        return FollowUpResult(follow_up=follow_up, send=result)
