"""Multi-tenant baseline.

The first migration. Everything before this was hand-written ALTER TABLE
against a SQLite file, which is why this exists: five sessions of that had
made the next schema change on real data unsafe.

The schema is created from the model metadata rather than from a transcribed
list of `create_table` calls. Autogenerate emits tables alphabetically, which
puts `emails` before the `organisations` it references; SQLAlchemy's own
dependency sort gets the order right and stays right as tables are added.

Row-level security is applied here too, in the same transaction as the tables.
Separating them would leave a window - however short - in which tenant tables
exist with no policy protecting them.

Revision ID: f4196bea7497
"""

from __future__ import annotations

from alembic import op

from app.core.db import Base
from app.models import *  # noqa: F401,F403 - registers every table
from scripts.rls import LOGIN_TABLES, login_policy_sql, policy_sql, tenant_tables

revision: str = "f4196bea7497"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    # Policies go on in the same transaction as the tables they protect.
    for table in tenant_tables():
        builder = login_policy_sql if table in LOGIN_TABLES else policy_sql
        for statement in builder(table):
            op.execute(statement)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
