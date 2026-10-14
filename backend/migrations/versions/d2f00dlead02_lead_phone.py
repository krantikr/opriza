"""Add phone and status to leads.

The Request-access form now collects a phone number (required going forward,
server-default '' so the NOT NULL holds for rows that predate the column), and
the operator moves each lead through a pipeline status (default 'new').

Revision ID: d2f00dlead02
Revises: d1f00dlead01
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f00dlead02"
down_revision: str | Sequence[str] | None = "d1f00dlead01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("phone", sa.String(length=40), nullable=False, server_default=""),
    )
    op.add_column(
        "leads",
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
    )
    op.create_index("ix_leads_status", "leads", ["status"])


def downgrade() -> None:
    op.drop_index("ix_leads_status", table_name="leads")
    op.drop_column("leads", "status")
    op.drop_column("leads", "phone")
