"""webhook delivery request/response headers

Revision ID: 4b7d9e1f2a83
Revises: 9f3a1c7d5e02
Create Date: 2026-09-11 00:00:00.000002

Vishal's follow-up on the admin Webhook Logs screen: "Webhook API is not
getting reached or logging headers, statuscode, etc.. from API." A
WebhookDelivery row already stored http_status/response_body but never
the actual HTTP headers exchanged - so debugging a signature mismatch,
a proxy/WAF rejection, or a content-type issue on the destination's
response meant guessing, not looking. This adds two nullable JSON
columns:

  - request_headers: exactly what this app sent (Content-Type,
    X-Webhook-Signature, and any admin-supplied extras from the ad-hoc
    test tool).
  - response_headers: exactly what the destination sent back.

Both nullable - every pre-existing delivery row simply has neither
populated (no way to retroactively know what was sent for an attempt
that already happened), and an attempt that raised before any response
came back (e.g. a connection error/timeout) never gets response_headers
either way.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b7d9e1f2a83'
down_revision: Union[str, None] = '9f3a1c7d5e02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('webhook_deliveries', sa.Column('request_headers', sa.JSON(), nullable=True))
    op.add_column('webhook_deliveries', sa.Column('response_headers', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('webhook_deliveries', 'response_headers')
    op.drop_column('webhook_deliveries', 'request_headers')
