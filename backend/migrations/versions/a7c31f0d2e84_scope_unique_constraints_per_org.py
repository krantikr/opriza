"""scope unique constraints per organisation

Revision ID: a7c31f0d2e84
Revises: e3599367096d
Create Date: 2026-08-20 14:05:00.000000

Several identifiers were unique across the whole platform when they are in
fact each desk's own: a pricing rule set version, a quotation number, a
customer code, a vehicle name, a freight lane, and Gmail's message id. Left
global, the second desk to reach any of them fails at the database - which is
what stopped onboarding from seeding a starting rule set, since only one desk
on the platform could ever hold version 1.

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7c31f0d2e84'
down_revision: str | Sequence[str] | None = 'e3599367096d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, old auto-named constraint, new name, columns)
SCOPED = [
    (
        "pricing_rule_sets",
        "pricing_rule_sets_version_key",
        "uq_rule_set_version",
        ["organisation_id", "version"],
    ),
    (
        "quotation_requests",
        "quotation_requests_quotation_number_key",
        "uq_quotation_number",
        ["organisation_id", "quotation_number"],
    ),
    (
        "customers",
        "customers_customer_code_key",
        "uq_customer_code",
        ["organisation_id", "customer_code"],
    ),
    (
        "vehicle_rates",
        "vehicle_rates_name_key",
        "uq_vehicle_name",
        ["organisation_id", "name"],
    ),
    (
        "emails",
        "emails_message_id_key",
        "uq_email_message_id",
        ["organisation_id", "message_id"],
    ),
]


def upgrade() -> None:
    """Upgrade schema."""
    for table, old_name, new_name, columns in SCOPED:
        # IF EXISTS: the constraint name is PostgreSQL's own default, so a
        # database built by `create_all` rather than by migration may not
        # carry it under that name.
        op.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS "{old_name}"')
        op.create_unique_constraint(new_name, table, columns)

    # This one already existed as a composite - it just omitted the desk.
    op.drop_constraint("uq_location_distance", "location_distances", type_="unique")
    op.create_unique_constraint(
        "uq_location_distance",
        "location_distances",
        ["organisation_id", "origin", "destination"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("uq_location_distance", "location_distances", type_="unique")
    op.create_unique_constraint(
        "uq_location_distance", "location_distances", ["origin", "destination"]
    )

    for table, old_name, new_name, columns in SCOPED:
        op.drop_constraint(new_name, table, type_="unique")
        # Reinstating a global unique can fail if two desks now hold the same
        # value - which is exactly the situation this migration made legal.
        op.create_unique_constraint(old_name, table, columns[1:])
