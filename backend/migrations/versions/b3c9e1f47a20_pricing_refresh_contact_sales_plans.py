"""pricing refresh: contact-sales plans + Starter/Institutional/Custom catalog

Revision ID: b3c9e1f47a20
Revises: ed10fff07aa9
Create Date: 2026-09-25 12:00:00.000000

Schema: adds plans.is_contact_sales ("Talk to us" plans - never self-served).

Data (only when the EVERYTICKET application already exists, i.e. an
already-deployed database; on a brand-new database this is a no-op and
`python -m app.core.seed` creates the same catalog from app.plans.catalog):
  - inserts STARTER / INSTITUTIONAL / CUSTOM with their features. If a
    plan with that code already exists (e.g. upgrade -> downgrade ->
    upgrade), its name/price/description are left alone, but it is made
    active and its is_contact_sales is set from the catalog - that column
    is brand new here, so there is no admin value to preserve, and leaving
    CUSTOM at the column default (False) would make it a free self-serve plan
  - adds the free-ticket / overage feature rows to FREE_TRIAL
  - deactivates BASIC / PROFESSIONAL / ENTERPRISE. Rows are kept (FKs from
    subscriptions, payments, invoices); existing subscribers are NOT moved
    or repriced - they renew on their current plan until they switch.

The catalog below is a deliberate frozen copy of app.plans.catalog as of
this revision - do not import app code from a migration.
"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c9e1f47a20'
down_revision: Union[str, None] = 'ed10fff07aa9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPLICATION_CODE = "EVERYTICKET"
LEGACY_PLAN_CODES = ("BASIC", "PROFESSIONAL", "ENTERPRISE")
# Pushed below the new catalog in the admin plans grid.
LEGACY_DISPLAY_ORDER_START = 11

FREE_TRIAL_FEATURES = [
    ("free_tickets", "Free tickets", "Up to 300 / month"),
    ("ticket_overage", "Ticket overage", "₹4 per ticket beyond 300 / month"),
]

PLANS = [
    {
        "plan_code": "STARTER",
        "name": "Starter",
        "description": "<p><strong>Included features</strong></p>",
        "price": 6999,
        "is_contact_sales": False,
        "display_order": 1,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "2,000 tickets"),
            ("pos_application", "POS Software Application", None),
            ("staff_accounts", "Active Staff Accounts (5 Users)", None),
            ("payment_methods", "Single Payment Method", None),
            ("analytics", "Basic Analytics with Real-Time Insight", None),
            ("staff_training", "Staff Training One-Time (Included)", None),
            ("event_management", "Event Management", None),
            ("custom_branding", "Basic Custom Branding", None),
            ("admission_app", "Admission App", None),
        ],
    },
    {
        "plan_code": "INSTITUTIONAL",
        "name": "Institutional",
        "description": "<p>Everything in <strong>Starter</strong>, plus:</p>",
        "price": 14999,
        "is_contact_sales": False,
        "display_order": 2,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "4,000 tickets"),
            ("ticket_overage", "Ticket overage", "₹4 per ticket beyond 4,000"),
            ("staff_accounts", "Active Staff Accounts (15 Users)", None),
            ("payment_methods", "Multiple Payment Methods", None),
            ("analytics", "AI-led Analytics with Real-Time Insight", None),
            ("staff_training", "Staff Training One-Time (Included)", None),
            ("event_management", "Event Management", None),
            ("custom_branding", "Custom Branding", None),
            ("visitor_behavior_analysis", "Visitor Behavior Analysis", None),
            ("ai_forecasting", "AI-led Forecasting", None),
            ("admission_app", "Admission App", None),
        ],
    },
    {
        "plan_code": "CUSTOM",
        "name": "Custom",
        "description": "<p>Everything in <strong>Institutional</strong>, plus:</p>",
        "price": 0,
        "is_contact_sales": True,
        "display_order": 3,
        "features": [
            ("onboarding_charges", "Onboarding charges", "Applicable"),
            ("monthly_ticket_limit", "Monthly ticket limit", "Talk to us"),
            ("custom_branding", "Custom Branding - Fully Customizable", None),
            ("fundraising_platform", "Donation / Fundraising Platform", None),
            ("email_campaigns", "Marketing / Automation Email Campaigns", None),
            ("white_label_domain", "White-label Custom Domain (additional)", None),
            ("crm_integration", "CRM Integration", None),
        ],
    },
]

# Lightweight table definitions for data operations (no ORM models).
applications_t = sa.table("applications", sa.column("id", sa.Integer), sa.column("code", sa.String))
plans_t = sa.table(
    "plans",
    sa.column("id", sa.Integer),
    sa.column("application_id", sa.Integer),
    sa.column("plan_code", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("price", sa.Numeric(12, 2)),
    sa.column("currency", sa.String),
    sa.column("billing_interval", sa.String),
    sa.column("billing_frequency", sa.Integer),
    sa.column("active", sa.Boolean),
    sa.column("display_order", sa.Integer),
    sa.column("is_trial", sa.Boolean),
    sa.column("trial_period_days", sa.Integer),
    sa.column("is_contact_sales", sa.Boolean),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)
plan_features_t = sa.table(
    "plan_features",
    sa.column("id", sa.Integer),
    sa.column("plan_id", sa.Integer),
    sa.column("feature_key", sa.String),
    sa.column("feature_label", sa.String),
    sa.column("feature_value", sa.String),
    sa.column("display_order", sa.Integer),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)


def _now() -> datetime:
    # Naive UTC - same as how the app's DateTime(timezone=True) columns land in MySQL DATETIME.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _plan_id(conn, application_id: int, plan_code: str) -> int | None:
    return conn.execute(
        sa.select(plans_t.c.id).where(
            plans_t.c.application_id == application_id, plans_t.c.plan_code == plan_code
        )
    ).scalar()


def _add_missing_features(conn, plan_id: int, features) -> None:
    """Idempotent: skips any feature_key the plan already has; appends after existing rows."""
    rows = conn.execute(
        sa.select(plan_features_t.c.feature_key, plan_features_t.c.display_order).where(
            plan_features_t.c.plan_id == plan_id
        )
    ).all()
    existing_keys = {row.feature_key for row in rows}
    next_order = max((row.display_order for row in rows), default=-1) + 1
    now = _now()
    for feature_key, feature_label, feature_value in features:
        if feature_key in existing_keys:
            continue
        conn.execute(
            plan_features_t.insert().values(
                plan_id=plan_id, feature_key=feature_key, feature_label=feature_label,
                feature_value=feature_value, display_order=next_order, created_at=now, updated_at=now,
            )
        )
        next_order += 1


def upgrade() -> None:
    # server_default so the NOT NULL column can be added to the already-
    # populated plans table - every existing plan is a normal self-serve plan.
    op.add_column(
        'plans', sa.Column('is_contact_sales', sa.Boolean(), nullable=False, server_default=sa.text('0'))
    )

    conn = op.get_bind()
    application_id = conn.execute(
        sa.select(applications_t.c.id).where(applications_t.c.code == APPLICATION_CODE)
    ).scalar()
    if application_id is None:
        # Fresh database - the seed creates the catalog.
        return

    now = _now()
    for entry in PLANS:
        plan_id = _plan_id(conn, application_id, entry["plan_code"])
        if plan_id is None:
            conn.execute(
                plans_t.insert().values(
                    application_id=application_id, plan_code=entry["plan_code"], name=entry["name"],
                    description=entry["description"], price=entry["price"], currency="INR",
                    billing_interval="month", billing_frequency=1, active=True,
                    display_order=entry["display_order"], is_trial=False, trial_period_days=None,
                    is_contact_sales=entry["is_contact_sales"], created_at=now, updated_at=now,
                )
            )
            plan_id = _plan_id(conn, application_id, entry["plan_code"])
        else:
            conn.execute(
                plans_t.update()
                .where(plans_t.c.id == plan_id)
                .values(active=True, is_contact_sales=entry["is_contact_sales"], updated_at=now)
            )
        _add_missing_features(conn, plan_id, entry["features"])

    free_trial_id = _plan_id(conn, application_id, "FREE_TRIAL")
    if free_trial_id is not None:
        _add_missing_features(conn, free_trial_id, FREE_TRIAL_FEATURES)

    for offset, plan_code in enumerate(LEGACY_PLAN_CODES):
        conn.execute(
            plans_t.update()
            .where(plans_t.c.application_id == application_id, plans_t.c.plan_code == plan_code)
            .values(active=False, display_order=LEGACY_DISPLAY_ORDER_START + offset, updated_at=now)
        )


def downgrade() -> None:
    conn = op.get_bind()
    application_id = conn.execute(
        sa.select(applications_t.c.id).where(applications_t.c.code == APPLICATION_CODE)
    ).scalar()
    if application_id is not None:
        now = _now()
        # Plans are never hard-deleted (subscriptions may already reference
        # the new ones) - hide the new catalog and restore the legacy one.
        # CUSTOM must be hidden BEFORE the column goes: without
        # is_contact_sales it would read as an ordinary price-0 plan.
        conn.execute(
            plans_t.update()
            .where(
                plans_t.c.application_id == application_id,
                plans_t.c.plan_code.in_([entry["plan_code"] for entry in PLANS]),
            )
            .values(active=False, updated_at=now)
        )
        conn.execute(
            plans_t.update()
            .where(plans_t.c.application_id == application_id, plans_t.c.plan_code.in_(LEGACY_PLAN_CODES))
            .values(active=True, updated_at=now)
        )
        free_trial_id = _plan_id(conn, application_id, "FREE_TRIAL")
        if free_trial_id is not None:
            conn.execute(
                plan_features_t.delete().where(
                    plan_features_t.c.plan_id == free_trial_id,
                    plan_features_t.c.feature_key.in_([key for key, _, _ in FREE_TRIAL_FEATURES]),
                )
            )

    op.drop_column('plans', 'is_contact_sales')
