"""Inflow forecasting and capacity planning.

1. Forecast daily ticket inflow per work type with Holt-Winters (additive weekly seasonality,
   damped trend). Per-type forecasts are summed so mix shifts flow into workload.
2. Back-test on the last 28 days against a seasonal-naive baseline (same weekday last week).
3. Convert forecast volume to workload minutes with each type's historical median AHT, then
   to required FTE = minutes / productive minutes per FTE, versus available FTE after shrinkage.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

HORIZON = 28
BACKTEST = 28


def daily_counts(tickets: pd.DataFrame, end: date) -> pd.DataFrame:
    """Rows = calendar days up to and including `end` (yesterday), columns = work type codes."""
    t = tickets[tickets["received_at"].dt.date <= end]
    counts = t.groupby([t["received_at"].dt.normalize(), "work_type_code"]).size().unstack(fill_value=0)
    idx = pd.date_range(counts.index.min(), pd.Timestamp(end), freq="D")
    return counts.reindex(idx, fill_value=0)


def _fit_forecast(y: pd.Series, horizon: int) -> tuple[np.ndarray, float]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = ExponentialSmoothing(
            y.astype(float),
            trend="add",
            damped_trend=True,
            seasonal="add",
            seasonal_periods=7,
            initialization_method="estimated",
        ).fit(optimized=True)
    fc = np.clip(model.forecast(horizon).to_numpy(), 0, None)
    resid_sd = float(np.std(y.to_numpy() - model.fittedvalues.to_numpy()))
    return fc, resid_sd


def wape(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.abs(actual - pred).sum() / max(actual.sum(), 1e-9))


def forecast_and_capacity(
    tickets: pd.DataFrame,
    aht_by_type: dict[str, float],
    headcount: int,
    productive_minutes: float,
    shrinkage: float,
    today: date,
) -> dict:
    end = today - timedelta(days=1)
    counts = daily_counts(tickets, end)
    types = list(counts.columns)

    # ---- back-test --------------------------------------------------------------------
    train, test = counts.iloc[:-BACKTEST], counts.iloc[-BACKTEST:]
    hw_bt = np.zeros(BACKTEST)
    for c in types:
        hw_bt += _fit_forecast(train[c], BACKTEST)[0]
    naive_bt = np.tile(train.sum(axis=1).iloc[-7:].to_numpy(), BACKTEST // 7 + 1)[:BACKTEST]
    actual_bt = test.sum(axis=1).to_numpy()

    # ---- forward forecast --------------------------------------------------------------
    total = np.zeros(HORIZON)
    var = np.zeros(HORIZON)
    workload = np.zeros(HORIZON)
    by_type = {}
    for c in types:
        fc, sd = _fit_forecast(counts[c], HORIZON)
        by_type[c] = fc
        total += fc
        var += (sd**2) * (1 + np.arange(HORIZON) / 14)  # widen with horizon
        workload += fc * aht_by_type.get(c, np.nan if not aht_by_type else np.median(list(aht_by_type.values())))
    sd_total = np.sqrt(var)
    dates = pd.date_range(pd.Timestamp(today), periods=HORIZON, freq="D")

    available_fte = headcount * (1 - shrinkage)
    weekday = np.asarray(dates.dayofweek < 5)
    # No weekend staffing: weekend workload lands on the next working day.
    staffed_workload = workload.copy()
    carry = 0.0
    for i in range(HORIZON):
        if not weekday[i]:
            carry += staffed_workload[i]
            staffed_workload[i] = 0.0
        elif carry:
            staffed_workload[i] += carry
            carry = 0.0
    required_fte = staffed_workload / productive_minutes

    history_tail = counts.sum(axis=1).iloc[-90:]
    return {
        "history": [{"date": d.date().isoformat(), "actual": int(v)} for d, v in history_tail.items()],
        "forecast": [
            {
                "date": d.date().isoformat(),
                "forecast": round(float(total[i]), 1),
                "lower": round(float(max(total[i] - 1.64 * sd_total[i], 0)), 1),
                "upper": round(float(total[i] + 1.64 * sd_total[i]), 1),
                "workload_min": round(float(workload[i]), 0),
                "required_fte": round(float(required_fte[i]), 2),
                "available_fte": round(float(available_fte if weekday[i] else 0), 2),
            }
            for i, d in enumerate(dates)
        ],
        "by_type_next_7d": {c: round(float(v[:7].sum()), 1) for c, v in by_type.items()},
        "backtest": {
            "days": BACKTEST,
            "holt_winters_wape": wape(actual_bt, hw_bt),
            "seasonal_naive_wape": wape(actual_bt, naive_bt),
            "series": [
                {
                    "date": d.date().isoformat(),
                    "actual": int(a),
                    "holt_winters": round(float(h), 1),
                    "seasonal_naive": round(float(n), 1),
                }
                for d, a, h, n in zip(test.index, actual_bt, hw_bt, naive_bt)
            ],
        },
        "capacity": {
            "headcount": headcount,
            "available_fte": round(available_fte, 2),
            "productive_minutes_per_fte": productive_minutes,
            "peak_required_fte": round(float(required_fte[weekday].max()), 2) if weekday.any() else 0.0,
            "avg_weekday_required_fte": round(float(required_fte[weekday].mean()), 2) if weekday.any() else 0.0,
            "days_over_capacity": int(((required_fte > available_fte) & weekday).sum()),
            "aht_by_type": {k: round(v, 1) for k, v in aht_by_type.items()},
        },
    }
