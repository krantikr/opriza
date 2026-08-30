"""not-sent reason, customer priority, priority products

Revision ID: 4bc52599963e
Revises: b21d833d2fe1
Create Date: 2026-08-29 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4bc52599963e'
down_revision: str | Sequence[str] | None = 'b21d833d2fe1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Nullable with no default, same as lost_reason/lost_note: an existing
    # quotation has no not-sent reason recorded yet, and NULL says exactly
    # that.
    op.add_column(
        'quotation_requests',
        sa.Column('not_sent_reason', sa.String(length=40), nullable=True),
    )
    op.add_column(
        'quotation_requests',
        sa.Column('not_sent_note', sa.String(length=300), nullable=True),
    )

    # Every existing customer defaults to not-priority.
    op.add_column(
        'customers',
        sa.Column('is_priority', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'priority_products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=True),
        sa.Column('grade', sa.String(length=60), nullable=False),
        sa.Column('make', sa.String(length=80), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('organisation_id', 'grade', 'make', name='uq_priority_product'),
    )
    op.create_index(
        op.f('ix_priority_products_grade'), 'priority_products', ['grade']
    )
    op.create_index(
        op.f('ix_priority_products_make'), 'priority_products', ['make']
    )
    op.create_index(
        op.f('ix_priority_products_organisation_id'), 'priority_products', ['organisation_id']
    )

    # Row-level security, matching every other tenant table.
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from scripts.rls import policy_sql  # noqa: PLC0415

    for statement in policy_sql("priority_products"):
        op.execute(statement)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON priority_products")
    op.drop_index(op.f('ix_priority_products_organisation_id'), table_name='priority_products')
    op.drop_index(op.f('ix_priority_products_make'), table_name='priority_products')
    op.drop_index(op.f('ix_priority_products_grade'), table_name='priority_products')
    op.drop_table('priority_products')

    op.drop_column('customers', 'is_priority')

    op.drop_column('quotation_requests', 'not_sent_note')
    op.drop_column('quotation_requests', 'not_sent_reason')
