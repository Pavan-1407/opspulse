"""ORM models.

Design notes
------------
* Timers are server-authoritative: the database stores `started_at`; clients only render
  `now - started_at`. That is what lets dozens of analysts run live timers concurrently
  without the UI framework holding state (the failure mode of a Streamlit-only prototype).
* A partial unique index guarantees at most one running timer per analyst.
* `intake_*` columns are feature snapshots captured when the ticket arrived, so training
  data never leaks information from the future.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

TICKET_STATUSES = ("NEW", "ASSIGNED", "IN_PROGRESS", "ON_HOLD", "CLOSED")
OPEN_STATUSES = ("NEW", "ASSIGNED", "IN_PROGRESS", "ON_HOLD")
PRIORITIES = ("P1", "P2", "P3", "P4")
CHANNELS = ("email", "portal", "batch")
# SLA window multiplier by priority (P1 = half the work type's standard SLA)
PRIORITY_SLA_MULT = {"P1": 0.5, "P2": 0.75, "P3": 1.0, "P4": 1.5}


class WorkType(Base):
    __tablename__ = "work_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    sla_hours: Mapped[float] = mapped_column(Float)
    target_aht_min: Mapped[float] = mapped_column(Float)


class Analyst(Base):
    __tablename__ = "analysts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(120), unique=True)
    team: Mapped[str] = mapped_column(String(40))
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    daily_capacity_min: Mapped[float] = mapped_column(Float, default=384)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    work_type_id: Mapped[int] = mapped_column(ForeignKey("work_types.id"), index=True)
    priority: Mapped[str] = mapped_column(String(4), default="P3")
    channel: Mapped[str] = mapped_column(String(16), default="portal")
    complexity: Mapped[int] = mapped_column(Integer, default=1)
    line_items: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="NEW", index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    assigned_to: Mapped[int | None] = mapped_column(ForeignKey("analysts.id"), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    intake_queue_pressure: Mapped[float | None] = mapped_column(Float, nullable=True)
    intake_analyst_load: Mapped[int | None] = mapped_column(Integer, nullable=True)

    work_type: Mapped[WorkType] = relationship(lazy="joined")
    analyst: Mapped[Analyst | None] = relationship(lazy="joined")


class TimeEntry(Base):
    __tablename__ = "time_entries"
    __table_args__ = (
        Index(
            "uq_one_running_timer_per_analyst",
            "analyst_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
            sqlite_where=text("ended_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    analyst_id: Mapped[int] = mapped_column(ForeignKey("analysts.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    auto_closed: Mapped[bool] = mapped_column(Boolean, default=False)

    ticket: Mapped[Ticket] = relationship(lazy="joined")

    @property
    def minutes(self) -> float | None:
        if self.ended_at is None:
            return None
        return (self.ended_at - self.started_at).total_seconds() / 60
