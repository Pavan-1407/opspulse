"""Feature engineering shared by training and online inference (one code path = no skew).

SLA-risk is framed as a *landmark* problem: "given the ticket is still open at time t, how
likely is it to finish after its due date?" Training rows are snapshots taken at a random
point in each historical ticket's open interval; inference rows are snapshots taken *now*.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

PRIORITY_NUM = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}
CHANNELS = ["email", "portal", "batch"]

NUMERIC_FEATURES = [
    "priority_num",
    "complexity",
    "line_items",
    "sla_hours",
    "elapsed_h",
    "hours_to_due",
    "frac_sla_used",
    "queue_pressure",
    "analyst_load",
    "skill_match",
    "analyst_aht_ratio",
    "received_dow",
    "received_hour",
    "expected_handle_min",
]

READABLE = {
    "priority_num": "Priority level",
    "complexity": "Complexity",
    "line_items": "Line items",
    "sla_hours": "SLA window",
    "elapsed_h": "Time already open",
    "hours_to_due": "Hours left to due",
    "frac_sla_used": "Share of SLA used",
    "queue_pressure": "Team backlog pressure",
    "analyst_load": "Assignee open load",
    "skill_match": "Assignee skill match",
    "analyst_aht_ratio": "Assignee speed vs target",
    "received_dow": "Day received",
    "received_hour": "Hour received",
    "expected_handle_min": "Expected handling effort",
}


def expected_handle_min(target_aht: pd.Series, complexity: pd.Series, line_items: pd.Series) -> pd.Series:
    return target_aht * (0.7 + 0.3 * complexity) + 2.5 * line_items


def build_features(
    df: pd.DataFrame,
    snapshot_at: pd.Series,
    work_type_codes: list[str],
) -> pd.DataFrame:
    """`df` needs: priority, complexity, line_items, channel, work_type_code, sla_hours
    (effective, priority-adjusted), target_aht_min, received_at, due_at, queue_pressure,
    analyst_load, skill_match, analyst_aht_ratio."""
    X = pd.DataFrame(index=df.index)
    X["priority_num"] = df["priority"].map(PRIORITY_NUM).astype(float)
    X["complexity"] = df["complexity"].astype(float)
    X["line_items"] = df["line_items"].astype(float)
    X["sla_hours"] = df["sla_hours"].astype(float)
    elapsed = (snapshot_at - df["received_at"]).dt.total_seconds() / 3600
    X["elapsed_h"] = elapsed.clip(lower=0)
    X["hours_to_due"] = (df["due_at"] - snapshot_at).dt.total_seconds() / 3600
    X["frac_sla_used"] = (X["elapsed_h"] / X["sla_hours"]).clip(0, 3)
    X["queue_pressure"] = df["queue_pressure"].astype(float)
    X["analyst_load"] = df["analyst_load"].astype(float)
    X["skill_match"] = df["skill_match"].astype(float)
    X["analyst_aht_ratio"] = df["analyst_aht_ratio"].astype(float)
    X["received_dow"] = df["received_at"].dt.dayofweek.astype(float)
    X["received_hour"] = df["received_at"].dt.hour.astype(float)
    X["expected_handle_min"] = expected_handle_min(
        df["target_aht_min"].astype(float), df["complexity"].astype(float), df["line_items"].astype(float)
    )
    for code in work_type_codes:
        X[f"wt_{code}"] = (df["work_type_code"] == code).astype(float)
    for ch in CHANNELS:
        X[f"ch_{ch}"] = (df["channel"] == ch).astype(float)
    return X


def readable(feature: str) -> str:
    if feature.startswith("wt_"):
        return f"Work type = {feature[3:]}"
    if feature.startswith("ch_"):
        return f"Channel = {feature[3:]}"
    return READABLE.get(feature, feature)


def analyst_speed_table(history: pd.DataFrame) -> dict[int, float]:
    """Analyst handle time relative to work-type target (median ratio), from closed work."""
    h = history.dropna(subset=["assigned_to", "handle_min"])
    if h.empty:
        return {}
    exp = expected_handle_min(h["target_aht_min"], h["complexity"], h["line_items"])
    ratio = (h["handle_min"] / exp).groupby(h["assigned_to"].astype(int)).median()
    return {int(k): float(np.clip(v, 0.5, 2.5)) for k, v in ratio.items()}


def sample_snapshots(closed: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    """Random landmark time within each ticket's open interval (and before its due date)."""
    turnaround = (closed["closed_at"] - closed["received_at"]).dt.total_seconds()
    to_due = (closed["due_at"] - closed["received_at"]).dt.total_seconds()
    upper = np.minimum(turnaround, to_due) * 0.97
    offs = rng.uniform(0, 1, len(closed)) * upper.clip(lower=60)
    return closed["received_at"] + pd.to_timedelta(offs, unit="s")


def now_series(index: pd.Index, now: datetime) -> pd.Series:
    return pd.Series(pd.Timestamp(now), index=index)
