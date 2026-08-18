"""Controlled vocabularies persisted by the application.

`EmailCategory` and `QuantityUnit` are re-exported from the `ai` package rather
than redefined: the classifier produces them, so the AI contract is the single
source of truth and the two can never drift apart.
"""

from enum import StrEnum

from ai.schemas import EmailCategory, QuantityUnit, ReplyIntent

__all__ = [
    "EmailCategory",
    "QuantityUnit",
    "ReplyIntent",
    "UserRole",
    "RecordStatus",
    "CustomerTier",
    "EmailSourceType",
    "ProcessingStatus",
    "QuotationStatus",
    "MatchStatus",
    "ConfidenceLevel",
    "ApprovalAction",
    "DraftStatus",
    "ImportStatus",
    "ImportEntity",
]


class UserRole(StrEnum):
    """Roles exist in the schema from day one so the audit trail is stable.

    The MVP has no login; every action is attributed to the seeded default
    user. Adding authentication later is a login endpoint plus a dependency -
    not a migration across every approval and audit row.
    """

    ADMIN = "ADMIN"
    APPROVER = "APPROVER"
    VIEWER = "VIEWER"


class RecordStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CustomerTier(StrEnum):
    """Commercial tier, kept for reference. Not used by automatic pricing."""

    A = "A"
    B = "B"
    C = "C"


class EmailSourceType(StrEnum):
    GMAIL = "GMAIL"
    LOCAL = "LOCAL"


class ProcessingStatus(StrEnum):
    """Lifecycle of an ingested email through the pipeline."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    SKIPPED = "SKIPPED"  # classified as a category the MVP does not action
    FAILED = "FAILED"


class QuotationStatus(StrEnum):
    """Spec section 18 status machine, extended past SENT.

    NEW -> PROCESSING -> (NEEDS_INFORMATION | READY_FOR_REVIEW | FAILED)
        -> EDITED -> APPROVED -> SENT | REJECTED
        -> (from SENT, once the customer replies on the same thread)
           CUSTOMER_ACCEPTED | CUSTOMER_DECLINED

    The two CUSTOMER_* states are reached only by `QuotationWorkflow`'s reply
    branch, never by a reviewer action - they represent what the customer said,
    not a decision the business made.
    """

    NEW = "NEW"
    PROCESSING = "PROCESSING"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    EDITED = "EDITED"
    APPROVED = "APPROVED"
    SENT = "SENT"
    REJECTED = "REJECTED"
    FAILED = "FAILED"
    CUSTOMER_ACCEPTED = "CUSTOMER_ACCEPTED"
    CUSTOMER_DECLINED = "CUSTOMER_DECLINED"


class MatchStatus(StrEnum):
    """Outcome of deterministic product matching (spec section 13)."""

    PENDING = "PENDING"
    MATCH_FOUND = "MATCH_FOUND"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    NO_MATCH = "NO_MATCH"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ApprovalAction(StrEnum):
    APPROVE = "APPROVE"
    EDIT = "EDIT"
    REJECT = "REJECT"
    REGENERATE = "REGENERATE"


class DraftStatus(StrEnum):
    GENERATED = "GENERATED"
    EDITED = "EDITED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SENT = "SENT"
    SUPERSEDED = "SUPERSEDED"


class ImportStatus(StrEnum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ImportEntity(StrEnum):
    STOCK = "STOCK"
    CUSTOMERS = "CUSTOMERS"
