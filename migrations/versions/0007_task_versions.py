"""Versioned task edits and bounded task instructions; preserve existing dates."""

import sqlalchemy as sa
from alembic import op

revision = "0007_task_versions"
down_revision = "0006_user_time_zones"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tasks", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("tasks", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("tasks", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(sa.text("UPDATE tasks SET updated_at = created_at"))
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
