"""admin config restructure: webhook params/retry/escalation, SMTP config

Revision ID: c2d4e6f8a1b3
Revises: b7e3d4f1a9c2
Create Date: 2026-09-02 00:00:00.000000

Backs the restructured admin Configuration page (Application / Payment
Gateway / Everyticket Integration / Notifications), per Vishal's explicit
field list:

  - Everyticket Integration: custom key/value POST parameters sent with
    every webhook delivery (webhook_extra_params), an admin-configurable
    retry limit overriding WEBHOOK_RETRY_SCHEDULE_MINUTES' own length
    (webhook_retry_limit), and an escalation email sent once a delivery
    is EXHAUSTED (webhook_escalation_emails/_subject/_body - body is
    admin-edited rich text, sanitized the same way Plan.description is).
  - Notifications: real per-application SMTP transport overrides
    (smtp_host/port/username/password/use_tls), alongside the existing
    sender name/address/reply-to fields - previously SMTP transport was
    env-only (Settings.SMTP_*), with no admin-editable override.

PayU per-mode (test/live) credentials are deliberately NOT a migration -
they're stored via the existing generic system_settings key/value store
(app.core.settings_service, same pattern as the invoice tax config and
security config) since they're keyed by gateway+mode rather than being a
single per-application value, so no schema change is needed for them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d4e6f8a1b3'
down_revision: Union[str, None] = 'b7e3d4f1a9c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('webhook_extra_params', sa.JSON(), nullable=True))
    op.add_column('applications', sa.Column('webhook_retry_limit', sa.Integer(), nullable=True))
    op.add_column('applications', sa.Column('webhook_escalation_emails', sa.String(length=1000), nullable=True))
    op.add_column('applications', sa.Column('webhook_escalation_email_subject', sa.String(length=255), nullable=True))
    op.add_column('applications', sa.Column('webhook_escalation_email_body', sa.Text(), nullable=True))
    op.add_column('applications', sa.Column('smtp_host', sa.String(length=255), nullable=True))
    op.add_column('applications', sa.Column('smtp_port', sa.Integer(), nullable=True))
    op.add_column('applications', sa.Column('smtp_username', sa.String(length=255), nullable=True))
    op.add_column('applications', sa.Column('smtp_password', sa.String(length=500), nullable=True))
    op.add_column('applications', sa.Column('smtp_use_tls', sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'smtp_use_tls')
    op.drop_column('applications', 'smtp_password')
    op.drop_column('applications', 'smtp_username')
    op.drop_column('applications', 'smtp_port')
    op.drop_column('applications', 'smtp_host')
    op.drop_column('applications', 'webhook_escalation_email_body')
    op.drop_column('applications', 'webhook_escalation_email_subject')
    op.drop_column('applications', 'webhook_escalation_emails')
    op.drop_column('applications', 'webhook_retry_limit')
    op.drop_column('applications', 'webhook_extra_params')
