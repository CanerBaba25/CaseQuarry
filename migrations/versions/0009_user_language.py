"""Shared interface language preferences; preserve existing accounts and evidence."""

import sqlalchemy as sa
from alembic import op

revision = "0009_user_language"
down_revision = "0008_task_priorities"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("language", sa.String(length=10), nullable=False, server_default="en"))


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
