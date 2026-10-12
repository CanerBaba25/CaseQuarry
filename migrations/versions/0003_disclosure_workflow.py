"""Derived productions, approval records, immutable Bates and review allocation."""

import sqlalchemy as sa
from alembic import op

revision="0003_disclosure_workflow"
down_revision="0002_local_ai"
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('bates_counters',
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('next_number', sa.BigInteger(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'case_id', 'prefix')
    )
    op.create_index(op.f('ix_bates_counters_case_id'), 'bates_counters', ['case_id'], unique=False)
    op.create_index(op.f('ix_bates_counters_tenant_id'), 'bates_counters', ['tenant_id'], unique=False)
    op.create_table('productions',
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('approval_reason', sa.Text(), nullable=True),
    sa.Column('bates_prefix', sa.String(length=16), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('redactions', sa.JSON(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('counts', sa.JSON(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_productions_case_id'), 'productions', ['case_id'], unique=False)
    op.create_index(op.f('ix_productions_state'), 'productions', ['state'], unique=False)
    op.create_index(op.f('ix_productions_tenant_id'), 'productions', ['tenant_id'], unique=False)
    op.create_table('issue_reviews',
    sa.Column('issue_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('reviewed_by', sa.String(length=36), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('evidence_snapshot', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('issue_id')
    )
    op.create_index(op.f('ix_issue_reviews_case_id'), 'issue_reviews', ['case_id'], unique=False)
    op.create_index(op.f('ix_issue_reviews_tenant_id'), 'issue_reviews', ['tenant_id'], unique=False)
    op.create_table('review_assignments',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('assignee_id', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('review_set_id', sa.String(length=36), nullable=True),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['assignee_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['review_set_id'], ['review_sets.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_assignments_case_id'), 'review_assignments', ['case_id'], unique=False)
    op.create_index(op.f('ix_review_assignments_tenant_id'), 'review_assignments', ['tenant_id'], unique=False)
    op.create_table('active_review_allocations',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('assignment_id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['assignment_id'], ['review_assignments.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('evidence_id')
    )
    op.create_index(op.f('ix_active_review_allocations_assignment_id'), 'active_review_allocations', ['assignment_id'], unique=False)
    op.create_index(op.f('ix_active_review_allocations_case_id'), 'active_review_allocations', ['case_id'], unique=False)
    op.create_index(op.f('ix_active_review_allocations_tenant_id'), 'active_review_allocations', ['tenant_id'], unique=False)
    op.create_table('production_items',
    sa.Column('production_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('prefix', sa.String(length=16), nullable=False),
    sa.Column('start_number', sa.BigInteger(), nullable=False),
    sa.Column('end_number', sa.BigInteger(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('produced_sha256', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['production_id'], ['productions.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'prefix', 'start_number'),
    sa.UniqueConstraint('production_id', 'evidence_id')
    )
    op.create_index(op.f('ix_production_items_case_id'), 'production_items', ['case_id'], unique=False)
    op.create_index(op.f('ix_production_items_production_id'), 'production_items', ['production_id'], unique=False)
    op.create_index(op.f('ix_production_items_tenant_id'), 'production_items', ['tenant_id'], unique=False)
    op.create_table('redactions',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('selection', sa.JSON(), nullable=False),
    sa.Column('snapshot', sa.JSON(), nullable=False),
    sa.Column('verification', sa.JSON(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('error_code', sa.String(length=100), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('lease_token', sa.String(length=36), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_redactions_case_id'), 'redactions', ['case_id'], unique=False)
    op.create_index(op.f('ix_redactions_evidence_id'), 'redactions', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_redactions_state'), 'redactions', ['state'], unique=False)
    op.create_index(op.f('ix_redactions_tenant_id'), 'redactions', ['tenant_id'], unique=False)
    op.create_table('review_assignment_items',
    sa.Column('assignment_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['assignment_id'], ['review_assignments.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('assignment_id', 'evidence_id')
    )
    op.create_index(op.f('ix_review_assignment_items_case_id'), 'review_assignment_items', ['case_id'], unique=False)
    op.create_index(op.f('ix_review_assignment_items_tenant_id'), 'review_assignment_items', ['tenant_id'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_review_assignment_items_tenant_id'), table_name='review_assignment_items')
    op.drop_index(op.f('ix_review_assignment_items_case_id'), table_name='review_assignment_items')
    op.drop_table('review_assignment_items')
    op.drop_index(op.f('ix_redactions_tenant_id'), table_name='redactions')
    op.drop_index(op.f('ix_redactions_state'), table_name='redactions')
    op.drop_index(op.f('ix_redactions_evidence_id'), table_name='redactions')
    op.drop_index(op.f('ix_redactions_case_id'), table_name='redactions')
    op.drop_table('redactions')
    op.drop_index(op.f('ix_production_items_tenant_id'), table_name='production_items')
    op.drop_index(op.f('ix_production_items_production_id'), table_name='production_items')
    op.drop_index(op.f('ix_production_items_case_id'), table_name='production_items')
    op.drop_table('production_items')
    op.drop_index(op.f('ix_active_review_allocations_tenant_id'), table_name='active_review_allocations')
    op.drop_index(op.f('ix_active_review_allocations_case_id'), table_name='active_review_allocations')
    op.drop_index(op.f('ix_active_review_allocations_assignment_id'), table_name='active_review_allocations')
    op.drop_table('active_review_allocations')
    op.drop_index(op.f('ix_review_assignments_tenant_id'), table_name='review_assignments')
    op.drop_index(op.f('ix_review_assignments_case_id'), table_name='review_assignments')
    op.drop_table('review_assignments')
    op.drop_index(op.f('ix_issue_reviews_tenant_id'), table_name='issue_reviews')
    op.drop_index(op.f('ix_issue_reviews_case_id'), table_name='issue_reviews')
    op.drop_table('issue_reviews')
    op.drop_index(op.f('ix_productions_tenant_id'), table_name='productions')
    op.drop_index(op.f('ix_productions_state'), table_name='productions')
    op.drop_index(op.f('ix_productions_case_id'), table_name='productions')
    op.drop_table('productions')
    op.drop_index(op.f('ix_bates_counters_tenant_id'), table_name='bates_counters')
    op.drop_index(op.f('ix_bates_counters_case_id'), table_name='bates_counters')
    op.drop_table('bates_counters')
