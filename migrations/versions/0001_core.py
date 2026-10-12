"""Core evidence preservation and matter review schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('audit_heads',
    sa.Column('scope_key', sa.String(length=100), nullable=False),
    sa.Column('sequence', sa.BigInteger(), nullable=False),
    sa.Column('event_hash', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('scope_key')
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=100), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('tenants',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('mfa_secret', sa.Text(), nullable=True),
    sa.Column('mfa_enabled', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_tenant_id'), 'users', ['tenant_id'], unique=False)
    op.create_table('cases',
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('matter_number', sa.String(length=100), nullable=False),
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('client', sa.String(length=200), nullable=False),
    sa.Column('jurisdiction', sa.String(length=200), nullable=False),
    sa.Column('case_type', sa.String(length=100), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'matter_number')
    )
    op.create_index(op.f('ix_cases_tenant_id'), 'cases', ['tenant_id'], unique=False)
    op.create_table('login_sessions',
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_login_sessions_user_id'), 'login_sessions', ['user_id'], unique=False)
    op.create_table('audit_events',
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=True),
    sa.Column('actor_id', sa.String(length=36), nullable=True),
    sa.Column('sequence', sa.BigInteger(), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('target_type', sa.String(length=100), nullable=False),
    sa.Column('target_id', sa.String(length=100), nullable=False),
    sa.Column('request_id', sa.String(length=100), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('event_hash', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_scope_sequence', 'audit_events', ['tenant_id', 'case_id', 'sequence'], unique=False)
    op.create_table('custodians',
    sa.Column('display_name', sa.String(length=200), nullable=False),
    sa.Column('organization', sa.String(length=200), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_custodians_case_id'), 'custodians', ['case_id'], unique=False)
    op.create_index(op.f('ix_custodians_tenant_id'), 'custodians', ['tenant_id'], unique=False)
    op.create_table('exports',
    sa.Column('requested_by', sa.String(length=36), nullable=False),
    sa.Column('format', sa.String(length=20), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('evidence_ids', sa.JSON(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=True),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('counts', sa.JSON(), nullable=False),
    sa.Column('reviews_snapshot', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_exports_case_id'), 'exports', ['case_id'], unique=False)
    op.create_index(op.f('ix_exports_tenant_id'), 'exports', ['tenant_id'], unique=False)
    op.create_table('issues',
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_issues_case_id'), 'issues', ['case_id'], unique=False)
    op.create_index(op.f('ix_issues_tenant_id'), 'issues', ['tenant_id'], unique=False)
    op.create_table('legal_holds',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('released_by', sa.String(length=36), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['released_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_legal_holds_case_id'), 'legal_holds', ['case_id'], unique=False)
    op.create_index(op.f('ix_legal_holds_tenant_id'), 'legal_holds', ['tenant_id'], unique=False)
    op.create_table('members',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=30), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'user_id')
    )
    op.create_index(op.f('ix_members_case_id'), 'members', ['case_id'], unique=False)
    op.create_index(op.f('ix_members_tenant_id'), 'members', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_members_user_id'), 'members', ['user_id'], unique=False)
    op.create_table('original_objects',
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('media_type', sa.String(length=200), nullable=False),
    sa.Column('integrity_status', sa.String(length=30), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'case_id', 'sha256')
    )
    op.create_index(op.f('ix_original_objects_case_id'), 'original_objects', ['case_id'], unique=False)
    op.create_index(op.f('ix_original_objects_sha256'), 'original_objects', ['sha256'], unique=False)
    op.create_index(op.f('ix_original_objects_tenant_id'), 'original_objects', ['tenant_id'], unique=False)
    op.create_table('people',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('state', sa.String(length=50), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'email')
    )
    op.create_index(op.f('ix_people_case_id'), 'people', ['case_id'], unique=False)
    op.create_index(op.f('ix_people_email'), 'people', ['email'], unique=False)
    op.create_index(op.f('ix_people_tenant_id'), 'people', ['tenant_id'], unique=False)
    op.create_table('review_sets',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('query_spec', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_review_sets_case_id'), 'review_sets', ['case_id'], unique=False)
    op.create_index(op.f('ix_review_sets_tenant_id'), 'review_sets', ['tenant_id'], unique=False)
    op.create_table('saved_searches',
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('query_spec', sa.JSON(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_saved_searches_case_id'), 'saved_searches', ['case_id'], unique=False)
    op.create_index(op.f('ix_saved_searches_tenant_id'), 'saved_searches', ['tenant_id'], unique=False)
    op.create_table('tasks',
    sa.Column('title', sa.String(length=300), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('assigned_to', sa.String(length=36), nullable=True),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_case_id'), 'tasks', ['case_id'], unique=False)
    op.create_index(op.f('ix_tasks_tenant_id'), 'tasks', ['tenant_id'], unique=False)
    op.create_table('sources',
    sa.Column('custodian_id', sa.String(length=36), nullable=True),
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('kind', sa.String(length=100), nullable=False),
    sa.Column('operator_id', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['custodian_id'], ['custodians.id'], ),
    sa.ForeignKeyConstraint(['operator_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sources_case_id'), 'sources', ['case_id'], unique=False)
    op.create_index(op.f('ix_sources_tenant_id'), 'sources', ['tenant_id'], unique=False)
    op.create_table('import_batches',
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('submitted_by', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('counts', sa.JSON(), nullable=False),
    sa.Column('errors', sa.JSON(), nullable=False),
    sa.Column('files', sa.JSON(), nullable=False),
    sa.Column('checkpoint', sa.JSON(), nullable=False),
    sa.Column('parser_version', sa.String(length=100), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('idempotency_key', sa.String(length=100), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['submitted_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'idempotency_key')
    )
    op.create_index(op.f('ix_import_batches_case_id'), 'import_batches', ['case_id'], unique=False)
    op.create_index(op.f('ix_import_batches_state'), 'import_batches', ['state'], unique=False)
    op.create_index(op.f('ix_import_batches_tenant_id'), 'import_batches', ['tenant_id'], unique=False)
    op.create_table('source_occurrences',
    sa.Column('original_id', sa.String(length=36), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=False),
    sa.Column('original_name', sa.String(length=500), nullable=False),
    sa.Column('original_path', sa.Text(), nullable=False),
    sa.Column('source_offset', sa.String(length=200), nullable=False),
    sa.Column('occurrence_key', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batches.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['original_id'], ['original_objects.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('case_id', 'occurrence_key')
    )
    op.create_index(op.f('ix_source_occurrences_batch_id'), 'source_occurrences', ['batch_id'], unique=False)
    op.create_index(op.f('ix_source_occurrences_case_id'), 'source_occurrences', ['case_id'], unique=False)
    op.create_index(op.f('ix_source_occurrences_original_id'), 'source_occurrences', ['original_id'], unique=False)
    op.create_index(op.f('ix_source_occurrences_source_id'), 'source_occurrences', ['source_id'], unique=False)
    op.create_index(op.f('ix_source_occurrences_tenant_id'), 'source_occurrences', ['tenant_id'], unique=False)
    op.create_table('upload_sessions',
    sa.Column('user_id', sa.String(length=36), nullable=False),
    sa.Column('filename', sa.String(length=500), nullable=False),
    sa.Column('byte_size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=True),
    sa.Column('part_size', sa.Integer(), nullable=False),
    sa.Column('parts', sa.JSON(), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('state', sa.String(length=30), nullable=False),
    sa.Column('batch_id', sa.String(length=36), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['import_batches.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_upload_sessions_case_id'), 'upload_sessions', ['case_id'], unique=False)
    op.create_index(op.f('ix_upload_sessions_tenant_id'), 'upload_sessions', ['tenant_id'], unique=False)
    op.create_table('evidence',
    sa.Column('original_id', sa.String(length=36), nullable=False),
    sa.Column('occurrence_id', sa.String(length=36), nullable=False),
    sa.Column('source_id', sa.String(length=36), nullable=False),
    sa.Column('custodian_id', sa.String(length=36), nullable=True),
    sa.Column('parent_id', sa.String(length=36), nullable=True),
    sa.Column('item_type', sa.String(length=30), nullable=False),
    sa.Column('title', sa.String(length=1000), nullable=False),
    sa.Column('filename', sa.String(length=500), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('text_hash', sa.String(length=64), nullable=False),
    sa.Column('text_version', sa.Integer(), nullable=False),
    sa.Column('date_raw', sa.Text(), nullable=False),
    sa.Column('date_utc', sa.DateTime(timezone=True), nullable=True),
    sa.Column('timezone_source', sa.String(length=50), nullable=False),
    sa.Column('sender', sa.String(length=320), nullable=False),
    sa.Column('recipients', sa.Text(), nullable=False),
    sa.Column('email_metadata', sa.JSON(), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=False),
    sa.Column('has_attachments', sa.Boolean(), nullable=False),
    sa.Column('parser_state', sa.String(length=30), nullable=False),
    sa.Column('parser_error', sa.Text(), nullable=True),
    sa.Column('review_status', sa.String(length=30), nullable=False),
    sa.Column('privilege_status', sa.String(length=30), nullable=False),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.Column('bookmarked', sa.Boolean(), nullable=False),
    sa.Column('review_version', sa.Integer(), nullable=False),
    sa.Column('assigned_to', sa.String(length=36), nullable=True),
    sa.Column('thread_id', sa.String(length=64), nullable=True),
    sa.Column('body_fingerprint', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['occurrence_id'], ['source_occurrences.id'], ),
    sa.ForeignKeyConstraint(['original_id'], ['original_objects.id'], ),
    sa.ForeignKeyConstraint(['parent_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['source_id'], ['sources.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('occurrence_id')
    )
    op.create_index(op.f('ix_evidence_body_fingerprint'), 'evidence', ['body_fingerprint'], unique=False)
    op.create_index('ix_evidence_case_date_id', 'evidence', ['case_id', 'date_utc', 'id'], unique=False)
    op.create_index(op.f('ix_evidence_case_id'), 'evidence', ['case_id'], unique=False)
    op.create_index(op.f('ix_evidence_custodian_id'), 'evidence', ['custodian_id'], unique=False)
    op.create_index(op.f('ix_evidence_date_utc'), 'evidence', ['date_utc'], unique=False)
    op.create_index(op.f('ix_evidence_item_type'), 'evidence', ['item_type'], unique=False)
    op.create_index(op.f('ix_evidence_original_id'), 'evidence', ['original_id'], unique=False)
    op.create_index(op.f('ix_evidence_parent_id'), 'evidence', ['parent_id'], unique=False)
    op.create_index(op.f('ix_evidence_parser_state'), 'evidence', ['parser_state'], unique=False)
    op.create_index(op.f('ix_evidence_review_status'), 'evidence', ['review_status'], unique=False)
    op.create_index(op.f('ix_evidence_sender'), 'evidence', ['sender'], unique=False)
    op.create_index(op.f('ix_evidence_source_id'), 'evidence', ['source_id'], unique=False)
    op.create_index(op.f('ix_evidence_tenant_id'), 'evidence', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_evidence_thread_id'), 'evidence', ['thread_id'], unique=False)
    op.create_table('derived_artifacts',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('kind', sa.String(length=50), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('parser_version', sa.String(length=100), nullable=False),
    sa.Column('storage_key', sa.String(length=500), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_derived_artifacts_case_id'), 'derived_artifacts', ['case_id'], unique=False)
    op.create_index(op.f('ix_derived_artifacts_evidence_id'), 'derived_artifacts', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_derived_artifacts_tenant_id'), 'derived_artifacts', ['tenant_id'], unique=False)
    op.create_table('email_participants',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('person_id', sa.String(length=36), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['person_id'], ['people.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('evidence_id', 'person_id', 'role')
    )
    op.create_index(op.f('ix_email_participants_case_id'), 'email_participants', ['case_id'], unique=False)
    op.create_index(op.f('ix_email_participants_evidence_id'), 'email_participants', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_email_participants_person_id'), 'email_participants', ['person_id'], unique=False)
    op.create_index(op.f('ix_email_participants_role'), 'email_participants', ['role'], unique=False)
    op.create_index(op.f('ix_email_participants_tenant_id'), 'email_participants', ['tenant_id'], unique=False)
    op.create_index('ix_participant_case_person_role', 'email_participants', ['case_id', 'person_id', 'role'], unique=False)
    op.create_table('issue_links',
    sa.Column('issue_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('side', sa.String(length=30), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['issue_id'], ['issues.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_issue_links_case_id'), 'issue_links', ['case_id'], unique=False)
    op.create_index(op.f('ix_issue_links_issue_id'), 'issue_links', ['issue_id'], unique=False)
    op.create_index(op.f('ix_issue_links_tenant_id'), 'issue_links', ['tenant_id'], unique=False)
    op.create_table('review_set_items',
    sa.Column('set_id', sa.String(length=36), nullable=False),
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['set_id'], ['review_sets.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('set_id', 'evidence_id')
    )
    op.create_index(op.f('ix_review_set_items_case_id'), 'review_set_items', ['case_id'], unique=False)
    op.create_index(op.f('ix_review_set_items_tenant_id'), 'review_set_items', ['tenant_id'], unique=False)
    op.create_table('reviews',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('reviewer_id', sa.String(length=36), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('changes', sa.JSON(), nullable=False),
    sa.Column('note', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['reviewer_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reviews_case_id'), 'reviews', ['case_id'], unique=False)
    op.create_index(op.f('ix_reviews_evidence_id'), 'reviews', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_reviews_tenant_id'), 'reviews', ['tenant_id'], unique=False)
    op.create_table('text_spans',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('artifact_id', sa.String(length=36), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('char_start', sa.Integer(), nullable=False),
    sa.Column('char_end', sa.Integer(), nullable=False),
    sa.Column('text_hash', sa.String(length=64), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['artifact_id'], ['derived_artifacts.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_text_spans_case_id'), 'text_spans', ['case_id'], unique=False)
    op.create_index(op.f('ix_text_spans_evidence_id'), 'text_spans', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_text_spans_tenant_id'), 'text_spans', ['tenant_id'], unique=False)
    op.create_table('annotations',
    sa.Column('evidence_id', sa.String(length=36), nullable=False),
    sa.Column('span_id', sa.String(length=36), nullable=True),
    sa.Column('author_id', sa.String(length=36), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.String(length=36), nullable=False),
    sa.Column('case_id', sa.String(length=36), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
    sa.ForeignKeyConstraint(['evidence_id'], ['evidence.id'], ),
    sa.ForeignKeyConstraint(['span_id'], ['text_spans.id'], ),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_annotations_case_id'), 'annotations', ['case_id'], unique=False)
    op.create_index(op.f('ix_annotations_evidence_id'), 'annotations', ['evidence_id'], unique=False)
    op.create_index(op.f('ix_annotations_tenant_id'), 'annotations', ['tenant_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_annotations_tenant_id'), table_name='annotations')
    op.drop_index(op.f('ix_annotations_evidence_id'), table_name='annotations')
    op.drop_index(op.f('ix_annotations_case_id'), table_name='annotations')
    op.drop_table('annotations')
    op.drop_index(op.f('ix_text_spans_tenant_id'), table_name='text_spans')
    op.drop_index(op.f('ix_text_spans_evidence_id'), table_name='text_spans')
    op.drop_index(op.f('ix_text_spans_case_id'), table_name='text_spans')
    op.drop_table('text_spans')
    op.drop_index(op.f('ix_reviews_tenant_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_evidence_id'), table_name='reviews')
    op.drop_index(op.f('ix_reviews_case_id'), table_name='reviews')
    op.drop_table('reviews')
    op.drop_index(op.f('ix_review_set_items_tenant_id'), table_name='review_set_items')
    op.drop_index(op.f('ix_review_set_items_case_id'), table_name='review_set_items')
    op.drop_table('review_set_items')
    op.drop_index(op.f('ix_issue_links_tenant_id'), table_name='issue_links')
    op.drop_index(op.f('ix_issue_links_issue_id'), table_name='issue_links')
    op.drop_index(op.f('ix_issue_links_case_id'), table_name='issue_links')
    op.drop_table('issue_links')
    op.drop_index('ix_participant_case_person_role', table_name='email_participants')
    op.drop_index(op.f('ix_email_participants_tenant_id'), table_name='email_participants')
    op.drop_index(op.f('ix_email_participants_role'), table_name='email_participants')
    op.drop_index(op.f('ix_email_participants_person_id'), table_name='email_participants')
    op.drop_index(op.f('ix_email_participants_evidence_id'), table_name='email_participants')
    op.drop_index(op.f('ix_email_participants_case_id'), table_name='email_participants')
    op.drop_table('email_participants')
    op.drop_index(op.f('ix_derived_artifacts_tenant_id'), table_name='derived_artifacts')
    op.drop_index(op.f('ix_derived_artifacts_evidence_id'), table_name='derived_artifacts')
    op.drop_index(op.f('ix_derived_artifacts_case_id'), table_name='derived_artifacts')
    op.drop_table('derived_artifacts')
    op.drop_index(op.f('ix_evidence_thread_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_tenant_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_source_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_sender'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_review_status'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_parser_state'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_parent_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_original_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_item_type'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_date_utc'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_custodian_id'), table_name='evidence')
    op.drop_index(op.f('ix_evidence_case_id'), table_name='evidence')
    op.drop_index('ix_evidence_case_date_id', table_name='evidence')
    op.drop_index(op.f('ix_evidence_body_fingerprint'), table_name='evidence')
    op.drop_table('evidence')
    op.drop_index(op.f('ix_upload_sessions_tenant_id'), table_name='upload_sessions')
    op.drop_index(op.f('ix_upload_sessions_case_id'), table_name='upload_sessions')
    op.drop_table('upload_sessions')
    op.drop_index(op.f('ix_source_occurrences_tenant_id'), table_name='source_occurrences')
    op.drop_index(op.f('ix_source_occurrences_source_id'), table_name='source_occurrences')
    op.drop_index(op.f('ix_source_occurrences_original_id'), table_name='source_occurrences')
    op.drop_index(op.f('ix_source_occurrences_case_id'), table_name='source_occurrences')
    op.drop_index(op.f('ix_source_occurrences_batch_id'), table_name='source_occurrences')
    op.drop_table('source_occurrences')
    op.drop_index(op.f('ix_import_batches_tenant_id'), table_name='import_batches')
    op.drop_index(op.f('ix_import_batches_state'), table_name='import_batches')
    op.drop_index(op.f('ix_import_batches_case_id'), table_name='import_batches')
    op.drop_table('import_batches')
    op.drop_index(op.f('ix_sources_tenant_id'), table_name='sources')
    op.drop_index(op.f('ix_sources_case_id'), table_name='sources')
    op.drop_table('sources')
    op.drop_index(op.f('ix_tasks_tenant_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_case_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_saved_searches_tenant_id'), table_name='saved_searches')
    op.drop_index(op.f('ix_saved_searches_case_id'), table_name='saved_searches')
    op.drop_table('saved_searches')
    op.drop_index(op.f('ix_review_sets_tenant_id'), table_name='review_sets')
    op.drop_index(op.f('ix_review_sets_case_id'), table_name='review_sets')
    op.drop_table('review_sets')
    op.drop_index(op.f('ix_people_tenant_id'), table_name='people')
    op.drop_index(op.f('ix_people_email'), table_name='people')
    op.drop_index(op.f('ix_people_case_id'), table_name='people')
    op.drop_table('people')
    op.drop_index(op.f('ix_original_objects_tenant_id'), table_name='original_objects')
    op.drop_index(op.f('ix_original_objects_sha256'), table_name='original_objects')
    op.drop_index(op.f('ix_original_objects_case_id'), table_name='original_objects')
    op.drop_table('original_objects')
    op.drop_index(op.f('ix_members_user_id'), table_name='members')
    op.drop_index(op.f('ix_members_tenant_id'), table_name='members')
    op.drop_index(op.f('ix_members_case_id'), table_name='members')
    op.drop_table('members')
    op.drop_index(op.f('ix_legal_holds_tenant_id'), table_name='legal_holds')
    op.drop_index(op.f('ix_legal_holds_case_id'), table_name='legal_holds')
    op.drop_table('legal_holds')
    op.drop_index(op.f('ix_issues_tenant_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_case_id'), table_name='issues')
    op.drop_table('issues')
    op.drop_index(op.f('ix_exports_tenant_id'), table_name='exports')
    op.drop_index(op.f('ix_exports_case_id'), table_name='exports')
    op.drop_table('exports')
    op.drop_index(op.f('ix_custodians_tenant_id'), table_name='custodians')
    op.drop_index(op.f('ix_custodians_case_id'), table_name='custodians')
    op.drop_table('custodians')
    op.drop_index('ix_audit_scope_sequence', table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index(op.f('ix_login_sessions_user_id'), table_name='login_sessions')
    op.drop_table('login_sessions')
    op.drop_index(op.f('ix_cases_tenant_id'), table_name='cases')
    op.drop_table('cases')
    op.drop_index(op.f('ix_users_tenant_id'), table_name='users')
    op.drop_table('users')
    op.drop_table('tenants')
    op.drop_table('settings')
    op.drop_table('audit_heads')
