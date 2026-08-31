"""Drop the follow-up rules engine.

Nothing schedules a nudge any more. A quotation appears on the Follow-ups
board the moment it reaches the customer and stays until the deal settles;
when to chase is the trader's decision, not a timer's.

`follow_ups` - the record of nudges actually sent - is deliberately kept. It
is history, not scheduling: "chased 3x" on a row, the Activity log and the
report lines that count follow-ups all read from it.

Revision ID: b7d4e91c05af
Revises: 9090c31b12db
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b7d4e91c05af"
down_revision = "9090c31b12db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Schedules first: they carry the FK to rules.
    op.drop_table("follow_up_schedules")
    op.drop_table("follow_up_rules")


def downgrade() -> None:
    """Recreate the tables empty.

    The rules themselves are not restored - they were configuration, and a
    downgrade that invented plausible-looking rules would start chasing
    customers on a schedule nobody chose.
    """
    op.create_table(
        "follow_up_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False, index=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("first_after_hours", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("remind_before_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_after_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("interval_days", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("stop_after_days", sa.Integer(), nullable=True),
        sa.Column("auto_send", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "mark_cold_when_exhausted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("subject_template", sa.String(length=300), nullable=True),
        sa.Column("body_template", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "follow_up_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), nullable=False, index=True),
        sa.Column(
            "quotation_request_id",
            sa.Integer(),
            sa.ForeignKey("quotation_requests.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "rule_id",
            sa.Integer(),
            sa.ForeignKey("follow_up_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "follow_up_id",
            sa.Integer(),
            sa.ForeignKey("follow_ups.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("status", sa.String(length=32), nullable=False, index=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("resolution_note", sa.String(length=300), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
