"""webhook delivery call/response timing

Revision ID: e45b1604043b
Revises: 4b7d9e1f2a83
Create Date: 2026-09-11 00:00:00.000003

Vishal: "Log webhook call time and response completion time." A
WebhookDelivery row already recorded that an attempt happened
(last_attempt_at, set right after the outbound call finishes) but never
when it actually STARTED, nor how long it took - useful on its own, and
directly useful for the timeout/connection-pool freezing issue fixed in
the same session (2026-09-11 follow-up 7): being able to see exactly how
long a specific delivery's call took is the fastest way to confirm the
new bounded httpx timeout is actually working as intended.

Adds two nullable columns:

  - attempt_started_at: wall-clock timestamp for when this attempt's
    outbound HTTP call began (last_attempt_at already doubles as the
    completion timestamp - it is set right after the call returns,
    success or failure).
  - duration_ms: elapsed time for the call, measured with a monotonic
    clock so it is never skewed by a wall-clock adjustment mid-attempt.

Both nullable - every pre-existing delivery row simply has neither
populated (no way to retroactively know how long an attempt that
already happened took), same convention as every other additive column
in this table.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e45b1604043b'
down_revision: Union[str, None] = '4b7d9e1f2a83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('webhook_deliveries', sa.Column('attempt_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('webhook_deliveries', sa.Column('duration_ms', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('webhook_deliveries', 'duration_ms')
    op.drop_column('webhook_deliveries', 'attempt_started_at')
