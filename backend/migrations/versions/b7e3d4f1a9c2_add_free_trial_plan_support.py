"""add free trial plan support

Revision ID: b7e3d4f1a9c2
Revises: a4f7c9e2b6d1
Create Date: 2026-09-02 00:00:00.000000

Free trial feature: a trial is modeled as its own distinct Plan (price=0,
is_trial=True, trial_period_days=N), not an attribute layered onto an
existing paid plan - "process will be the same" per the feature request.

plans.is_trial / plans.trial_period_days: configurable per trial plan.
subscriptions.is_trial: denormalized copy of plan.is_trial at subscription-
creation time. This is needed (rather than joining to plans.is_trial) because
Postgres partial-unique-index predicates can only reference columns on the
same table as the index - the new
uq_one_trial_subscription_per_customer_application index below constrains
(customer_id, application_id) to at most one row WHERE is_trial = true,
regardless of that row's status (PENDING_PAYMENT/ACTIVE/EXPIRED/CANCELLED
all count), enforcing "one credentials can take only one trial lifetime" at
the database level - the hard guarantee behind the application-level
pre-check in app.subscriptions.service.assert_trial_not_already_used().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3d4f1a9c2'
down_revision: Union[str, None] = 'a4f7c9e2b6d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'plans',
        sa.Column('is_trial', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'plans',
        sa.Column('trial_period_days', sa.Integer(), nullable=True),
    )
    op.add_column(
        'subscriptions',
        sa.Column('is_trial', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Spec follow-up: "one credentials can take only one trial lifetime" -
    # unique across ALL statuses (no postgresql_where status filter, unlike
    # the one-active-subscription index), so a CANCELLED or EXPIRED trial
    # still blocks a second one from ever being created.
    op.create_index(
        'uq_one_trial_subscription_per_customer_application',
        'subscriptions',
        ['customer_id', 'application_id'],
        unique=True,
        postgresql_where=sa.text('is_trial = true'),
    )


def downgrade() -> None:
    op.drop_index(
        'uq_one_trial_subscription_per_customer_application',
        table_name='subscriptions',
        postgresql_where=sa.text('is_trial = true'),
    )
    op.drop_column('subscriptions', 'is_trial')
    op.drop_column('plans', 'trial_period_days')
    op.drop_column('plans', 'is_trial')
