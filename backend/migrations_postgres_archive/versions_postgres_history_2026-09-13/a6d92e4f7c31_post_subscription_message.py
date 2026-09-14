"""configurable post-subscription confirmation message

Revision ID: a6d92e4f7c31
Revises: f2a8c3d91b45
Create Date: 2026-09-13 00:00:00.000000

Vishal's follow-up: "show message 'You have successfully subscribed, you
will get your credentials in sometime' for first time subscription...
This message also should be configurable."

One new nullable column on `applications` - `post_subscription_message`.
Nullable rather than a hardcoded server_default so an unset value falls
back to the built-in default text in code
(app.applications.config_schemas.DEFAULT_POST_SUBSCRIPTION_MESSAGE),
same fallback convention as validation_message/duplicate_message on
registration form fields.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a6d92e4f7c31'
down_revision: Union[str, None] = 'f2a8c3d91b45'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('post_subscription_message', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'post_subscription_message')
