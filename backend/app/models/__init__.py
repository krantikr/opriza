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
    ImportEntity,
    ImportStatus,
    MatchStatus,
    ProcessingStatus,
    QuantityUnit,
    QuotationStatus,
    RecordStatus,
    ReplyIntent,
    UserRole,
)
from app.models.master import Customer, StockItem
from app.models.quotation import (
    Approval,
    FollowUp,
    QuotationDraft,
    QuotationLineItem,
    QuotationRequest,
    StockAvailability,
)
from app.models.system import AuditLog, ImportBatch, LLMCall, User

__all__ = [
    "Base",
    # master data
    "Customer",
    "StockItem",
    # email
    "Email",
    "EmailAttachment",
    # quotation workflow
    "QuotationRequest",
    "QuotationLineItem",
    "StockAvailability",
    "QuotationDraft",
    "Approval",
    "FollowUp",
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
    "ImportEntity",
    "ImportStatus",
    "MatchStatus",
    "ProcessingStatus",
    "QuantityUnit",
    "QuotationStatus",
    "RecordStatus",
    "ReplyIntent",
    "UserRole",
]
