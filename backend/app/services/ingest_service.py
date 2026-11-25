"""Bulk ticket upload from CSV / Excel with row-level validation."""

from __future__ import annotations

import io
from datetime import timedelta

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import CHANNELS, PRIORITIES, PRIORITY_SLA_MULT, Ticket
from ..repositories.sql import TicketRepository, WorkTypeRepository
from .risk_service import LiveContext

REQUIRED = ["external_ref", "title", "work_type", "priority"]
OPTIONAL = {"received_at": None, "channel": "portal", "complexity": 1, "line_items": 1}
MAX_ROWS = 5000


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    name = filename.lower()
    try:
        if name.endswith(".csv"):
            return pd.read_csv(io.BytesIO(content))
        if name.endswith((".xlsx", ".xls")):
            return pd.read_excel(io.BytesIO(content))
    except Exception as exc:  # malformed file
        raise HTTPException(400, f"Could not read file: {exc}") from exc
    raise HTTPException(415, "Upload a .csv or .xlsx file")


def ingest(session: Session, df: pd.DataFrame) -> dict:
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise HTTPException(422, f"Missing required columns: {', '.join(missing)}")
    if len(df) > MAX_ROWS:
        raise HTTPException(413, f"Max {MAX_ROWS} rows per upload")
    for c, default in OPTIONAL.items():
        if c not in df.columns:
            df[c] = default

    tickets, wts = TicketRepository(session), WorkTypeRepository(session)
    wt_cache = {w.code: w for w in wts.list()}
    now = utcnow()
    pressure = LiveContext(session, now).pressure
    inserted = updated = 0
    errors: list[dict] = []
    seen: set[str] = set()

    for i, r in df.iterrows():
        row_no = int(i) + 2  # header is row 1
        try:
            ref = str(r["external_ref"]).strip()
            if not ref or ref == "nan":
                raise ValueError("external_ref is empty")
            if ref in seen:
                raise ValueError(f"duplicate external_ref '{ref}' in file")
            seen.add(ref)
            code = str(r["work_type"]).strip().upper()
            wt = wt_cache.get(code)
            if wt is None:
                raise ValueError(f"unknown work_type '{code}'")
            prio = str(r["priority"]).strip().upper()
            if prio not in PRIORITIES:
                raise ValueError(f"priority must be one of {PRIORITIES}")
            channel = str(r["channel"]).strip().lower()
            if channel not in CHANNELS:
                raise ValueError(f"channel must be one of {CHANNELS}")
            complexity = int(r["complexity"])
            if complexity not in (1, 2, 3):
                raise ValueError("complexity must be 1, 2 or 3")
            line_items = max(1, int(r["line_items"]))
            received = (
                now
                if pd.isna(r["received_at"])
                else pd.to_datetime(r["received_at"], utc=True).tz_localize(None).to_pydatetime()
            )
            if received > now + timedelta(minutes=5):
                raise ValueError("received_at is in the future")
            title = str(r["title"]).strip()[:200]
        except (ValueError, TypeError) as exc:
            errors.append({"row": row_no, "error": str(exc)})
            continue

        due = received + timedelta(hours=wt.sla_hours * PRIORITY_SLA_MULT[prio])
        existing = tickets.by_ref(ref)
        if existing is not None:
            if existing.status == "CLOSED":
                errors.append({"row": row_no, "error": f"{ref} is closed and cannot be updated"})
                continue
            existing.title, existing.work_type_id, existing.priority = title, wt.id, prio
            existing.channel, existing.complexity, existing.line_items = channel, complexity, line_items
            existing.received_at, existing.due_at = received, due
            updated += 1
        else:
            session.add(
                Ticket(
                    external_ref=ref,
                    title=title,
                    work_type_id=wt.id,
                    priority=prio,
                    channel=channel,
                    complexity=complexity,
                    line_items=line_items,
                    status="NEW",
                    received_at=received,
                    due_at=due,
                    intake_queue_pressure=pressure,
                )
            )
            inserted += 1
    session.flush()
    return {"inserted": inserted, "updated": updated, "rejected": len(errors), "errors": errors[:100]}
