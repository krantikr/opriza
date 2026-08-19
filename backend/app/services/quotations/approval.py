"""Human approval and sending (spec section 17).

Guardrail Rule 4 lives here, structurally rather than as a flag: **the only
function in this system that sends a quotation is `approve_and_send`, and it
cannot be reached except by an explicit human action that writes an `Approval`
row first.** There is no scheduled job, no workflow node and no configuration
value that routes to it. `AUTO_SEND_ENABLED` exists so the intent is auditable,
and is asserted against - not consulted.

Every decision records both the text the model proposed and the text actually
sent. The difference between them is the edit-rate metric, and more importantly
it is the only honest record of what the customer received.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import utcnow
from app.core.logging import get_logger
from app.models import (
    Approval,
    ApprovalAction,
    DraftStatus,
    QuotationDraft,
    QuotationRequest,
    QuotationStatus,
)
from app.services import audit
from app.services.email.sender import EmailSender, SendResult, get_sender

logger = get_logger(__name__)

# Statuses from which a quotation may still be acted on.
OPEN_STATUSES = {
    QuotationStatus.READY_FOR_REVIEW,
    QuotationStatus.NEEDS_INFORMATION,
    QuotationStatus.EDITED,
    QuotationStatus.PROCESSING,
    # A courtesy reply was drafted after the customer declined; it still
    # needs the same human approval before anything sends.
    QuotationStatus.CUSTOMER_DECLINED,
}


class ApprovalError(RuntimeError):
    """The requested action is not valid for this quotation's current state."""


@dataclass(slots=True)
class ApprovalResult:
    quotation: QuotationRequest
    action: ApprovalAction
    send: SendResult | None = None
    draft: QuotationDraft | None = None

    @property
    def sent(self) -> bool:
        return bool(self.send and self.send.sent)


