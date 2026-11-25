"""Ticket lifecycle and server-authoritative timers."""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import PRIORITY_SLA_MULT, Ticket, TimeEntry
from ..repositories.sql import AnalystRepository, TicketRepository, TimeEntryRepository, WorkTypeRepository
from ..schemas import TicketCreate
from .risk_service import LiveContext


class TicketService:
    def __init__(self, session: Session):
        self.s = session
        self.tickets = TicketRepository(session)
        self.analysts = AnalystRepository(session)
        self.work_types = WorkTypeRepository(session)
        self.timers = TimeEntryRepository(session)

    def _get(self, ticket_id: int) -> Ticket:
        t = self.tickets.get(ticket_id)
        if t is None:
            raise HTTPException(404, "Ticket not found")
        return t

    def create(self, data: TicketCreate) -> Ticket:
        wt = self.work_types.by_code(data.work_type_code)
        if wt is None:
            raise HTTPException(422, f"Unknown work type '{data.work_type_code}'")
        ref = data.external_ref or self.tickets.next_ref()
        if self.tickets.by_ref(ref):
            raise HTTPException(409, f"Ticket {ref} already exists")
        now = utcnow()
        t = Ticket(
            external_ref=ref,
            title=data.title,
            work_type_id=wt.id,
            priority=data.priority,
            channel=data.channel,
            complexity=data.complexity,
            line_items=data.line_items,
            status="NEW",
            received_at=now,
            due_at=now + timedelta(hours=wt.sla_hours * PRIORITY_SLA_MULT[data.priority]),
            intake_queue_pressure=LiveContext(self.s, now).pressure,
        )
        return self.tickets.add(t)

    def assign(self, ticket_id: int, analyst_id: int) -> Ticket:
        t = self._get(ticket_id)
        a = self.analysts.get(analyst_id)
        if a is None or not a.active:
            raise HTTPException(422, "Analyst not found or inactive")
        if t.status == "CLOSED":
            raise HTTPException(409, "Ticket is closed")
        if t.assigned_to != analyst_id:
            running = self.timers.running_for(t.assigned_to) if t.assigned_to else None
            if running and running.ticket_id == t.id:
                running.ended_at = utcnow()
            t.intake_analyst_load = self.analysts.open_loads().get(analyst_id, 0)
        t.assigned_to = analyst_id
        t.assigned_at = utcnow()
        if t.status == "NEW":
            t.status = "ASSIGNED"
        self.s.flush()
        return t

    def set_status(self, ticket_id: int, status: str) -> Ticket:
        t = self._get(ticket_id)
        if t.status == "CLOSED":
            raise HTTPException(409, "Ticket is already closed")
        if status in ("IN_PROGRESS", "CLOSED") and t.assigned_to is None:
            raise HTTPException(409, "Assign the ticket before working on it")
        now = utcnow()
        if status in ("ON_HOLD", "CLOSED"):
            for e in self.timers.for_ticket(t.id):
                if e.ended_at is None:
                    e.ended_at = now
        t.status = status
        if status == "CLOSED":
            t.closed_at = now
        self.s.flush()
        return t


class TimerService:
    """One running timer per analyst, enforced in code *and* by a partial unique index."""

    def __init__(self, session: Session):
        self.s = session
        self.timers = TimeEntryRepository(session)
        self.tickets = TicketRepository(session)

    def start(self, analyst_id: int, ticket_id: int) -> TimeEntry:
        t = self.tickets.get(ticket_id)
        if t is None:
            raise HTTPException(404, "Ticket not found")
        if t.assigned_to != analyst_id:
            raise HTTPException(409, "Ticket is not assigned to this analyst")
        if t.status == "CLOSED":
            raise HTTPException(409, "Ticket is closed")
        now = utcnow()
        current = self.timers.running_for(analyst_id)
        if current is not None:
            if current.ticket_id == ticket_id:
                return current
            current.ended_at = now  # switching tasks stops the previous timer
            self.s.flush()
        t.status = "IN_PROGRESS"
        try:
            return self.timers.add(TimeEntry(ticket_id=ticket_id, analyst_id=analyst_id, started_at=now))
        except IntegrityError as exc:  # concurrent start from another tab/device lost the race
            raise HTTPException(409, "Another timer was started for this analyst; refresh and retry") from exc

    def stop(self, timer_id: int) -> TimeEntry:
        e = self.timers.get(timer_id)
        if e is None:
            raise HTTPException(404, "Timer not found")
        if e.ended_at is None:
            e.ended_at = utcnow()
            self.s.flush()
        return e

    def reconcile(self, max_hours: float | None = None) -> int:
        """Force-close timers left running (e.g. someone went home). Returns count closed."""
        max_hours = max_hours or settings.stale_timer_hours
        now = utcnow()
        stale = self.timers.stale(now - timedelta(hours=max_hours))
        for e in stale:
            e.ended_at = e.started_at + timedelta(hours=max_hours)
            e.auto_closed = True
        self.s.flush()
        return len(stale)
