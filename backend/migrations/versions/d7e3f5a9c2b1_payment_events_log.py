"""payment_events: append-only payment history log

Revision ID: d7e3f5a9c2b1
Revises: c4d2a8e61f93
Create Date: 2026-10-01 18:00:00.000000

One row per thing that happened to a payment - started (with the surl/furl
sent to PayU and where the request came from), PayU browser return, PayU
server webhook, rejected status-page token, reconciliation check - see
app.payments.models.PaymentEvent and app.payments.events.

New table only; no existing data is touched. transaction_id is a plain
indexed string, not a foreign key, so events for unknown txnids can be
stored too.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7e3f5a9c2b1'
down_revision: Union[str, None] = 'c4d2a8e61f93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('transaction_id', sa.String(length=30), nullable=True),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('channel', sa.String(length=30), nullable=True),
        sa.Column('endpoint', sa.String(length=255), nullable=True),
        sa.Column('initiated_from', sa.String(length=500), nullable=True),
        sa.Column('surl_sent', sa.String(length=500), nullable=True),
        sa.Column('furl_sent', sa.String(length=500), nullable=True),
        sa.Column('return_url', sa.String(length=500), nullable=True),
        sa.Column('source_ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('gateway_status', sa.String(length=30), nullable=True),
        sa.Column('gateway_transaction_id', sa.String(length=150), nullable=True),
        sa.Column('hash_verified', sa.Boolean(), nullable=True),
        sa.Column('result', sa.String(length=40), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payment_events_transaction_id'), 'payment_events', ['transaction_id'], unique=False)
    op.create_index(op.f('ix_payment_events_event_type'), 'payment_events', ['event_type'], unique=False)
    op.create_index('ix_payment_events_created_at', 'payment_events', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_payment_events_created_at', table_name='payment_events')
    op.drop_index(op.f('ix_payment_events_event_type'), table_name='payment_events')
    op.drop_index(op.f('ix_payment_events_transaction_id'), table_name='payment_events')
    op.drop_table('payment_events')
