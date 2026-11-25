from datetime import datetime

import numpy as np

from app.ml.balancer import plan_assignments
from app.ml.synthetic import generate


def test_simulator_is_deterministic_and_realistic():
    now = datetime(2026, 6, 1, 10, 0)
    a = generate(now, history_days=60, seed=7)
    b = generate(now, history_days=60, seed=7)
    assert a.tickets["closed_at"].equals(b.tickets["closed_at"])
    closed = a.tickets.dropna(subset=["closed_at"])
    breach = (closed["closed_at"] > closed["due_at"]).mean()
    assert 0.05 < breach < 0.45
    assert (closed["closed_at"] > closed["received_at"]).all()
    assert a.tickets["external_ref"].is_unique


def test_hungarian_prefers_low_risk_and_respects_slots():
    risk = np.array([[0.9, 0.1], [0.2, 0.8], [0.5, 0.5]])
    skill = np.ones_like(risk)
    pairs = dict(plan_assignments(risk, loads=np.array([0, 1]), skill=skill, max_open_per_analyst=2))
    assert pairs[0] == 1 and pairs[1] == 0
    per = np.bincount(list(pairs.values()), minlength=2)
    assert per[0] <= 2 and per[1] <= 1  # analyst 1 already holds one ticket


def test_no_slots_means_no_plan():
    assert plan_assignments(np.ones((3, 2)), np.array([5, 5]), np.ones((3, 2)), max_open_per_analyst=5) == []
