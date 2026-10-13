"""Per-user IANA timezone preferences; existing accounts keep UTC."""

import sqlalchemy as sa
from alembic import op

revision = "0006_user_time_zones"
down_revision = "0005_task_due_dates"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("time_zone", sa.String(length=100), nullable=False, server_default="UTC"))


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
