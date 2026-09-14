"""widen plans.description to text

Revision ID: a4f7c9e2b6d1
Revises: 1f06a0f4b4a6
Create Date: 2026-08-31 00:00:00.000000

plans.description now holds sanitized rich-text HTML (bold/italic/bullet
+numbered lists - spec section 51's Plans admin module, app.plans.sanitize)
rather than plain text, so the old VARCHAR(2000) cap is widened to an
unbounded TEXT column. Postgres ALTER COLUMN TYPE VARCHAR -> TEXT is a
metadata-only change (no table rewrite, no data loss) since TEXT is a
strict superset of VARCHAR(n).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4f7c9e2b6d1'
down_revision: Union[str, None] = '1f06a0f4b4a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('plans', 'description', existing_type=sa.String(length=2000), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    # Truncates any description longer than 2000 chars back down - accepted
    # lossy downgrade, matching this repo's existing practice for widening
    # migrations (there is no non-lossy way to shrink a column back down).
    op.execute("UPDATE plans SET description = LEFT(description, 2000) WHERE description IS NOT NULL")
    op.alter_column('plans', 'description', existing_type=sa.Text(), type_=sa.String(length=2000), existing_nullable=True)
