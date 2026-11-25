"""Workload balancing.

Two entry points:

* `rank_candidates` - for one ticket, score every active analyst by the *predicted SLA risk if
  assigned to them* (what-if inference with the SLA model) plus a load-fairness penalty, and
  return the top candidates with reasons.
* `plan_assignments` - for a batch of unassigned tickets, solve a min-cost assignment
  (Hungarian algorithm, scipy `linear_sum_assignment`). Each analyst is expanded into as many
  "slots" as their spare capacity allows, so the plan respects capacity while minimising total
  breach risk and spreading work fairly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

LOAD_WEIGHT = 0.025  # risk-equivalent penalty per open ticket already held
SKILL_MISS_PENALTY = 0.15  # discourage mis-routing beyond what the model already prices in


def candidate_cost(risk: np.ndarray, load: np.ndarray, skill: np.ndarray) -> np.ndarray:
    return risk + LOAD_WEIGHT * load + SKILL_MISS_PENALTY * (1 - skill)


def rank_candidates(
    risk_by_analyst: pd.DataFrame,
    top_k: int = 3,
) -> list[dict]:
    """`risk_by_analyst` columns: analyst_id, name, team, risk, load, skill_match, aht_ratio."""
    df = risk_by_analyst.copy()
    df["score"] = candidate_cost(df["risk"].to_numpy(), df["load"].to_numpy(), df["skill_match"].to_numpy())
    df = df.sort_values("score").head(top_k)
    out = []
    for r in df.itertuples():
        reasons = []
        reasons.append("Skilled in this work type" if r.skill_match else "Not skilled in this work type")
        reasons.append(f"{int(r.load)} open tickets")
        if r.aht_ratio < 0.95:
            reasons.append(f"Works {round((1 - r.aht_ratio) * 100)}% faster than standard")
        elif r.aht_ratio > 1.05:
            reasons.append(f"Works {round((r.aht_ratio - 1) * 100)}% slower than standard")
        out.append(
            {
                "analyst_id": int(r.analyst_id),
                "name": r.name,
                "team": r.team,
                "predicted_risk": round(float(r.risk), 4),
                "load": int(r.load),
                "skill_match": bool(r.skill_match),
                "score": round(float(r.score), 4),
                "reasons": reasons,
            }
        )
    return out


def plan_assignments(
    risk_matrix: np.ndarray,  # tickets x analysts predicted risk
    loads: np.ndarray,  # analysts current open tickets
    skill: np.ndarray,  # tickets x analysts 0/1
    max_open_per_analyst: int = 8,
) -> list[tuple[int, int]]:
    """Return (ticket_idx, analyst_idx) pairs."""
    n_t, n_a = risk_matrix.shape
    slots = np.clip(max_open_per_analyst - loads, 0, None).astype(int)
    if n_t == 0 or slots.sum() == 0:
        return []
    cols, col_cost = [], []
    for a in range(n_a):
        for s in range(slots[a]):
            cols.append(a)
            # the k-th extra ticket for the same analyst costs more (load grows as we assign)
            col_cost.append(candidate_cost(risk_matrix[:, a], np.full(n_t, loads[a] + s), skill[:, a]))
    cost = np.column_stack(col_cost)
    rows, cidx = linear_sum_assignment(cost)
    return [(int(r), int(cols[c])) for r, c in zip(rows, cidx)]
