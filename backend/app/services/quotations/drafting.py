"""Draft generation and verification.

Generates a reply, checks it reproduced every supplied figure, and regenerates
once if it did not. A draft that fails twice is still stored - the reviewer sees
it alongside the exact discrepancy - but it is never treated as clean.

Drafts are versioned. Regenerating supersedes the previous version rather than
overwriting it, so a reviewer who was midway through reading one does not have
it vanish, and the edit history stays intact for the metrics in section 22.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ai.drafter import generate_draft
from ai.guards import find_unsupported_claims, verify_draft_facts
from ai.llm.base import LLMClient, LLMError
from ai.reply_drafter import draft_decline_reply
from app.core.logging import get_logger
from app.core.rules import BusinessRules, get_rules
from app.models import DraftStatus, QuotationDraft, QuotationRequest
from app.services import audit, telemetry
from app.services.quotations.draft_context import build_draft_context
from app.services.quotations.table import build_rows, splice_text

logger = get_logger(__name__)


@dataclass(slots=True)
class DraftResult:
    draft: QuotationDraft | None = None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    regenerated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.draft is not None and not self.violations and not self.error

    @property
    def review_notes(self) -> list[str]:
        notes = []
        if self.violations:
            notes.append(
                "The generated draft did not reproduce the calculated figures exactly: "
                + "; ".join(self.violations)
            )
        if self.warnings:
            notes.append("The draft makes claims the system cannot support: " + "; ".join(self.warnings))
        return notes


class DraftingService:
    def __init__(
        self,
        db: Session,
        client: LLMClient | None = None,
        rules: BusinessRules | None = None,
    ) -> None:
        self.db = db
        self.client = client
        self.rules = rules or get_rules()

    def generate(self, quotation: QuotationRequest, *, user_id: int | None = None) -> DraftResult:
        context = build_draft_context(quotation, self.rules)
        email = quotation.email

        try:
            outcome = generate_draft(
                facts=context.facts,
                original_subject=email.subject if email else None,
                original_body=email.body_text if email else None,
                client=self.client,
            )
        except LLMError as exc:
            telemetry.record_failure(
                self.db,
                task="draft",
                model="unknown",
                error=str(exc),
                quotation_request_id=quotation.id,
            )
            logger.error("Draft generation failed for %s: %s", quotation.quotation_number, exc)
            return DraftResult(error=str(exc))

        telemetry.record_call(self.db, outcome.usage, quotation_request_id=quotation.id)
        draft_email = outcome.value
        model_used = outcome.usage.model
        regenerated = False

        violations = verify_draft_facts(draft_email.body, context.required_facts)

        if violations:
            logger.warning(
                "Draft for %s altered supplied figures (%s); regenerating.",
                quotation.quotation_number,
                "; ".join(violations),
            )
            try:
                retry = generate_draft(
                    facts=context.facts,
                    original_subject=email.subject if email else None,
                    original_body=email.body_text if email else None,
                    violations=violations,
                    previous_draft=draft_email.body,
                    client=self.client,
                )
            except LLMError as exc:
                logger.error("Draft regeneration failed for %s: %s", quotation.quotation_number, exc)
            else:
                telemetry.record_call(self.db, retry.usage, quotation_request_id=quotation.id)
                regenerated = True
                retry_violations = verify_draft_facts(retry.value.body, context.required_facts)
                # Keep the better attempt rather than the later one.
                if len(retry_violations) < len(violations):
                    draft_email, violations = retry.value, retry_violations
                    model_used = retry.usage.model

        warnings = find_unsupported_claims(draft_email.body)
        subject = self._reply_subject(draft_email.subject, email.subject if email else None)

        # Spliced *after* verification, deliberately. The guards check what the
        # model actually wrote; the table is settled arithmetic that was never
        # the model's to get wrong, and running the fact check over it would
        # only be checking this code against itself.
        body = splice_text(draft_email.body, build_rows(quotation))

        draft = self._store(
            quotation,
            subject=subject,
            body=body,
            model=model_used,
            user_id=user_id,
            violations=violations,
            warnings=warnings,
            regenerated=regenerated,
        )

        return DraftResult(
            draft=draft, violations=violations, warnings=warnings, regenerated=regenerated
        )

    def generate_decline_reply(
        self,
        quotation: QuotationRequest,
        *,
        customer_reply_text: str,
        user_id: int | None = None,
    ) -> DraftResult:
        """Write and store a courtesy reply for a customer who declined.

        No fact-verification pass here (unlike `generate`): this email is
        required *not* to repeat any quoted figure, so there is nothing to
        check it reproduced.
        """
        context = build_draft_context(quotation, self.rules)
        email = quotation.email

        try:
            outcome = draft_decline_reply(
                customer_name=quotation.customer_name_raw or quotation.customer_company_raw,
                quotation_number=quotation.quotation_number,
                quotation_summary=context.facts,
                customer_reply_text=customer_reply_text,
                original_subject=email.subject if email else None,
                client=self.client,
            )
        except LLMError as exc:
            telemetry.record_failure(
                self.db,
                task="decline_reply",
                model="unknown",
                error=str(exc),
                quotation_request_id=quotation.id,
            )
            logger.error(
                "Decline-reply generation failed for %s: %s", quotation.quotation_number, exc
            )
            return DraftResult(error=str(exc))

        telemetry.record_call(self.db, outcome.usage, quotation_request_id=quotation.id)
        draft_email = outcome.value
        subject = self._reply_subject(draft_email.subject, email.subject if email else None)

        draft = self._store(
            quotation,
            subject=subject,
            body=draft_email.body,
            model=outcome.usage.model,
            user_id=user_id,
            violations=[],
            warnings=[],
            regenerated=False,
        )
        return DraftResult(draft=draft)

    # --- Internals --------------------------------------------------------

    @staticmethod
    def _reply_subject(generated: str | None, original: str | None) -> str:
        """Guarantee the reply threads visibly, whatever the model returned."""
        subject = (generated or "").strip() or (original or "Quotation")
        if original and not subject.lower().startswith("re:"):
            subject = f"Re: {original.strip()}"
        return subject[:500]

    def _store(
        self,
        quotation: QuotationRequest,
        *,
        subject: str,
        body: str,
        model: str,
        user_id: int | None,
        violations: list[str],
        warnings: list[str],
        regenerated: bool,
    ) -> QuotationDraft:
        # Retire the previous current draft rather than deleting it.
        self.db.execute(
            update(QuotationDraft)
            .where(
                QuotationDraft.quotation_request_id == quotation.id,
                QuotationDraft.is_current.is_(True),
            )
            .values(is_current=False, status=DraftStatus.SUPERSEDED)
        )

        next_version = (
            self.db.scalar(
                select(QuotationDraft.version)
                .where(QuotationDraft.quotation_request_id == quotation.id)
                .order_by(QuotationDraft.version.desc())
                .limit(1)
            )
            or 0
        ) + 1

        draft = QuotationDraft(
            quotation_request_id=quotation.id,
            version=next_version,
            is_current=True,
            subject=subject,
            body=body,
            status=DraftStatus.GENERATED,
            generated_by=model,
        )
        self.db.add(draft)

        # The new draft was written from the figures as they stand now, so the
        # staleness that prompted the regeneration is spent. Left set, the
        # warning would never clear and a reviewer would learn to ignore a
        # banner that is right the one time it matters.
        for item in quotation.line_items:
            if item.pricing is not None and item.pricing.draft_stale:
                item.pricing.draft_stale = False

        self.db.flush()

        audit.record(
            self.db,
            entity_type="quotation_draft",
            entity_id=draft.id,
            action="GENERATED",
            user_id=user_id,
            details={
                "quotation_number": quotation.quotation_number,
                "version": next_version,
                "model": model,
                "regenerated": regenerated,
                "fact_violations": violations,
                "unsupported_claims": warnings,
            },
        )
        self.db.commit()
        return draft
