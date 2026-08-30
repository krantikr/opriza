"""multi-location pricing options

Revision ID: 9090c31b12db
Revises: 4bc52599963e
Create Date: 2026-08-30 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9090c31b12db'
down_revision: str | Sequence[str] | None = '4bc52599963e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A line item can now carry more than one priced option (one per
    # despatch location a trader added to compare). Every existing row
    # becomes that line's sole, selected option: `is_selected` defaults
    # true, so nothing needs a backfill pass.
    op.drop_constraint(
        'quotation_pricing_quotation_line_item_id_key',
        'quotation_pricing',
        type_='unique',
    )
    op.add_column(
        'quotation_pricing',
        sa.Column('despatch_location', sa.String(length=120), nullable=True),
    )
    op.add_column(
        'quotation_pricing',
        sa.Column(
            'is_selected', sa.Boolean(), nullable=False, server_default=sa.true()
        ),
    )
    op.add_column(
        'quotation_pricing',
        sa.Column(
            'is_manual', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('quotation_pricing', 'is_manual')
    op.drop_column('quotation_pricing', 'is_selected')
    op.drop_column('quotation_pricing', 'despatch_location')
    op.create_unique_constraint(
        'quotation_pricing_quotation_line_item_id_key',
        'quotation_pricing',
        ['quotation_line_item_id'],
    )
