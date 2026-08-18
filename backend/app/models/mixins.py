"""Shared column patterns for ORM models."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import utcnow


def enum_col(enum_cls: type[StrEnum]) -> SAEnum:
    """Store enums as portable VARCHAR rather than a dialect-native ENUM type.

    Native enums make schema evolution painful and do not exist in SQLite;
    `validate_strings` keeps the safety of rejecting unknown values.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=40,
        validate_strings=True,
        values_callable=lambda e: [member.value for member in e],
    )


class TimestampMixin:
    """created_at / updated_at maintained by the ORM, not the database.

    Kept application-side so behaviour is identical on SQLite and PostgreSQL.
    """

    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, nullable=False
    )


class CreatedAtMixin:
    """For append-only tables that are never updated in place."""

    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False, index=True)
