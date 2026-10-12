"""Persisted review work allocations, retaining assignment history separately."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Identity, Scoped, now


class ReviewAssignment(Identity, Scoped, Base):
    __tablename__ = "review_assignments"
    title: Mapped[str] = mapped_column(String(200))
    assignee_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    review_set_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("review_sets.id"), nullable=True)
    state: Mapped[str] = mapped_column(String(30), default="unassigned")
    version: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssignmentItem(Scoped, Base):
    __tablename__ = "review_assignment_items"
    assignment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("review_assignments.id"), primary_key=True
    )
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), primary_key=True)


class ActiveAllocation(Scoped, Base):
    __tablename__ = "active_review_allocations"
    evidence_id: Mapped[str] = mapped_column(String(36), ForeignKey("evidence.id"), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(36), ForeignKey("review_assignments.id"), index=True)
