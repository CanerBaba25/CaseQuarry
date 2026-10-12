"""Immutable derived disclosure artifacts, approval records and Bates registry."""

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Identity, Scoped


class Redaction(Identity, Scoped, Base):
    __tablename__ = "redactions"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), index=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    reason: Mapped[str] = mapped_column(Text)
    selection: Mapped[dict] = mapped_column(JSON)
    snapshot: Mapped[dict] = mapped_column(JSON)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Production(Identity, Scoped, Base):
    __tablename__ = "productions"
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    state: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    reason: Mapped[str] = mapped_column(Text)
    approval_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    bates_prefix: Mapped[str] = mapped_column(String(16))
    evidence_ids: Mapped[list] = mapped_column(JSON)
    redactions: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON)
    counts: Mapped[dict] = mapped_column(JSON, default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BatesCounter(Identity, Scoped, Base):
    __tablename__ = "bates_counters"
    __table_args__ = (UniqueConstraint("tenant_id", "case_id", "prefix"),)
    prefix: Mapped[str] = mapped_column(String(16))
    next_number: Mapped[int] = mapped_column(BigInteger, default=1)


class ProductionItem(Identity, Scoped, Base):
    __tablename__ = "production_items"
    __table_args__ = (UniqueConstraint("production_id", "evidence_id"), UniqueConstraint("case_id", "prefix", "start_number"))
    production_id: Mapped[str] = mapped_column(String(36), ForeignKey("productions.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"))
    prefix: Mapped[str] = mapped_column(String(16))
    start_number: Mapped[int] = mapped_column(BigInteger)
    end_number: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    produced_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)


class IssueReview(Identity, Scoped, Base):
    __tablename__ = "issue_reviews"
    issue_id: Mapped[str] = mapped_column(String(36), ForeignKey("issues.id"), unique=True)
    state: Mapped[str] = mapped_column(String(30), default="needs_review")
    version: Mapped[int] = mapped_column(Integer, default=0)
    reviewed_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(Text)
    evidence_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
