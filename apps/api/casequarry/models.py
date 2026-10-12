from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Identity:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Scoped:
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id"), index=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Tenant(Identity, Base):
    __tablename__ = "tenants"
    name: Mapped[str] = mapped_column(String(200))


class User(Identity, Base):
    __tablename__ = "users"
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), default="reviewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Identity, Base):
    __tablename__ = "login_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class Case(Identity, Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("tenant_id", "matter_number"),)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)
    matter_number: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    client: Mapped[str] = mapped_column(String(200), default="")
    jurisdiction: Mapped[str] = mapped_column(String(200), default="")
    case_type: Mapped[str] = mapped_column(String(100), default="civil")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Member(Identity, Scoped, Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("case_id", "user_id"),)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30))


class Custodian(Identity, Scoped, Base):
    __tablename__ = "custodians"
    display_name: Mapped[str] = mapped_column(String(200))
    organization: Mapped[str] = mapped_column(String(200), default="")


class Source(Identity, Scoped, Base):
    __tablename__ = "sources"
    custodian_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("custodians.id"), nullable=True)
    label: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(100), default="file-upload")
    operator_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))


class ImportBatch(Identity, Scoped, Base):
    __tablename__ = "import_batches"
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"))
    submitted_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    state: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    files: Mapped[list] = mapped_column(JSON, default=list)
    checkpoint: Mapped[dict] = mapped_column(JSON, default=dict)
    parser_version: Mapped[str] = mapped_column(String(100), default="extract-v1")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    __table_args__ = (UniqueConstraint("case_id", "idempotency_key"),)


class UploadSession(Identity, Scoped, Base):
    __tablename__ = "upload_sessions"
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    filename: Mapped[str] = mapped_column(String(500))
    byte_size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    part_size: Mapped[int] = mapped_column(Integer, default=4 * 1024 * 1024)
    parts: Mapped[dict] = mapped_column(JSON, default=dict)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"))
    state: Mapped[str] = mapped_column(String(30), default="open")
    batch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("import_batches.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Original(Identity, Scoped, Base):
    __tablename__ = "original_objects"
    __table_args__ = (UniqueConstraint("tenant_id", "case_id", "sha256"),)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(BigInteger)
    storage_key: Mapped[str] = mapped_column(String(500))
    media_type: Mapped[str] = mapped_column(String(200), default="application/octet-stream")
    integrity_status: Mapped[str] = mapped_column(String(30), default="verified")


class Occurrence(Identity, Scoped, Base):
    __tablename__ = "source_occurrences"
    __table_args__ = (UniqueConstraint("case_id", "occurrence_key"),)
    original_id: Mapped[str] = mapped_column(String(36), ForeignKey("original_objects.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String(36), ForeignKey("import_batches.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(500))
    original_path: Mapped[str] = mapped_column(Text, default="")
    source_offset: Mapped[str] = mapped_column(String(200), default="")
    occurrence_key: Mapped[str] = mapped_column(String(64))


class Evidence(Identity, Scoped, Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_case_date_id", "case_id", "date_utc", "id"),)
    original_id: Mapped[str] = mapped_column(String(36), ForeignKey("original_objects.id"), index=True)
    occurrence_id: Mapped[str] = mapped_column(String(36), ForeignKey("source_occurrences.id"), unique=True)
    source_id: Mapped[str] = mapped_column(String(36), ForeignKey("sources.id"), index=True)
    custodian_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    parent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("evidence.id"), nullable=True, index=True
    )
    item_type: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(1000))
    filename: Mapped[str] = mapped_column(String(500))
    text: Mapped[str] = mapped_column(Text, default="")
    text_hash: Mapped[str] = mapped_column(String(64), default="")
    text_version: Mapped[int] = mapped_column(Integer, default=1)
    date_raw: Mapped[str] = mapped_column(Text, default="")
    date_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    timezone_source: Mapped[str] = mapped_column(String(50), default="missing")
    sender: Mapped[str] = mapped_column(String(320), default="", index=True)
    recipients: Mapped[str] = mapped_column(Text, default="")
    email_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    parser_state: Mapped[str] = mapped_column(String(30), default="stored", index=True)
    parser_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(30), default="unreviewed", index=True)
    privilege_status: Mapped[str] = mapped_column(String(30), default="none")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    review_version: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    body_fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)


class Artifact(Identity, Scoped, Base):
    __tablename__ = "derived_artifacts"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50), default="extracted-text")
    version: Mapped[int] = mapped_column(Integer, default=1)
    parser_version: Mapped[str] = mapped_column(String(100), default="extract-v1")
    storage_key: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64))


class Span(Identity, Scoped, Base):
    __tablename__ = "text_spans"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    artifact_id: Mapped[str] = mapped_column(String(36), ForeignKey("derived_artifacts.id"))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    text_hash: Mapped[str] = mapped_column(String(64))


class Review(Identity, Scoped, Base):
    __tablename__ = "reviews"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    changes: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str] = mapped_column(Text, default="")


class Annotation(Identity, Scoped, Base):
    __tablename__ = "annotations"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    span_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("text_spans.id"), nullable=True)
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    text: Mapped[str] = mapped_column(Text)


class SavedSearch(Identity, Scoped, Base):
    __tablename__ = "saved_searches"
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(200))
    query_spec: Mapped[dict] = mapped_column(JSON)


class ReviewSet(Identity, Scoped, Base):
    __tablename__ = "review_sets"
    name: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    query_spec: Mapped[dict] = mapped_column(JSON, default=dict)


class ReviewSetItem(Scoped, Base):
    __tablename__ = "review_set_items"
    set_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_sets.id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), primary_key=True)


class Hold(Identity, Scoped, Base):
    __tablename__ = "legal_holds"
    name: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(30), default="active")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    released_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)


class Export(Identity, Scoped, Base):
    __tablename__ = "exports"
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    format: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30), default="pending")
    evidence_ids: Mapped[list] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    reviews_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)


class Person(Identity, Scoped, Base):
    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("case_id", "email"),)
    email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    state: Mapped[str] = mapped_column(String(50), default="header-address")


class Participant(Identity, Scoped, Base):
    __tablename__ = "email_participants"
    __table_args__ = (
        UniqueConstraint("evidence_id", "person_id", "role"),
        Index("ix_participant_case_person_role", "case_id", "person_id", "role"),
    )
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    person_id: Mapped[str] = mapped_column(String(36), ForeignKey("people.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), index=True)


class Issue(Identity, Scoped, Base):
    __tablename__ = "issues"
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))


class IssueLink(Identity, Scoped, Base):
    __tablename__ = "issue_links"
    issue_id: Mapped[str] = mapped_column(String(36), ForeignKey("issues.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"))
    side: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))


class Task(Identity, Scoped, Base):
    __tablename__ = "tasks"
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(String(30), default="open")
    assigned_to: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))


class AuditHead(Base):
    __tablename__ = "audit_heads"
    scope_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    event_hash: Mapped[str] = mapped_column(String(64), default="")


class Audit(Identity, Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_scope_sequence", "tenant_id", "case_id", "sequence"),)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"))
    case_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("cases.id"), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    sequence: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[str] = mapped_column(String(100), default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), default="")
    event_hash: Mapped[str] = mapped_column(String(64))
