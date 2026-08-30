"""ORM models.

Importing this package registers every table on `Base.metadata`, which is what
`scripts/init_db.py` relies on to create the schema.
"""

from app.core.db import Base
from app.models.email import Email, EmailAttachment
from app.models.enums import (
    ApprovalAction,
    ConfidenceLevel,
    CustomerTier,
    DraftStatus,
    EmailCategory,
    EmailSourceType,
    FollowUpStatus,
    FollowUpTrigger,
    ImportEntity,
    ImportStatus,
    InviteStatus,
    LostReason,
    MailboxStatus,
    MailDirection,
    MatchStatus,
    NotificationChannel,
    NotificationKind,
    NotificationStatus,
    NotSentReason,
    OrgStatus,
    PricingBasis,
    PricingComponentKind,
    ProcessingStatus,
    QuantityUnit,
    QuotationStatus,
    RecordStatus,
    ReplyIntent,
    RuleScope,
    StockMovementKind,
    UserRole,
)
from app.models.master import Customer, PriorityProduct, StockItem
from app.models.ops import (
    CustomerNote,
    FollowUpRule,
    FollowUpSchedule,
    Notification,
    NotificationRule,
    PushDevice,
    StockMovement,
)
from app.models.pricing import (
    LocationDistance,
    MillOffer,
    PricingOverride,
    PricingRule,
    PricingRuleSet,
    QuotationPricing,
    SalesInvoice,
    VehicleRate,
)
from app.models.quotation import (
    PRICING_FROZEN_STATUSES,
    Approval,
    FollowUp,
    QuotationDraft,
    QuotationLineItem,
    QuotationRequest,
    StockAvailability,
)
from app.models.system import AuditLog, ImportBatch, LLMCall
from app.models.tenancy import Invite, Mailbox, Organisation, User

__all__ = [
    "Base",
    # tenancy
    "Organisation",
    "User",
    "Mailbox",
    "Invite",
    "OrgStatus",
    "MailboxStatus",
    "InviteStatus",
    "MailDirection",
    # master data
    "Customer",
    "PriorityProduct",
    "StockItem",
    # email
    "Email",
    "EmailAttachment",
    # quotation workflow
    "PRICING_FROZEN_STATUSES",
    "QuotationRequest",
    "QuotationLineItem",
    "StockAvailability",
    "QuotationDraft",
    "Approval",
    "FollowUp",
    # pricing
    "PricingRuleSet",
    "PricingRule",
    "QuotationPricing",
    "PricingOverride",
    "LocationDistance",
    "VehicleRate",
    "MillOffer",
    "SalesInvoice",
    # operations
    "NotificationRule",
    "PushDevice",
    "Notification",
    "FollowUpRule",
    "FollowUpSchedule",
    "StockMovement",
    "CustomerNote",
    # system
    "User",
    "AuditLog",
    "LLMCall",
    "ImportBatch",
    # enums
    "ApprovalAction",
    "ConfidenceLevel",
    "CustomerTier",
    "DraftStatus",
    "EmailCategory",
    "EmailSourceType",
    "FollowUpStatus",
    "FollowUpTrigger",
    "LostReason",
    "ImportEntity",
    "ImportStatus",
    "MatchStatus",
    "NotificationChannel",
    "NotificationKind",
    "NotificationStatus",
    "NotSentReason",
    "PricingBasis",
    "PricingComponentKind",
    "ProcessingStatus",
    "QuantityUnit",
    "QuotationStatus",
    "RecordStatus",
    "ReplyIntent",
    "RuleScope",
    "StockMovementKind",
    "UserRole",
]
