"""Add business details to leads, for sign-ups from the live demo.

The /demo page asks a prospect for their trade, city, yearly sales, team size,
Tally version and the problems they picked, then stores them as a lead with
source 'demo'. Those answers vary by channel, so they live in one JSON column
rather than a column each; the Request-access form leaves it empty.

Revision ID: d3f00dlead03
Revises: d2f00dlead02
Create Date: 2026-10-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3f00dlead03"
down_revision: str | Sequence[str] | None = "d2f00dlead02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("details", sa.JSON(), nullable=True))
    op.create_index("ix_leads_source", "leads", ["source"])


def downgrade() -> None:
    op.drop_index("ix_leads_source", table_name="leads")
    op.drop_column("leads", "details")
