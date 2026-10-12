"""Separate optional local-model jobs and source quotations."""

import sqlalchemy as sa
from alembic import op

revision = "0002_local_ai"
down_revision = '0001_core'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ai_jobs',
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('task', sa.String(length=30), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('style', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('provider_endpoint', sa.String(length=300), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('prompt_version', sa.String(length=100), nullable=False),
    sa.Column('policy_revision', sa.Integer(), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('scope', sa.JSON(), nullable=False),
    sa.Column('coverage', sa.JSON(), nullable=False),
    sa.Column('source_refs', sa.JSON(), nullable=False),
    sa.Column('usage', sa.JSON(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=True),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_jobs_case_id'), 'ai_jobs', ['case_id'], unique=False)
    op.create_index('ix_ai_jobs_scope_state', 'ai_jobs', ['tenant_id', 'case_id', 'state'], unique=False)
    op.create_index(op.f('ix_ai_jobs_tenant_id'), 'ai_jobs', ['tenant_id'], unique=False)
    op.create_table('ai_results',
    sa.Column('job_id', sa.String(length=36), nullable=False),
    sa.Column('finding_index', sa.Integer(), nullable=False),
    sa.Column('claim', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=False),
    sa.Column('review_state', sa.String(length=30), nullable=False),
    sa.Column('reviewed_by', sa.String(length=36), nullable=True),
    sa.Column('review_reason', sa.Text(), nullable=True),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['ai_jobs.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'finding_index')
    )
    op.create_index(op.f('ix_ai_results_case_id'), 'ai_results', ['case_id'], unique=False)
    op.create_index(op.f('ix_ai_results_job_id'), 'ai_results', ['job_id'], unique=False)
    op.create_index(op.f('ix_ai_results_tenant_id'), 'ai_results', ['tenant_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_ai_results_tenant_id'), table_name='ai_results')
    op.drop_index(op.f('ix_ai_results_job_id'), table_name='ai_results')
    op.drop_index(op.f('ix_ai_results_case_id'), table_name='ai_results')
    op.drop_table('ai_results')
    op.drop_index(op.f('ix_ai_jobs_tenant_id'), table_name='ai_jobs')
    op.drop_index('ix_ai_jobs_scope_state', table_name='ai_jobs')
    op.drop_index(op.f('ix_ai_jobs_case_id'), table_name='ai_jobs')
    op.drop_table('ai_jobs')
