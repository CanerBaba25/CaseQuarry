"""Optional manually entered task dates and indexed cross-matter work lists."""

import sqlalchemy as sa
from alembic import op

revision = "0005_task_due_dates"
down_revision = "0004_firm_sync_providers"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("due_date", sa.Date(), nullable=True))
    op.create_index("ix_tasks_worklist_due", "tasks", ["tenant_id", "assigned_to", "state", "due_date", "id"], unique=False)


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
