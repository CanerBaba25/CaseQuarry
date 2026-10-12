"""Versioned local-model jobs and suggestions, separate from human evidence decisions."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Identity, Scoped


class AIJob(Identity, Scoped, Base):
    __tablename__ = "ai_jobs"
    __table_args__ = (Index("ix_ai_jobs_scope_state", "tenant_id", "case_id", "state"),)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    task: Mapped[str] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(30), default="pending")
    question: Mapped[str] = mapped_column(Text)
    style: Mapped[str] = mapped_column(String(30), default="brief")
    provider: Mapped[str] = mapped_column(String(30), default="local-ollama")
    provider_endpoint: Mapped[str] = mapped_column(String(300))
    model: Mapped[str] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(100), default="extractive-quotes-v1")
    policy_revision: Mapped[int] = mapped_column(Integer)
    evidence_ids: Mapped[list] = mapped_column(JSON)
    scope: Mapped[dict] = mapped_column(JSON, default=dict)
    coverage: Mapped[dict] = mapped_column(JSON, default=dict)
    source_refs: Mapped[list] = mapped_column(JSON, default=list)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AIResult(Identity, Scoped, Base):
    __tablename__ = "ai_results"
    __table_args__ = (UniqueConstraint("job_id", "finding_index"),)
    job_id: Mapped[str] = mapped_column(String(36), ForeignKey("ai_jobs.id"), index=True)
    finding_index: Mapped[int] = mapped_column(Integer)
    claim: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSON)
    review_state: Mapped[str] = mapped_column(String(30), default="pending")
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
