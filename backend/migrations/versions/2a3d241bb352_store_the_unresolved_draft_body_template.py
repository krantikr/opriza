"""store the unresolved draft body template

The drafted reply keeps its money as `{{placeholders}}` alongside the
resolved text, so a price change re-renders the body in code rather than
needing a second LLM call. Null on existing rows, which is correct: a draft
written before this has no template, and the old behaviour applies to it.

2a3d241bb352
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2a3d241bb352'
down_revision: Union[str, Sequence[str], None] = '287d9a2e87cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "quotation_drafts", sa.Column("body_template", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("quotation_drafts", "body_template")
