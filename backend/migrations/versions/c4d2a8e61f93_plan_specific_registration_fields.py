"""plan-specific registration form fields + Custom plan questions

Revision ID: c4d2a8e61f93
Revises: b3c9e1f47a20
Create Date: 2026-10-01 12:00:00.000000

Schema: adds registration_form_fields.plan_codes (JSON, nullable). NULL =
a general field asked once at first signup for every plan (unchanged
behaviour for every existing row); a list of plan codes = a "Show only for
plans" question, asked every time someone subscribes or switches to one of
those plans - see app.forms.models.RegistrationFormField.plan_codes.

Data (only when the EVERYTICKET application already exists, i.e. an
already-deployed database; a brand-new database gets the same rows from
`python -m app.core.seed` via app.plans.catalog.CUSTOM_PLAN_FORM_FIELDS):
inserts the Custom plan's default questions (expected tickets per month,
average ticket price). Idempotent: a field_key that already exists for the
application is left untouched (never overwrites an admin's edits).

The field list below is a deliberate frozen copy of
app.plans.catalog.CUSTOM_PLAN_FORM_FIELDS as of this revision - do not
import app code from a migration.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4d2a8e61f93'
down_revision: Union[str, None] = 'b3c9e1f47a20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPLICATION_CODE = "EVERYTICKET"

CUSTOM_PLAN_FORM_FIELDS = [
    {
        "field_key": "expected_monthly_tickets",
        "label": "Expected tickets per month",
        "field_type": "number",
        "required": True,
        "validation_pattern": r"[0-9]{1,9}",
        "validation_message": "Enter the expected number of tickets per month as a whole number, e.g. 5000",
        "placeholder": "e.g. 5000",
        "help_text": "Roughly how many tickets you expect to sell in a month.",
        "plan_codes": ["CUSTOM"],
        "display_order": 101,
    },
    {
        "field_key": "average_ticket_price",
        "label": "Average ticket price (INR)",
        "field_type": "number",
        "required": True,
        "validation_pattern": r"[0-9]{1,9}(\.[0-9]{1,2})?",
        "validation_message": "Enter the average ticket price in rupees, e.g. 250 or 249.50",
        "placeholder": "e.g. 250",
        "help_text": "Typical price of one ticket, in rupees.",
        "plan_codes": ["CUSTOM"],
        "display_order": 102,
    },
]

# Lightweight table definitions for data operations (no ORM models).
applications_t = sa.table("applications", sa.column("id", sa.Integer), sa.column("code", sa.String))
form_fields_t = sa.table(
    "registration_form_fields",
    sa.column("id", sa.Integer),
    sa.column("application_id", sa.Integer),
    sa.column("field_key", sa.String),
    sa.column("label", sa.String),
    sa.column("field_type", sa.String),
    sa.column("required", sa.Boolean),
    sa.column("validation_pattern", sa.String),
    sa.column("validation_message", sa.String),
    sa.column("check_duplicate", sa.Boolean),
    sa.column("placeholder", sa.String),
    sa.column("help_text", sa.String),
    sa.column("plan_codes", sa.JSON),
    sa.column("display_order", sa.Integer),
    sa.column("active", sa.Boolean),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def _now() -> datetime:
    # Naive UTC - same as how the app's DateTime(timezone=True) columns land in MySQL DATETIME.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _application_id(conn) -> int | None:
    return conn.execute(
        sa.select(applications_t.c.id).where(applications_t.c.code == APPLICATION_CODE)
    ).scalar()


def upgrade() -> None:
    op.add_column("registration_form_fields", sa.Column("plan_codes", sa.JSON(), nullable=True))

    conn = op.get_bind()
    application_id = _application_id(conn)
    if application_id is None:
        return  # fresh database - app.core.seed creates these rows

    existing_keys = set(
        conn.execute(
            sa.select(form_fields_t.c.field_key).where(form_fields_t.c.application_id == application_id)
        ).scalars()
    )
    now = _now()
    for field in CUSTOM_PLAN_FORM_FIELDS:
        if field["field_key"] in existing_keys:
            continue
        conn.execute(
            form_fields_t.insert().values(
                application_id=application_id, check_duplicate=False, active=True,
                created_at=now, updated_at=now, **field,
            )
        )


def downgrade() -> None:
    # Without plan_codes these two would turn into GENERAL questions shown
    # for every plan, so remove the seeded rows before dropping the column.
    # Submitted answers (customer_registration_data) are kept - they're
    # keyed by field_key, not by a foreign key to these rows.
    conn = op.get_bind()
    application_id = _application_id(conn)
    if application_id is not None:
        conn.execute(
            form_fields_t.delete().where(
                form_fields_t.c.application_id == application_id,
                form_fields_t.c.field_key.in_([f["field_key"] for f in CUSTOM_PLAN_FORM_FIELDS]),
            )
        )
    op.drop_column("registration_form_fields", "plan_codes")
