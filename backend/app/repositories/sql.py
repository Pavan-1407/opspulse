from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select

from ..models import OPEN_STATUSES, Analyst, Ticket, TimeEntry, WorkType
from .base import SqlRepository


class WorkTypeRepository(SqlRepository[WorkType]):
    model = WorkType

    def by_code(self, code: str) -> WorkType | None:
        return self.session.execute(select(WorkType).where(WorkType.code == code)).scalar_one_or_none()


class AnalystRepository(SqlRepository[Analyst]):
    model = Analyst

    def active(self) -> Sequence[Analyst]:
        return self.session.execute(select(Analyst).where(Analyst.active).order_by(Analyst.name)).scalars().all()

    def open_loads(self) -> dict[int, int]:
        rows = self.session.execute(
            select(Ticket.assigned_to, func.count())
            .where(Ticket.status.in_(OPEN_STATUSES), Ticket.assigned_to.is_not(None))
            .group_by(Ticket.assigned_to)
        ).all()
        return {int(a): int(n) for a, n in rows}


class TicketRepository(SqlRepository[Ticket]):
    model = Ticket

    def by_ref(self, ref: str) -> Ticket | None:
        return self.session.execute(select(Ticket).where(Ticket.external_ref == ref)).unique().scalar_one_or_none()

    def open(self, assigned_to: int | None = None) -> Sequence[Ticket]:
        stmt = select(Ticket).where(Ticket.status.in_(OPEN_STATUSES))
        if assigned_to is not None:
            stmt = stmt.where(Ticket.assigned_to == assigned_to)
        return self.session.execute(stmt.order_by(Ticket.due_at)).unique().scalars().all()

    def next_ref(self) -> str:
        n = self.session.execute(select(func.max(Ticket.id))).scalar() or 0
        return f"OPS-{n + 1:06d}"


class TimeEntryRepository(SqlRepository[TimeEntry]):
    model = TimeEntry

    def running_for(self, analyst_id: int) -> TimeEntry | None:
        return (
            self.session.execute(
                select(TimeEntry).where(TimeEntry.analyst_id == analyst_id, TimeEntry.ended_at.is_(None))
            )
            .unique()
            .scalar_one_or_none()
        )

    def running(self) -> Sequence[TimeEntry]:
        return self.session.execute(select(TimeEntry).where(TimeEntry.ended_at.is_(None))).unique().scalars().all()

    def stale(self, older_than: datetime) -> Sequence[TimeEntry]:
        return (
            self.session.execute(
                select(TimeEntry).where(TimeEntry.ended_at.is_(None), TimeEntry.started_at < older_than)
            )
            .unique()
            .scalars()
            .all()
        )

    def for_ticket(self, ticket_id: int) -> Sequence[TimeEntry]:
        return (
            self.session.execute(
                select(TimeEntry).where(TimeEntry.ticket_id == ticket_id).order_by(TimeEntry.started_at)
            )
            .unique()
            .scalars()
            .all()
        )
