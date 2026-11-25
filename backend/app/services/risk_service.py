"""Online SLA-risk scoring, what-if analysis and assignment planning for the live queue."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..ml import data
from ..ml.balancer import plan_assignments, rank_candidates
from ..ml.features import build_features, expected_handle_min, now_series
from ..ml.registry import registry
from ..ml.sla_model import SlaModel

BANDS = [(0.6, "high"), (0.3, "medium"), (0.0, "low")]


def band(p: float, overdue: bool = False) -> str:
    if overdue:
        return "breached"
    return next(name for cut, name in BANDS if p >= cut)


class LiveContext:
    """Snapshot of the live operation used to build inference features."""

    def __init__(self, session: Session, now: datetime | None = None):
        self.now = now or utcnow()
        self.open = data.ticket_frame(session, only_open=True)
        self.analysts = data.analyst_frame(session)
        self.active = (
            self.analysts[self.analysts["active"]].reset_index(drop=True) if not self.analysts.empty else self.analysts
        )
        self.loads = (
            self.open.dropna(subset=["assigned_to"]).groupby("assigned_to").size().to_dict()
            if not self.open.empty
            else {}
        )
        self.skills = dict(zip(self.analysts["id"], self.analysts["skills"])) if not self.analysts.empty else {}
        self.pressure = self._queue_pressure()

    def _queue_pressure(self) -> float:
        if self.open.empty or self.active.empty:
            return 0.0
        work = expected_handle_min(self.open["target_aht_min"], self.open["complexity"], self.open["line_items"]).sum()
        capacity = self.active["daily_capacity_min"].sum() * (1 - settings.shrinkage)
        # backlog beyond one day of capacity, in days (matches the simulator's definition)
        return float(max(0.0, work / max(capacity, 1.0) - 1.0))


def _frame_for(rows: pd.DataFrame, analyst_ids: np.ndarray, ctx: LiveContext, model: SlaModel) -> pd.DataFrame:
    f = rows.copy()
    f["queue_pressure"] = ctx.pressure
    f["analyst_load"] = [
        ctx.loads.get(int(a), 0) - (1 if own == a else 0) for a, own in zip(analyst_ids, f["assigned_to"].fillna(-1))
    ]
    f["skill_match"] = [
        1.0 if c in ctx.skills.get(int(a), []) else 0.0 for a, c in zip(analyst_ids, f["work_type_code"])
    ]
    f["analyst_aht_ratio"] = [model.analyst_speed.get(int(a), 1.0) for a in analyst_ids]
    return build_features(f, now_series(f.index, ctx.now), model.work_type_codes)


def what_if_matrix(rows: pd.DataFrame, ctx: LiveContext, model: SlaModel) -> np.ndarray:
    """Predicted risk for every (ticket, active analyst) pair -> shape (n_tickets, n_analysts)."""
    n_t, ids = len(rows), ctx.active["id"].to_numpy()
    if n_t == 0 or len(ids) == 0:
        return np.zeros((n_t, len(ids)))
    rep = rows.loc[rows.index.repeat(len(ids))].reset_index(drop=True)
    X = _frame_for(rep, np.tile(ids, n_t), ctx, model)
    return model.predict_proba(X).reshape(n_t, len(ids))


def score_open(session: Session, ctx: LiveContext | None = None) -> pd.DataFrame:
    """Open tickets with `sla_risk`, `risk_band` and `risk_basis` columns."""
    ctx = ctx or LiveContext(session)
    df = ctx.open.copy()
    if df.empty:
        return df
    model = registry.sla(session)
    df["sla_risk"] = np.nan
    df["risk_basis"] = ""
    overdue = (df["due_at"] <= pd.Timestamp(ctx.now)).to_numpy()

    assigned = df["assigned_to"].notna().to_numpy() & ~overdue
    if assigned.any():
        rows = df[assigned]
        X = _frame_for(rows, rows["assigned_to"].astype(int).to_numpy(), ctx, model)
        df.loc[assigned, "sla_risk"] = model.predict_proba(X)
        df.loc[assigned, "risk_basis"] = "current assignee"

    unassigned = df["assigned_to"].isna().to_numpy() & ~overdue
    if unassigned.any():
        m = what_if_matrix(df[unassigned], ctx, model)
        df.loc[unassigned, "sla_risk"] = m.min(axis=1)
        df.loc[unassigned, "risk_basis"] = "best available analyst"

    df.loc[overdue, "sla_risk"] = 1.0
    df.loc[overdue, "risk_basis"] = "past due"
    df["risk_band"] = [band(p, o) for p, o in zip(df["sla_risk"], overdue)]
    return df


def ticket_insight(session: Session, ticket_id: int) -> tuple[list[dict], list[dict]]:
    """(SHAP drivers, top-3 analyst recommendations) for one open ticket."""
    ctx = LiveContext(session)
    rows = ctx.open[ctx.open["id"] == ticket_id]
    if rows.empty:
        return [], []
    model = registry.sla(session)
    row = rows.iloc[[0]]
    drivers: list[dict] = []
    if pd.notna(row["assigned_to"].iloc[0]):
        X = _frame_for(row, row["assigned_to"].astype(int).to_numpy(), ctx, model)
    else:
        m = what_if_matrix(row, ctx, model)
        best = ctx.active["id"].to_numpy()[int(np.argmin(m[0]))] if m.size else None
        X = _frame_for(row.assign(assigned_to=np.nan), np.array([best]), ctx, model) if best is not None else None
    if X is not None and (row["due_at"].iloc[0] > pd.Timestamp(ctx.now)):
        drivers = model.explain(X)[0]

    m = what_if_matrix(row, ctx, model)
    if m.size == 0:
        return drivers, []
    cand = ctx.active[["id", "name", "team"]].rename(columns={"id": "analyst_id"}).copy()
    cand["risk"] = m[0]
    own = row["assigned_to"].iloc[0]
    cand["load"] = [ctx.loads.get(int(a), 0) - (1 if own == a else 0) for a in cand["analyst_id"]]
    code = row["work_type_code"].iloc[0]
    cand["skill_match"] = [code in ctx.skills.get(int(a), []) for a in cand["analyst_id"]]
    cand["aht_ratio"] = [model.analyst_speed.get(int(a), 1.0) for a in cand["analyst_id"]]
    return drivers, rank_candidates(cand)


def auto_balance_plan(session: Session, max_open: int = 8) -> list[dict]:
    ctx = LiveContext(session)
    pool = ctx.open[ctx.open["assigned_to"].isna() & (ctx.open["status"] == "NEW")].reset_index(drop=True)
    if pool.empty or ctx.active.empty:
        return []
    model = registry.sla(session)
    risk = what_if_matrix(pool, ctx, model)
    ids = ctx.active["id"].to_numpy()
    loads = np.array([ctx.loads.get(int(a), 0) for a in ids])
    skill = np.array([[1.0 if c in ctx.skills.get(int(a), []) else 0.0 for a in ids] for c in pool["work_type_code"]])
    pairs = plan_assignments(risk, loads, skill, max_open_per_analyst=max_open)
    names = dict(zip(ctx.active["id"], ctx.active["name"]))
    return [
        {
            "ticket_id": int(pool.loc[t, "id"]),
            "external_ref": pool.loc[t, "external_ref"],
            "analyst_id": int(ids[a]),
            "analyst_name": names[ids[a]],
            "predicted_risk": round(float(risk[t, a]), 4),
        }
        for t, a in sorted(pairs)
    ]