class ApprovalService:
    def __init__(self, db: Session, sender: EmailSender | None = None) -> None:
        self.db = db
        self.sender = sender or get_sender()

    # --- Guards -----------------------------------------------------------

    @staticmethod
    def _require_open(quotation: QuotationRequest) -> None:
        if quotation.status not in OPEN_STATUSES:
            raise ApprovalError(
                f"{quotation.quotation_number} is {quotation.status.value} and can no longer be actioned."
            )

    def _require_draft(self, quotation: QuotationRequest) -> QuotationDraft:
        draft = quotation.current_draft
        if draft is None:
            raise ApprovalError(
                f"{quotation.quotation_number} has no draft to act on. "
                "Regenerate one, or resolve the review notes first."
            )
        return draft

    # --- Actions ----------------------------------------------------------

    def edit_draft(
        self,
        quotation: QuotationRequest,
        *,
        subject: str,
        body: str,
        user_id: int | None = None,
        comments: str | None = None,
    ) -> ApprovalResult:
        """Save a reviewer's edits without sending."""
        self._require_open(quotation)
        draft = self._require_draft(quotation)

        original_subject, original_body = draft.subject, draft.body
        draft.subject = subject
        draft.body = body
        draft.status = DraftStatus.EDITED
        quotation.status = QuotationStatus.EDITED

        self.db.add(
            Approval(
                quotation_draft_id=draft.id,
                user_id=user_id,
                action=ApprovalAction.EDIT,
                comments=comments,
                original_subject=original_subject,
                original_body=original_body,
                final_subject=subject,
                final_body=body,
                was_edited=body != original_body or subject != original_subject,
                acted_at=utcnow(),
            )
        )
        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="DRAFT_EDITED",
            user_id=user_id,
            details={"quotation_number": quotation.quotation_number, "draft_version": draft.version},
        )
        self.db.commit()
        return ApprovalResult(quotation=quotation, action=ApprovalAction.EDIT, draft=draft)

    def reject(
        self,
        quotation: QuotationRequest,
        *,
        reason: str | None = None,
        user_id: int | None = None,
    ) -> ApprovalResult:
        self._require_open(quotation)
        draft = quotation.current_draft

        if draft is not None:
            draft.status = DraftStatus.REJECTED
            self.db.add(
                Approval(
                    quotation_draft_id=draft.id,
                    user_id=user_id,
                    action=ApprovalAction.REJECT,
                    comments=reason,
                    original_subject=draft.subject,
                    original_body=draft.body,
                    acted_at=utcnow(),
                )
            )

        quotation.status = QuotationStatus.REJECTED
        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="REJECTED",
            user_id=user_id,
            details={"quotation_number": quotation.quotation_number, "reason": reason},
        )
        self.db.commit()
        return ApprovalResult(quotation=quotation, action=ApprovalAction.REJECT, draft=draft)

    def approve_and_send(
        self,
        quotation: QuotationRequest,
        *,
        user_id: int | None = None,
        subject: str | None = None,
        body: str | None = None,
        comments: str | None = None,
    ) -> ApprovalResult:
        """Record a human approval, then send. In that order.

        `subject` and `body` allow a reviewer to approve with final edits in one
        action; what is stored as `final_body` is what actually goes out.
        """
        assert not settings.auto_send_enabled, (
            "AUTO_SEND_ENABLED is set, but this build has no automatic send path. "
            "Sending requires a recorded human approval (spec Rule 4)."
        )

        self._require_open(quotation)
        draft = self._require_draft(quotation)

        original_subject, original_body = draft.subject, draft.body
        final_subject = subject if subject is not None else draft.subject
        final_body = body if body is not None else draft.body

        if not final_subject or not final_body:
            raise ApprovalError("The draft has no subject or body to send.")

        approval = Approval(
            quotation_draft_id=draft.id,
            user_id=user_id,
            action=ApprovalAction.APPROVE,
            comments=comments,
            original_subject=original_subject,
            original_body=original_body,
            final_subject=final_subject,
            final_body=final_body,
            was_edited=(final_body != original_body or final_subject != original_subject),
            acted_at=utcnow(),
        )
        self.db.add(approval)

        draft.subject = final_subject
        draft.body = final_body
        draft.status = DraftStatus.APPROVED
        quotation.status = QuotationStatus.APPROVED
        self.db.commit()

        # --- Send -----------------------------------------------------------
        from app.services.email.sender import reply_to

        result = reply_to(
            quotation.email, subject=final_subject, body=final_body, sender=self.sender
        )

        if result.sent:
            draft.status = DraftStatus.SENT
            quotation.status = QuotationStatus.SENT
            quotation.sent_at = utcnow()
            quotation.sent_message_id = result.message_id
            quotation.send_error = None
            self._schedule_follow_up(quotation)
        else:
            # Approval stands - the human did approve it - but the send failed
            # and must be visible and retryable rather than silently lost.
            quotation.status = QuotationStatus.APPROVED
            quotation.send_error = result.error

        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="APPROVED_AND_SENT" if result.sent else "APPROVED_SEND_FAILED",
            user_id=user_id,
            details={
                "quotation_number": quotation.quotation_number,
                "draft_version": draft.version,
                "was_edited": approval.was_edited,
                "destination": result.destination,
                "sent_message_id": result.message_id,
                "error": result.error,
            },
        )
        self.db.commit()

        logger.info(
            "%s %s via %s",
            quotation.quotation_number,
            "sent" if result.sent else f"send FAILED ({result.error})",
            self.sender.describe(),
        )
        return ApprovalResult(
            quotation=quotation, action=ApprovalAction.APPROVE, send=result, draft=draft
        )

    def record_regeneration(
        self, quotation: QuotationRequest, *, user_id: int | None = None
    ) -> None:
        """Note that a human asked for a new draft, before one is generated."""
        draft = quotation.current_draft
        if draft is not None:
            self.db.add(
                Approval(
                    quotation_draft_id=draft.id,
                    user_id=user_id,
                    action=ApprovalAction.REGENERATE,
                    original_subject=draft.subject,
                    original_body=draft.body,
                    acted_at=utcnow(),
                )
            )
        audit.record(
            self.db,
            entity_type="quotation_request",
            entity_id=quotation.id,
            action="REGENERATE_REQUESTED",
            user_id=user_id,
            details={"quotation_number": quotation.quotation_number},
        )
        self.db.commit()

    def _schedule_follow_up(self, quotation) -> None:
        """Queue the first nudge, if a follow-up rule covers this quotation.

        Scheduling only: the nudge is drafted and queued for a human when it
        falls due. Nothing here sends anything, and a scheduling failure must
        not undo a send that already succeeded.
        """
        from app.services.quotations.followup_rules import FollowUpScheduler

        try:
            FollowUpScheduler(self.db).schedule_for(quotation)
        except Exception:  # noqa: BLE001 - the quotation has already gone out
            logger.exception("Could not schedule a follow-up for %s", quotation.quotation_number)
