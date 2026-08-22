"""chase: snooze and lost reason

Revision ID: b8d24a1c3f57
Revises: a7c31f0d2e84
Create Date: 2026-08-20 12:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d24a1c3f57'
down_revision: str | Sequence[str] | None = 'a7c31f0d2e84'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # All three are nullable with no default, so no backfill is needed: an
    # existing quotation is neither snoozed nor lost, and NULL says exactly
    # that. Enums are stored as strings, matching `enum_col` elsewhere.
    op.add_column('quotation_requests', sa.Column('snoozed_until', sa.Date(), nullable=True))
    op.add_column(
        'quotation_requests',
        sa.Column('lost_reason', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'quotation_requests',
        sa.Column('lost_note', sa.String(length=300), nullable=True),
    )
    # The chase board filters open quotations on the snooze date every time it
    # loads, which is the busiest read on the screen a trader opens first.
    op.create_index(
        op.f('ix_quotation_requests_snoozed_until'),
        'quotation_requests',
        ['snoozed_until'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f('ix_quotation_requests_snoozed_until'), table_name='quotation_requests'
    )
    op.drop_column('quotation_requests', 'lost_note')
    op.drop_column('quotation_requests', 'lost_reason')
    op.drop_column('quotation_requests', 'snoozed_until')
