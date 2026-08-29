"""add negotiation and payment stages

Adds `paid_at`. The three new statuses - NEGOTIATION, PAYMENT_PENDING, PAID -
need no DDL: `enum_col` stores statuses as a portable VARCHAR(40) with no
native enum type and no CHECK constraint, precisely so the state machine can
grow without a migration. The new values fit the existing width.

Existing rows keep their status and get a null `paid_at`, which is correct:
nothing that went out before this was tracked as paid.

b21d833d2fe1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b21d833d2fe1'
down_revision: Union[str, Sequence[str], None] = '2a3d241bb352'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quotation_requests",
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("quotation_requests", "paid_at")
