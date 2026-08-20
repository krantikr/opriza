"""Shared column patterns for ORM models."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

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


class TenantMixin:
    """`organisation_id` plus the index every scoped query relies on.

    Applied to every table holding a desk's business data. Two things make
    this safe rather than merely conventional:

    * The column is **not nullable**. A row with no owner is a row that RLS
      cannot protect, so the schema refuses to create one.
    * `ondelete="CASCADE"` - removing an organisation removes its data rather
      than orphaning rows that no policy will ever match again.

    The column alone does not isolate anything. `scripts/rls.py` generates the
    matching PostgreSQL policy for each table carrying this mixin, and
    `tests/test_tenancy.py` fails if a table has the column but no policy.
    """

    @declared_attr
    def organisation_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
