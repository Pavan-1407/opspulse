"""Operational KPIs and capacity forecast."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..ml import data
from ..ml.forecast import forecast_and_capacity
from ..ml.registry import registry
from ..models import TimeEntry
from .risk_service import LiveContext, score_open


def _logged_minutes(session: Session, since) -> pd.DataFrame:
    rows = session.execute(
        select(TimeEntry.analyst_id, TimeEntry.ticket_id, TimeEntry.started_at, TimeEntry.ended_at).where(
            TimeEntry.started_at >= since
        )
    ).all()
    df = pd.DataFrame(rows, columns=["analyst_id", "ticket_id", "started_at", "ended_at"])
    if df.empty:
        return df.assign(minutes=[])
    now = pd.Timestamp(utcnow())
    df["ended_at"] = pd.to_datetime(df["ended_at"]).fillna(now)
    df["minutes"] = (df["ended_at"] - pd.to_datetime(df["started_at"])).dt.total_seconds() / 60
    return df


def overview(session: Session) -> dict:
    now = utcnow()
    ctx = LiveContext(session, now)
    scored = score_open(session, ctx)
    hist = data.history_frame(session)
    t_now = pd.Timestamp(now)

    def attainment(frame: pd.DataFrame) -> float | None:
        return None if frame.empty else float(1 - frame["breached"].mean())

    last30 = hist[hist["closed_at"] >= t_now - pd.Timedelta(days=30)]
    prev30 = hist[
        (hist["closed_at"] < t_now - pd.Timedelta(days=30)) & (hist["closed_at"] >= t_now - pd.Timedelta(days=60))
    ]
    running = session.execute(select(TimeEntry).where(TimeEntry.ended_at.is_(None))).unique().scalars().all()

    # ---- daily flow (last 60 days) --------------------------------------------------
    all_t = data.ticket_frame(session)
    start = (t_now - pd.Timedelta(days=60)).normalize()
    idx = pd.date_range(start, t_now.normalize(), freq="D")
    rec = all_t[all_t["received_at"] >= start].groupby(all_t["received_at"].dt.normalize()).size()
    clo = hist[hist["closed_at"] >= start].groupby(hist["closed_at"].dt.normalize())
    flow = pd.DataFrame(
        {
            "received": rec.reindex(idx, fill_value=0),
            "closed": clo.size().reindex(idx, fill_value=0),
            "attainment": (1 - clo["breached"].mean()).reindex(idx),
        }
    )

    # ---- by work type (last 30 days) ------------------------------------------------
    by_type = []
    for code, g in last30.groupby("work_type_code"):
        by_type.append(
            {
                "work_type": code,
                "closed": int(len(g)),
                "attainment": float(1 - g["breached"].mean()),
                "median_aht_min": float(g["handle_min"].median()) if g["handle_min"].notna().any() else None,
                "target_aht_min": float(g["target_aht_min"].iloc[0]),
                "open": int((scored["work_type_code"] == code).sum()) if not scored.empty else 0,
            }
        )

    # ---- analysts (last 7 days) ------------------------------------------------------
    logged = _logged_minutes(session, now - timedelta(days=7))
    workdays = max(1, int(np.busday_count((now - timedelta(days=7)).date(), now.date())))
    per = logged.groupby("analyst_id")["minutes"].sum() if not logged.empty else pd.Series(dtype=float)
    analysts = []
    for a in ctx.active.itertuples():
        mine = scored[scored["assigned_to"] == a.id] if not scored.empty else scored
        analysts.append(
            {
                "analyst_id": int(a.id),
                "name": a.name,
                "team": a.team,
                "open": int(len(mine)),
                "high_risk": int((mine["risk_band"].isin(["high", "breached"])).sum()) if not mine.empty else 0,
                "utilization_7d": round(float(per.get(a.id, 0.0) / (a.daily_capacity_min * workdays)), 3),
            }
        )

    return {
        "as_of": now.isoformat() + "Z",
        "kpis": {
            "open_backlog": int(len(scored)),
            "unassigned": int(scored["assigned_to"].isna().sum()) if not scored.empty else 0,
            "high_risk": int((scored["risk_band"] == "high").sum()) if not scored.empty else 0,
            "past_due": int((scored["risk_band"] == "breached").sum()) if not scored.empty else 0,
            "active_timers": len(running),
            "sla_attainment_30d": attainment(last30),
            "sla_attainment_prev_30d": attainment(prev30),
            "closed_30d": int(len(last30)),
            "median_aht_30d": float(last30["handle_min"].median()) if not last30.empty else None,
            "queue_pressure": round(ctx.pressure, 3),
        },
        "flow": [
            {
                "date": d.date().isoformat(),
                "received": int(r.received),
                "closed": int(r.closed),
                "attainment": None if pd.isna(r.attainment) else round(float(r.attainment), 3),
            }
            for d, r in flow.iterrows()
        ],
        "by_work_type": sorted(by_type, key=lambda x: x["attainment"]),
        "analysts": sorted(analysts, key=lambda x: -x["open"]),
    }


def capacity_forecast(session: Session) -> dict:
    today = utcnow().date()
    cached = registry.cached_forecast(today)
    if cached is not None:
        return cached
    tickets = data.ticket_frame(session)
    hist = data.history_frame(session)
    recent = hist[hist["closed_at"] >= pd.Timestamp(today) - pd.Timedelta(days=90)]
    aht = recent.groupby("work_type_code")["handle_min"].median().dropna().to_dict()
    analysts = data.analyst_frame(session)
    result = forecast_and_capacity(
        tickets, aht, int(analysts["active"].sum()), settings.productive_minutes, settings.shrinkage, today
    )
    registry.store_forecast(today, result)
    return result
