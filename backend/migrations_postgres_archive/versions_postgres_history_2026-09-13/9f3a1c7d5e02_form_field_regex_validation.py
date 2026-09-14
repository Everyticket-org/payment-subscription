"""registration form field regex validation + custom message

Revision ID: 9f3a1c7d5e02
Revises: 7e0230c7e509
Create Date: 2026-09-11 00:00:00.000001

Vishal's follow-up on the Registration Form admin module: "For forms -
give one more option for validation by Regex and validation message
fields to be set." registration_form_fields already had a generic,
never-enforced `validation_rules` JSON column - this adds two explicit,
typed columns instead so the admin UI has a plain regex input + a plain
message input rather than free-form JSON, and so
app.forms.validation.validate_registration_data() has something
concrete to enforce:

  - validation_pattern: an optional regex a submitted value must fully
    match (checked with re.fullmatch, same semantics as the HTML5
    `pattern` attribute).
  - validation_message: the error shown when validation_pattern doesn't
    match - falls back to a generic "<label> is not valid" when unset.

Both nullable - every existing field keeps validating exactly as before
(i.e. not at all beyond "required", which is enforced in the same pass)
until an admin explicitly sets a pattern.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f3a1c7d5e02'
down_revision: Union[str, None] = '7e0230c7e509'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('registration_form_fields', sa.Column('validation_pattern', sa.String(length=500), nullable=True))
    op.add_column('registration_form_fields', sa.Column('validation_message', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('registration_form_fields', 'validation_message')
    op.drop_column('registration_form_fields', 'validation_pattern')
