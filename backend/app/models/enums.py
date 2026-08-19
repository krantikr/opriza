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
    "PricingComponentKind",
    "PricingBasis",
    "RuleScope",
    "NotificationChannel",
    "NotificationKind",
    "NotificationStatus",
    "FollowUpStatus",
    "FollowUpTrigger",
    "StockMovementKind",
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


class PricingComponentKind(StrEnum):
    """The arithmetic a pricing rule performs.

    Deliberately a closed set. A trader configures *which* rules apply, with
    what figures and under what conditions; the operation each one performs is
    written in `services/pricing/components.py` and reviewed like any other
    code. An open expression language would let a loss-making rule be written
    by accident, and the margins here do not leave room for that.
    """

    #: Landed cost of matched stock, or a mill offer when nothing is held.
    BASE_PRICE = "BASE_PRICE"
    #: Freight, derived from distance and vehicle economics or a flat rate.
    TRANSPORTATION = "TRANSPORTATION"
    #: Loading, unloading and other per-MT handling.
    HANDLING = "HANDLING"
    #: Cost of credit over the payment period.
    FINANCING = "FINANCING"
    #: Market and delivery risk allowance.
    RISK_BUFFER = "RISK_BUFFER"
    #: Blends recent comparable invoices toward the computed cost.
    INVOICE_ANCHOR = "INVOICE_ANCHOR"
    #: Volume adjustment by tonnage band.
    QUANTITY_SLAB = "QUANTITY_SLAB"
    #: A/B/C commercial adjustment.
    CUSTOMER_TIER = "CUSTOMER_TIER"
    #: Any other named per-MT or percentage adjustment.
    ADJUSTMENT = "ADJUSTMENT"
    #: The single margin applied to total cost. Runs after every cost line.
    TARGET_MARGIN = "TARGET_MARGIN"
    #: Clamps the quote up to a minimum margin, and flags that it happened.
    MARGIN_FLOOR = "MARGIN_FLOOR"
    #: Rounds to a quotable figure, never back down through the floor.
    ROUNDING = "ROUNDING"


class PricingBasis(StrEnum):
    """Where the base price came from."""

    STOCK = "STOCK"
    MILL_OFFER = "MILL_OFFER"
    MANUAL = "MANUAL"
    UNAVAILABLE = "UNAVAILABLE"


class RuleScope(StrEnum):
    """What a rule is allowed to apply to."""

    ALL = "ALL"
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    LOCATION = "LOCATION"


class NotificationChannel(StrEnum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    SMS = "SMS"


class NotificationKind(StrEnum):
    """Why someone is being told something."""

    NEW_ENQUIRY = "NEW_ENQUIRY"
    QUOTATION_READY = "QUOTATION_READY"
    CUSTOMER_REPLIED = "CUSTOMER_REPLIED"
    FOLLOW_UP_DUE = "FOLLOW_UP_DUE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DIGEST = "DIGEST"


class NotificationStatus(StrEnum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"
    READ = "READ"


class FollowUpStatus(StrEnum):
    """Lifecycle of a scheduled follow-up.

    `DUE` is the important one: the rule decides when a nudge is owed, but it
    is queued for a human rather than sent, so no code path mails a customer
    unattended.
    """

    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    SENT = "SENT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class FollowUpTrigger(StrEnum):
    """What starts the clock on a follow-up.

    `ELAPSED` counts from the moment the quotation went out. `PROMISED_DATE`
    counts from a date the customer themselves gave - "we will decide by the
    14th" - which is a far better moment to call than an arbitrary interval,
    and is the difference between chasing and following up.
    """

    ELAPSED = "ELAPSED"
    PROMISED_DATE = "PROMISED_DATE"


class StockMovementKind(StrEnum):
    """How a quantity of stock moved, or stopped being available.

    `BLOCK` is a *soft* hold: the material is physically present and still
    counted as on hand, but it is withheld from quoting - a trader keeping
    tonnage back for an expected order, or quarantining a lot pending
    inspection. Unlike an ISSUE it can be lifted, and unlike a RESERVATION it
    is not tied to a particular quotation.
    """

    RECEIPT = "RECEIPT"
    ISSUE = "ISSUE"
    RESERVATION = "RESERVATION"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"
    BLOCK = "BLOCK"
