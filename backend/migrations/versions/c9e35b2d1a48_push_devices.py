"""push devices for FCM

Revision ID: c9e35b2d1a48
Revises: b8d24a1c3f57
Create Date: 2026-08-21 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c9e35b2d1a48'
down_revision: str | Sequence[str] | None = 'b8d24a1c3f57'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'push_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organisation_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        # 512 because an FCM registration token has no documented maximum and
        # the ones Google issues today already run past 200 characters.
        sa.Column('token', sa.String(length=512), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=True),
        sa.Column('user_agent', sa.String(length=300), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('disabled_reason', sa.String(length=300), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['app_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # Scoped per desk like every other tenant table: the same physical
        # browser could legitimately be registered against two organisations.
        sa.UniqueConstraint('organisation_id', 'token', name='uq_push_device_token'),
    )
    op.create_index(op.f('ix_push_devices_user_id'), 'push_devices', ['user_id'])
    op.create_index('ix_push_devices_user', 'push_devices', ['user_id', 'is_active'])
    op.create_index(
        op.f('ix_push_devices_organisation_id'), 'push_devices', ['organisation_id']
    )

    # Row-level security, matching every other tenant table. The predicate is
    # not written by hand here: `scripts/rls.py::policy_sql` is the single
    # definition, and it compares on *text* because casting the setting to int
    # fails outright when it holds the super-admin sentinel rather than an id.
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root))
    from scripts.rls import policy_sql  # noqa: PLC0415

    for statement in policy_sql("push_devices"):
        op.execute(statement)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON push_devices")
    op.drop_index(op.f('ix_push_devices_organisation_id'), table_name='push_devices')
    op.drop_index('ix_push_devices_user', table_name='push_devices')
    op.drop_index(op.f('ix_push_devices_user_id'), table_name='push_devices')
    op.drop_table('push_devices')
