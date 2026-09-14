"""registration form field duplicate validation + custom message

Revision ID: f2a8c3d91b45
Revises: e45b1604043b
Create Date: 2026-09-13 00:00:00.000000

Vishal's follow-up on the Registration Form admin module: "Add one more
checkbox to validate duplication (it means any record have similar value
then it will not allow user to enter same name) & Validation message for
that duplication also should be configured."

Two new columns, mirroring the validation_pattern/validation_message pair
added in 9f3a1c7d5e02:

  - check_duplicate: when true, a submitted value for this field is
    rejected if it already exists (case-insensitively, trimmed) on any
    OTHER customer's registration data for this application - see
    app.forms.validation.check_duplicate_registration_data(). NOT NULL
    with a false server default so every existing field keeps behaving
    exactly as before (no duplicate check) until an admin explicitly
    turns it on.
  - duplicate_message: the error shown on a match - falls back to a
    generic "<label> already exists" when unset.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a8c3d91b45'
down_revision: Union[str, None] = 'e45b1604043b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'registration_form_fields',
        sa.Column('check_duplicate', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('registration_form_fields', sa.Column('duplicate_message', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('registration_form_fields', 'duplicate_message')
    op.drop_column('registration_form_fields', 'check_duplicate')
