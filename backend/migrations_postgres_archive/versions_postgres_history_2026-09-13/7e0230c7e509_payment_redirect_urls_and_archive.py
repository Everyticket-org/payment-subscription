"""configurable PayU redirect/webhook URLs + archive-after-non-renewal

Revision ID: 7e0230c7e509
Revises: c2d4e6f8a1b3
Create Date: 2026-09-02 00:00:00.000001

Two independent follow-ups, both on the `applications` table:

  - return_url / payu_webhook_base_url (frontend request, 2026-09:
    "PayU redirect back to localhost:4200 which is wrong. instead allow
    to configure return URL and PayU webhook URL"): the customer's
    post-payment browser redirect and PayU's own success/failure
    server-callback target were both hardcoded via env vars
    (FRONTEND_URL, PAYU_SUCCESS_URL/PAYU_FAILURE_URL) with no admin
    override - fine for local dev (defaults point at localhost) but
    wrong for any real deployment. These two columns, when set, take
    priority over those env vars (same DB-row-overrides-env-fallback
    pattern as every other per-application override in this app -
    webhook_secret, sso_secret, PayU credentials, SMTP transport).
    return_url is the customer-facing app URL (used to build
    /payment/return and /sso/consume links); payu_webhook_base_url is
    THIS backend's own publicly-reachable base URL (used to build the
    /api/v1/payment/payu/callback/{success,failure} URLs PayU's hosted
    checkout page is told to redirect the browser to).

  - archive_after_days (admin Configuration > Everyticket Integration,
    2026-09: "third [webhook] to delete/archive when user does not
    renew for x days"): admin-configurable threshold for the new
    subscriptions.archive_stale sweep (app.subscriptions.service.
    archive_stale_subscriptions) - None/0 = archiving disabled for this
    application (existing behavior, opt-in).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7e0230c7e509'
down_revision: Union[str, None] = 'c2d4e6f8a1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('return_url', sa.String(length=500), nullable=True))
    op.add_column('applications', sa.Column('payu_webhook_base_url', sa.String(length=500), nullable=True))
    op.add_column('applications', sa.Column('archive_after_days', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'archive_after_days')
    op.drop_column('applications', 'payu_webhook_base_url')
    op.drop_column('applications', 'return_url')
