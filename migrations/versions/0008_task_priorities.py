"""Task triage priorities; existing tasks retain their versions and timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "0008_task_priorities"
down_revision = "0007_task_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"))


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
