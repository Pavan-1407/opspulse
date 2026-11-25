"""Create tables and load the synthetic demo dataset.

python -m app.seed            # seed if empty
python -m app.seed --reset    # drop everything and reseed
"""

from __future__ import annotations

import argparse
import logging
from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import func, insert, select, text
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine, utcnow
from .ml.registry import registry
from .ml.synthetic import generate
from .models import Analyst, Ticket, TimeEntry, WorkType

log = logging.getLogger(__name__)


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.astype(object).where(df.notna(), None).to_dict("records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, pd.Timestamp):
                r[k] = v.to_pydatetime()
            elif isinstance(v, np.generic):
                r[k] = v.item()
    return out


def is_empty(session: Session) -> bool:
    return (session.execute(select(func.count()).select_from(Ticket)).scalar() or 0) == 0


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
        registry.invalidate()
    Base.metadata.create_all(engine)
    with SessionLocal() as s:
        if not is_empty(s):
            log.info("Database already seeded")
            return
        now = utcnow()
        log.info("Generating synthetic operations history (%s days)...", settings.history_days)
        d = generate(now, history_days=settings.history_days, seed=settings.random_seed)
        s.execute(insert(WorkType), _records(d.work_types))
        s.execute(insert(Analyst), _records(d.analysts))
        tickets = d.tickets.drop(columns=["_handle_min"])
        recs = _records(tickets)
        for i in range(0, len(recs), 5000):
            s.execute(insert(Ticket), recs[i : i + 5000])
        entries = _records(d.time_entries)
        for i in range(0, len(entries), 5000):
            s.execute(insert(TimeEntry), entries[i : i + 5000])

        # A handful of analysts are mid-task right now so the live board isn't empty.
        rng = np.random.default_rng(settings.random_seed)
        open_assigned = tickets[(tickets["status"] == "ASSIGNED")].drop_duplicates("assigned_to")
        for r in open_assigned.head(6).itertuples():
            s.execute(
                insert(TimeEntry),
                [
                    {
                        "ticket_id": int(r.id),
                        "analyst_id": int(r.assigned_to),
                        "started_at": now - timedelta(minutes=float(rng.uniform(4, 55))),
                        "ended_at": None,
                        "auto_closed": False,
                    }
                ],
            )
            s.get(Ticket, int(r.id)).status = "IN_PROGRESS"
        if engine.dialect.name == "postgresql":
            # explicit ids were inserted, so move the identity sequences past them
            for table in ("work_types", "analysts", "tickets", "time_entries"):
                s.execute(
                    text(
                        f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), (SELECT COALESCE(MAX(id), 1) FROM {table}))"
                    )
                )
        s.commit()
        log.info("Seeded %d tickets, %d analysts", len(tickets), len(d.analysts))
        registry.invalidate()
        registry.retrain(s)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    seed(reset=p.parse_args().reset)
