"""add follow-up email templates to organisation

Per-desk wording for the follow-up nudge. Null means "use the built-in
default", so an existing desk keeps sending exactly what it sent before this
ran, and clearing the field in the UI restores the default rather than
sending an empty email.

Autogenerate also proposed changes to `push_devices` and an index on
`emails.message_id` that this change did not cause. They are left out: a
migration should do what its name says, and unrelated drift belongs in its
own revision where it can be reviewed on its own merits.

Revision ID: 287d9a2e87cc
Revises: c9e35b2d1a48
Create Date: 2026-08-29 12:42:03.108520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '287d9a2e87cc'
down_revision: Union[str, Sequence[str], None] = 'c9e35b2d1a48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'organisations',
        sa.Column('followup_subject_template', sa.Text(), nullable=True),
    )
    op.add_column(
        'organisations',
        sa.Column('followup_body_template', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('organisations', 'followup_body_template')
    op.drop_column('organisations', 'followup_subject_template')
