"""Manual custodian hold notices; preserve all existing preservation records."""

import sqlalchemy as sa
from alembic import op

revision = "0010_manual_hold_notices"
down_revision = "0009_user_language"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hold_notices",
        sa.Column("hold_id", sa.String(36), sa.ForeignKey("legal_holds.id"), nullable=False),
        sa.Column("custodian_id", sa.String(36), sa.ForeignKey("custodians.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("notice_text", sa.Text(), nullable=False),
        sa.Column("notice_text_sha256", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_name", sa.String(200), nullable=False),
        sa.Column("acknowledged_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_count", sa.Integer(), nullable=False),
        sa.Column("last_reminded_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("last_reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_reminder_date", sa.Date(), nullable=True),
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False),
        sa.UniqueConstraint("hold_id", "custodian_id", name="uq_hold_notice_custodian"),
    )
    for column in ("hold_id", "custodian_id", "tenant_id", "case_id"):
        op.create_index(f"ix_hold_notices_{column}", "hold_notices", [column])
    op.create_index("ix_hold_notices_scope_page", "hold_notices", ["tenant_id", "case_id", "hold_id", "id"])


def downgrade():
    raise RuntimeError("Downgrades are disabled: restore a verified backup into a separate instance.")
