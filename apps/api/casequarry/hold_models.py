"""Manually recorded custodian notices, separate from preservation enforcement."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Identity, Scoped, now


class HoldNotice(Identity, Scoped, Base):
    __tablename__ = "hold_notices"
    __table_args__ = (
        UniqueConstraint("hold_id", "custodian_id", name="uq_hold_notice_custodian"),
        Index("ix_hold_notices_scope_page", "tenant_id", "case_id", "hold_id", "id"),
    )

    hold_id: Mapped[str] = mapped_column(String(36), ForeignKey("legal_holds.id"), index=True)
    custodian_id: Mapped[str] = mapped_column(String(36), ForeignKey("custodians.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(20), default="draft")
    notice_text: Mapped[str] = mapped_column(Text)
    notice_text_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    issued_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledgement_name: Mapped[str] = mapped_column(String(200), default="")
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reminded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    last_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_reminder_date: Mapped[date | None] = mapped_column(Date, nullable=True)
