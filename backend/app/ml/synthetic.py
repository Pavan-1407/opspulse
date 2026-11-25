"""Synthetic back-office operations simulator.

Generates a realistic, fully synthetic ticket history for a team of operations analysts.
No real company data is used. The simulator encodes plausible causal dynamics so that the
ML models have genuine signal to learn:

* Inflow: per-work-type Poisson volume with weekly seasonality, month-end spikes, an upward
  trend over the year and quiet weekends (no weekend staffing -> Monday backlog).
* Capacity: analysts x productive minutes, minus random leave.
* Backlog: carried-over work (minutes). Queue pressure = backlog / daily capacity.
* Routing: ~80% of tickets go to a skilled, lightly loaded analyst; ~20% are mis-routed.
* Turnaround = queue wait (pressure, analyst load, priority) + handling (AHT x complexity x
  analyst speed x skill penalty) + noise; weekends are skipped.
* SLA breach = turnaround > SLA hours for the work type and priority.

Anything still unfinished at `now` becomes the live open queue.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..models import PRIORITY_SLA_MULT

WORK_TYPES = [
    # code, name, sla_hours, target_aht_min, share of volume
    ("ACC_SETUP", "Account Setup", 96, 95, 0.14),
    ("CFG_CHANGE", "Configuration Change", 72, 60, 0.20),
    ("DATA_FIX", "Data Correction", 48, 35, 0.18),
    ("RECON", "Reconciliation", 96, 120, 0.09),
    ("ACCESS_REQ", "Access Request", 48, 20, 0.15),
    ("RENEWAL", "Annual Renewal", 144, 140, 0.07),
    ("ESCALATION", "Escalation", 48, 75, 0.08),
    ("AUDIT_REQ", "Audit Request", 120, 110, 0.09),
]

PRIORITY_P = {"P1": 0.06, "P2": 0.22, "P3": 0.52, "P4": 0.20}
PRIORITY_WAIT_MULT = {"P1": 0.25, "P2": 0.6, "P3": 1.0, "P4": 1.3}
CHANNEL_P = {"portal": 0.55, "email": 0.30, "batch": 0.15}

FIRST = [
    "Aarav",
    "Maya",
    "Liam",
    "Sofia",
    "Kenji",
    "Amara",
    "Noah",
    "Priya",
    "Lucas",
    "Zara",
    "Mateo",
    "Ines",
    "Ravi",
    "Chloe",
    "Omar",
    "Hana",
    "Ethan",
    "Leila",
    "Diego",
    "Anika",
    "Felix",
    "Nadia",
    "Arjun",
    "Elena",
    "Tomas",
    "Yara",
]
LAST = [
    "Shah",
    "Chen",
    "Okafor",
    "Rossi",
    "Tanaka",
    "Mensah",
    "Novak",
    "Iyer",
    "Silva",
    "Haddad",
    "Kowalski",
    "Moreau",
    "Reddy",
    "Larsen",
    "Farouk",
    "Kim",
    "Walsh",
    "Nasser",
    "Ortega",
    "Gupta",
    "Berg",
    "Petrova",
    "Menon",
    "Costa",
    "Varga",
    "Aziz",
]
TEAMS = ["Atlas", "Borealis", "Cascade"]

TITLE_TEMPLATES = {
    "ACC_SETUP": ["New client account setup", "Onboard subsidiary account", "Create account hierarchy"],
    "CFG_CHANGE": ["Update rule configuration", "Change pricing parameters", "Modify plan settings"],
    "DATA_FIX": ["Correct member attributes", "Fix duplicate records", "Repair effective dates"],
    "RECON": ["Monthly balance reconciliation", "Reconcile vendor feed", "Resolve ledger mismatch"],
    "ACCESS_REQ": ["Grant system access", "Role change request", "Revoke leaver access"],
    "RENEWAL": ["Annual contract renewal", "Renewal configuration load", "Renewal rate review"],
    "ESCALATION": ["Client escalation", "Executive complaint follow-up", "Urgent service failure"],
    "AUDIT_REQ": ["Internal audit sample", "Compliance evidence pull", "External audit request"],
}


@dataclass
class SyntheticData:
    work_types: pd.DataFrame
    analysts: pd.DataFrame
    tickets: pd.DataFrame
    time_entries: pd.DataFrame


def _skip_weekends(start: datetime, hours: float) -> datetime:
    """Add `hours` of elapsed queue/working time, pausing over Saturdays and Sundays."""
    t = start
    remaining = hours
    while remaining > 0:
        if t.weekday() >= 5:  # jump to Monday 08:00
            t = (t + timedelta(days=7 - t.weekday())).replace(hour=8, minute=0, second=0, microsecond=0)
            continue
        end_of_day = (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        step = min(remaining, (end_of_day - t).total_seconds() / 3600)
        t += timedelta(hours=step)
        remaining -= step
    return t


def generate(now: datetime, history_days: int = 365, n_analysts: int = 24, seed: int = 42) -> SyntheticData:
    rng = np.random.default_rng(seed)

    # ---- dimensions -------------------------------------------------------------------
    wt = pd.DataFrame(WORK_TYPES, columns=["code", "name", "sla_hours", "target_aht_min", "share"])
    wt["id"] = np.arange(1, len(wt) + 1)
    codes = wt["code"].tolist()

    names = set()
    analysts = []
    while len(analysts) < n_analysts:
        n = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        if n in names:
            continue
        names.add(n)
        k = int(rng.integers(3, 6))
        skills = sorted(rng.choice(codes, size=k, replace=False).tolist())
        analysts.append(
            {
                "id": len(analysts) + 1,
                "name": n,
                "email": n.lower().replace(" ", ".") + "@opspulse.demo",
                "team": TEAMS[len(analysts) % len(TEAMS)],
                "skills": skills,
                "daily_capacity_min": 384.0,
                "active": True,
                "speed": float(np.exp(rng.normal(0, 0.15))),  # hidden: <1 faster, >1 slower
            }
        )
    an = pd.DataFrame(analysts)
    skill_sets = {r.id: set(r.skills) for r in an.itertuples()}
    speed = dict(zip(an.id, an.speed))

    wt_rows = {r.code: r for r in wt.itertuples()}
    shares = wt["share"].to_numpy()
    base_daily = 58.0  # average weekday tickets at the start of the period

    start_day = (now - timedelta(days=history_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    n_days = (now.replace(hour=0, minute=0, second=0, microsecond=0) - start_day).days + 1

    backlog_min = 0.0
    analyst_heaps: dict[int, list[datetime]] = {a: [] for a in an.id}  # closing times of open work
    rows, entries = [], []
    tid = 0

    for d in range(n_days):
        day = start_day + timedelta(days=d)
        dow = day.weekday()
        progress = d / max(n_days - 1, 1)
        trend = 1.0 + 0.17 * progress
        weekly = [1.15, 1.05, 1.0, 0.97, 0.9, 0.12, 0.06][dow]
        month_end = 1.35 if day.day >= 26 or day.day <= 2 else 1.0
        lam_total = base_daily * trend * weekly * month_end

        # capacity today
        on_shift = rng.random(len(an)) > 0.08
        capacity = 0.0 if dow >= 5 else float(an.loc[on_shift, "daily_capacity_min"].sum())

        n_today = int(rng.poisson(lam_total))
        hours = np.sort(np.clip(rng.normal(12.5, 3.0, n_today), 6.0, 21.5))
        today_work = 0.0
        daily_assign_count = {a: 0 for a in an.id}

        for h in hours:
            received = day + timedelta(hours=float(h))
            if received > now:
                break
            code = codes[int(rng.choice(len(codes), p=shares))]
            w = wt_rows[code]
            prio = rng.choice(list(PRIORITY_P), p=list(PRIORITY_P.values()))
            channel = rng.choice(list(CHANNEL_P), p=list(CHANNEL_P.values()))
            complexity = int(rng.choice([1, 2, 3], p=[0.55, 0.32, 0.13]))
            line_items = int(max(1, rng.poisson(2 + 3 * (complexity - 1))))

            # routing: prefer skilled + lightly loaded analysts; some mis-routing
            for a in an.id:  # pop finished work
                hp = analyst_heaps[a]
                while hp and hp[0] <= received:
                    heapq.heappop(hp)
            skilled = [a for a in an.id if code in skill_sets[a] and on_shift[a - 1]]
            if skilled and rng.random() < 0.8:
                loads = np.array([len(analyst_heaps[a]) + 0.5 * daily_assign_count[a] for a in skilled])
                pick = skilled[int(np.argmin(loads + rng.random(len(loads)) * 2))]
            else:
                pick = int(rng.choice(an.id))
            daily_assign_count[pick] += 1
            load = len(analyst_heaps[pick])
            skill_match = code in skill_sets[pick]

            handle = float(w.target_aht_min) * (0.7 + 0.3 * complexity) * speed[pick]
            handle *= 1.0 if skill_match else 1.45
            handle *= float(np.exp(rng.normal(0, 0.35)))
            handle += 2.5 * line_items

            day_capacity_ref = max(capacity, 1.0) if capacity > 0 else float(an.daily_capacity_min.sum() * 0.92)
            pressure = backlog_min / day_capacity_ref
            wait_h = (9.0 + pressure * 16.0 + load * 2.0) * PRIORITY_WAIT_MULT[prio]
            wait_h *= float(np.exp(rng.normal(0, 0.45)))  # unobserved queue variability
            wait_h += float(rng.exponential(3.0))
            if rng.random() < 0.15:  # awaiting client / third-party info
                wait_h += float(rng.exponential(30.0))
            work_h = handle / 60 * 2.2  # context switching / fragmentation
            turnaround_h = wait_h + work_h

            closed = _skip_weekends(received, turnaround_h)
            due = received + timedelta(hours=float(w.sla_hours) * PRIORITY_SLA_MULT[prio])
            heapq.heappush(analyst_heaps[pick], closed)
            today_work += handle

            tid += 1
            title = f"{rng.choice(TITLE_TEMPLATES[code])} #{tid:05d}"
            is_open = closed > now
            rows.append(
                {
                    "id": tid,
                    "external_ref": f"OPS-{tid:06d}",
                    "title": title,
                    "work_type_id": int(w.id),
                    "priority": prio,
                    "channel": channel,
                    "complexity": complexity,
                    "line_items": line_items,
                    "received_at": received,
                    "due_at": due,
                    "assigned_to": pick,
                    "assigned_at": received + timedelta(minutes=float(rng.uniform(5, 90))),
                    "closed_at": None if is_open else closed,
                    "status": "CLOSED" if not is_open else "ASSIGNED",
                    "intake_queue_pressure": round(pressure, 4),
                    "intake_analyst_load": load,
                    "_handle_min": handle,
                }
            )
            if not is_open:
                entries.append(
                    {
                        "ticket_id": tid,
                        "analyst_id": pick,
                        "started_at": closed - timedelta(minutes=handle),
                        "ended_at": closed,
                        "auto_closed": False,
                    }
                )

        backlog_min = max(0.0, backlog_min + today_work - capacity)

    tickets = pd.DataFrame(rows)

    # Freshest open tickets haven't been triaged yet -> unassigned "NEW" queue.
    open_mask = tickets["closed_at"].isna()
    open_idx = tickets.index[open_mask]
    newest = tickets.loc[open_idx].sort_values("received_at").tail(30).index
    tickets.loc[newest, ["assigned_to", "assigned_at"]] = None
    tickets.loc[newest, "status"] = "NEW"
    tickets.loc[newest, "intake_analyst_load"] = None
    # A few open tickets are on hold awaiting client info.
    rest = tickets.loc[open_idx.difference(newest)]
    hold = rest.sample(frac=0.08, random_state=seed).index
    tickets.loc[hold, "status"] = "ON_HOLD"

    tickets["assigned_to"] = tickets["assigned_to"].astype("Int64")
    tickets["intake_analyst_load"] = tickets["intake_analyst_load"].astype("Int64")

    return SyntheticData(
        work_types=wt.drop(columns=["share"]),
        analysts=an.drop(columns=["speed"]),
        tickets=tickets,
        time_entries=pd.DataFrame(entries),
    )
