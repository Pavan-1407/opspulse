"""Pull ticket data from the database into pandas frames for analytics and ML."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Analyst, Ticket, TimeEntry, WorkType


def ticket_frame(session: Session, only_open: bool = False) -> pd.DataFrame:
    stmt = select(
        Ticket.id,
        Ticket.external_ref,
        Ticket.title,
        Ticket.priority,
        Ticket.channel,
        Ticket.complexity,
        Ticket.line_items,
        Ticket.status,
        Ticket.received_at,
        Ticket.due_at,
        Ticket.assigned_to,
        Ticket.closed_at,
        Ticket.intake_queue_pressure,
        Ticket.intake_analyst_load,
        WorkType.code.label("work_type_code"),
        WorkType.target_aht_min,
        WorkType.id.label("work_type_id"),
    ).join(WorkType, Ticket.work_type_id == WorkType.id)
    if only_open:
        stmt = stmt.where(Ticket.status != "CLOSED")
    df = pd.DataFrame(session.execute(stmt).mappings().all())
    if df.empty:
        return df
    for c in ("received_at", "due_at", "closed_at"):
        df[c] = pd.to_datetime(df[c])
    df["sla_hours"] = (df["due_at"] - df["received_at"]).dt.total_seconds() / 3600
    return df


def handle_minutes(session: Session) -> pd.Series:
    """Total logged minutes per ticket (closed timers only)."""
    rows = session.execute(
        select(TimeEntry.ticket_id, TimeEntry.started_at, TimeEntry.ended_at).where(TimeEntry.ended_at.is_not(None))
    ).all()
    if not rows:
        return pd.Series(dtype=float, name="handle_min")
    te = pd.DataFrame(rows, columns=["ticket_id", "started_at", "ended_at"])
    te["m"] = (pd.to_datetime(te["ended_at"]) - pd.to_datetime(te["started_at"])).dt.total_seconds() / 60
    return te.groupby("ticket_id")["m"].sum().rename("handle_min")


def history_frame(session: Session) -> pd.DataFrame:
    df = ticket_frame(session)
    if df.empty:
        return df
    df = df[df["status"] == "CLOSED"].copy()
    df = df.join(handle_minutes(session), on="id")
    df["breached"] = (df["closed_at"] > df["due_at"]).astype(int)
    return df


def analyst_frame(session: Session) -> pd.DataFrame:
    rows = session.execute(select(Analyst)).scalars().all()
    return pd.DataFrame(
        [
            {
                "id": a.id,
                "name": a.name,
                "team": a.team,
                "skills": a.skills,
                "daily_capacity_min": a.daily_capacity_min,
                "active": a.active,
            }
            for a in rows
        ]
    )


def work_type_codes(session: Session) -> list[str]:
    return [c for (c,) in session.execute(select(WorkType.code).order_by(WorkType.id)).all()]
