"""The multi-tenant mail poller.

One scheduled tick runs often - every minute - and decides *per organisation*
whether that desk is due a check. The alternative, a scheduled job per desk,
means adding and removing jobs whenever an owner edits their window, and a
missed removal keeps polling a suspended account.

The scheduling rule is time-banded and local to each desk: frequently through
its working day, sparsely overnight. `app.services.crawl_window` owns that
decision; this module owns the loop and the isolation.

**Isolation is the thing to get right here.** A background loop has no request
and therefore no token, so nothing binds the session automatically. Each desk
is processed inside `as_organisation`, which binds and commits per iteration,
so one desk's mail can never be written under another's id.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal, utcnow
from app.core.logging import get_logger
from app.core.tenancy import as_organisation, bind_session
from app.models import Mailbox, MailboxStatus, Organisation, OrgStatus
from app.services.crawl_window import decide, is_due

logger = get_logger(__name__)


@dataclass(slots=True)
class PollResult:
    checked: int = 0
    skipped: int = 0
    ingested: int = 0
    failures: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"checked={self.checked} skipped={self.skipped} "
            f"ingested={self.ingested} failures={len(self.failures)}"
        )


def poll_all_organisations() -> PollResult:
    """One tick: check every desk that is due, skip the rest.

    A failure on one desk is recorded against that desk's mailbox and the loop
    continues. One customer's expired Google token must not stop everyone
    else's mail arriving.
    """
    result = PollResult()
    db = SessionLocal()
    try:
        # Reading the organisation list is a cross-tenant operation by nature,
        # so it runs as the super admin sentinel rather than unscoped.
        bind_session(db, None, super_admin=True)
        organisations = list(
            db.scalars(
                select(Organisation).where(Organisation.status == OrgStatus.ACTIVE)
            )
        )
        db.commit()

        for organisation in organisations:
            try:
                _poll_one(db, organisation, result)
            except Exception as exc:  # noqa: BLE001 - one desk must not stop the rest
                logger.exception("Poll failed for %s", organisation.slug)
                result.failures.append(f"{organisation.slug}: {exc}")
    finally:
        db.close()

    if result.checked or result.failures:
        logger.info("Poll tick: %s", result.summary())
    return result


def poll_one_organisation(db, organisation_id: int) -> PollResult:
    """Check one desk's mail now, ignoring its schedule.

    For the "check now" button a trader presses straight after connecting a
    mailbox. Waiting ten minutes to discover whether the connection worked is
    a poor first impression, so the window is deliberately bypassed here - it
    governs unattended polling, not a person asking directly.
    """
    result = PollResult()
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        return result

    for mailbox in db.scalars(select(Mailbox)):
        if mailbox.status is MailboxStatus.DISCONNECTED:
            continue
        try:
            _ingest_mailbox(db, organisation, mailbox, result)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            logger.exception("Manual check failed for %s", mailbox.email_address)
            if str(exc) not in " ".join(result.failures):
                result.failures.append(str(exc))
    db.commit()
    return result


def _poll_one(db, organisation: Organisation, result: PollResult) -> None:
    """Check one desk's mailboxes, if its window says it is due."""
    with as_organisation(db, organisation.id):
        mailboxes = list(db.scalars(select(Mailbox)))

    if not mailboxes:
        result.skipped += 1
        return

    decision = decide(organisation)
    if not decision.should_poll:
        result.skipped += 1
        return

    for mailbox in mailboxes:
        if mailbox.status is MailboxStatus.DISCONNECTED:
            result.skipped += 1
            continue
        if not is_due(organisation, mailbox.last_polled_at):
            result.skipped += 1
            continue

        with as_organisation(db, organisation.id):
            _ingest_mailbox(db, organisation, mailbox, result)


def _ingest_mailbox(db, organisation: Organisation, mailbox: Mailbox, result: PollResult) -> None:
    """Ingest and process one mailbox, recording the outcome on the mailbox.

    Errors are stored rather than only logged: a disconnected mailbox looks
    exactly like a quiet week to a trader, so the reason has to reach the
    interface where they will see it.
    """
    from app.services.email.factory import get_email_source_for
    from app.services.email.ingestion import EmailIngestionService
    from app.workflows.quotation import process_pending_emails

    result.checked += 1
    mailbox.last_polled_at = utcnow()

    try:
        source = get_email_source_for(mailbox)
        if not source.is_available():
            mailbox.status = MailboxStatus.NEEDS_RECONNECT
            mailbox.last_error = (
                "We could not reach this mailbox. Reconnect it in Settings."
            )
            return

        # `ingest` returns a report, not a list - `created` is the count of
        # genuinely new mail, excluding duplicates already seen.
        report = EmailIngestionService(db, source).ingest(
            limit=settings.gmail_max_results
        )
        result.ingested += report.created

        if settings.llm_configured:
            process_pending_emails(db, limit=settings.gmail_max_results)

        mailbox.status = MailboxStatus.CONNECTED
        mailbox.last_error = None
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        mailbox.status = MailboxStatus.ERROR
        mailbox.last_error = str(exc)[:500]
        result.failures.append(f"{organisation.slug}/{mailbox.email_address}: {exc}")
        raise


__all__ = ["PollResult", "poll_all_organisations"]
