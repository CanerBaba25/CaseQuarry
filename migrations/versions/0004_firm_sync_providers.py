"""Central firm sync revisions and encrypted user-owned provider credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0004_firm_sync_providers"
down_revision = "0003_disclosure_workflow"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sync_revisions",
        sa.Column("scope_key", sa.String(length=100), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.PrimaryKeyConstraint("scope_key"),
    )
    op.create_index("ix_sync_revisions_tenant_id", "sync_revisions", ["tenant_id"], unique=False)
    op.create_index("ix_sync_revisions_case_id", "sync_revisions", ["case_id"], unique=False)
    op.create_table(
        "provider_credentials",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("last_four", sa.String(length=4), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "provider"),
    )
    op.create_index("ix_provider_credentials_tenant_id", "provider_credentials", ["tenant_id"], unique=False)
    op.create_index("ix_provider_credentials_user_id", "provider_credentials", ["user_id"], unique=False)


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
