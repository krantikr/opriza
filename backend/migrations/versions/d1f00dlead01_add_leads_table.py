"""Add the public leads table.

Platform-level (no organisation_id, so no row-level-security policy): it holds
design-partner requests from the marketing site, which arrive before a tenant
exists. Append-only — created_at but no updated_at.

Revision ID: d1f00dlead01
Revises: b7d4e91c05af
Create Date: 2026-10-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1f00dlead01"
down_revision: str | Sequence[str] | None = "b7d4e91c05af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("monthly_enquiries", sa.String(length=60), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=60), nullable=False, server_default="marketing_site"),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
    )
    op.create_index("ix_leads_created_at", "leads", ["created_at"])
    op.create_index("ix_leads_email", "leads", ["email"])


def downgrade() -> None:
    op.drop_index("ix_leads_email", table_name="leads")
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_table("leads")
