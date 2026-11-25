"""SLA breach risk model: XGBoost classifier with native TreeSHAP explanations.

* Time-based split (train on the oldest 80% of tickets, test on the newest 20%) so the
  evaluation mimics production: predicting the future from the past.
* Logistic regression baseline to prove the tree model earns its complexity.
* Explanations use XGBoost's built-in `pred_contribs` (exact TreeSHAP), no extra dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .features import analyst_speed_table, build_features, readable, sample_snapshots

XGB_PARAMS = dict(
    n_estimators=400,
    max_depth=4,
    learning_rate=0.05,
    subsample=0.85,
    colsample_bytree=0.85,
    min_child_weight=5,
    reg_lambda=1.0,
    eval_metric="logloss",
    n_jobs=2,
)


# Business-sensible shape constraints: risk can only go up with these (+1) or down (-1).
MONOTONE = {
    "queue_pressure": 1, "analyst_load": 1, "analyst_aht_ratio": 1, "frac_sla_used": 1,
    "elapsed_h": 1, "expected_handle_min": 1, "complexity": 1, "line_items": 1,
    "hours_to_due": -1, "skill_match": -1,
}


def _make_clf(features: list[str], seed: int) -> xgb.XGBClassifier:
    constraints = "(" + ",".join(str(MONOTONE.get(f, 0)) for f in features) + ")"
    return xgb.XGBClassifier(**XGB_PARAMS, monotone_constraints=constraints, random_state=seed)


@dataclass
class SlaModel:
    clf: xgb.XGBClassifier
    feature_names: list[str]
    work_type_codes: list[str]
    analyst_speed: dict[int, float]
    metrics: dict = field(default_factory=dict)

    # ---------------------------------------------------------------- inference
    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if X.empty:
            return np.array([])
        return self.clf.predict_proba(X[self.feature_names])[:, 1]

    def explain(self, X: pd.DataFrame, top_k: int = 5) -> list[list[dict]]:
        """Top SHAP drivers (log-odds contributions) per row."""
        if X.empty:
            return []
        contrib = self.clf.get_booster().predict(
            xgb.DMatrix(X[self.feature_names], feature_names=self.feature_names), pred_contribs=True
        )[:, :-1]  # last column is the bias term
        out = []
        for i in range(len(X)):
            order = np.argsort(-np.abs(contrib[i]))[:top_k]
            out.append(
                [
                    {
                        "feature": self.feature_names[j],
                        "label": readable(self.feature_names[j]),
                        "value": float(X.iloc[i][self.feature_names[j]]),
                        "impact": float(contrib[i, j]),
                    }
                    for j in order
                ]
            )
        return out

    # ---------------------------------------------------------------- persistence
    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> SlaModel:
        return joblib.load(path)


def _training_frame(history: pd.DataFrame, analysts: pd.DataFrame, speed: dict[int, float]) -> pd.DataFrame:
    skills = dict(zip(analysts["id"], analysts["skills"]))
    df = history.copy()
    df["queue_pressure"] = df["intake_queue_pressure"].fillna(0.0)
    df["analyst_load"] = df["intake_analyst_load"].fillna(0).astype(float)
    df["skill_match"] = [
        1.0 if (a == a and a is not None and code in skills.get(int(a), [])) else 0.0
        for a, code in zip(df["assigned_to"], df["work_type_code"])
    ]
    df["analyst_aht_ratio"] = df["assigned_to"].map(lambda a: speed.get(int(a), 1.0) if a == a else 1.0)
    return df


def _precision_at(y: np.ndarray, p: np.ndarray, frac: float) -> tuple[float, float]:
    k = max(1, int(len(p) * frac))
    idx = np.argsort(-p)[:k]
    tp = y[idx].sum()
    return float(tp / k), float(tp / max(y.sum(), 1))


def _calibration(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (p >= lo) & (p < hi if hi < 1 else p <= hi)
        if m.sum() >= 20:
            out.append(
                {
                    "bin": f"{lo:.1f}-{hi:.1f}",
                    "predicted": float(p[m].mean()),
                    "observed": float(y[m].mean()),
                    "n": int(m.sum()),
                }
            )
    return out


def _auc_by_stage(y: np.ndarray, p: np.ndarray, frac: np.ndarray) -> list[dict]:
    """Discrimination at different points in the ticket's life: early predictions are harder."""
    out = []
    for lo, hi, name in [(0, 0.25, "0-25%"), (0.25, 0.5, "25-50%"), (0.5, 0.75, "50-75%"), (0.75, 1.01, "75-100%")]:
        m = (frac >= lo) & (frac < hi)
        if m.sum() >= 50 and 0 < y[m].mean() < 1:
            out.append(
                {
                    "stage": name,
                    "n": int(m.sum()),
                    "breach_rate": float(y[m].mean()),
                    "roc_auc": float(roc_auc_score(y[m], p[m])),
                }
            )
    return out


def train(history: pd.DataFrame, analysts: pd.DataFrame, work_type_codes: list[str], seed: int = 42) -> SlaModel:
    history = history.sort_values("received_at").reset_index(drop=True)
    rng = np.random.default_rng(seed)
    cutoff = history["received_at"].quantile(0.8)
    is_train = (history["received_at"] < cutoff).to_numpy()

    # analyst speed is estimated on the training window only (no test leakage)
    speed_train = analyst_speed_table(history[is_train])
    frame = _training_frame(history, analysts, speed_train)
    snaps = sample_snapshots(frame, rng)
    X = build_features(frame, snaps, work_type_codes)
    y = frame["breached"].to_numpy()
    feats = list(X.columns)

    Xtr, Xte, ytr, yte = X[is_train], X[~is_train], y[is_train], y[~is_train]

    clf = _make_clf(feats, seed)
    clf.fit(Xtr, ytr)
    p = clf.predict_proba(Xte)[:, 1]

    base = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))
    base.fit(Xtr, ytr)
    pb = base.predict_proba(Xte)[:, 1]

    prec10, rec10 = _precision_at(yte, p, 0.10)
    contrib = clf.get_booster().predict(xgb.DMatrix(Xte, feature_names=feats), pred_contribs=True)[:, :-1]
    importance = sorted(
        (
            {"feature": f, "label": readable(f), "mean_abs_shap": float(v)}
            for f, v in zip(feats, np.abs(contrib).mean(axis=0))
        ),
        key=lambda d: -d["mean_abs_shap"],
    )[:12]

    metrics = {
        "model": "XGBoost (gradient-boosted trees, monotonic constraints)",
        "n_train": int(is_train.sum()),
        "n_test": int((~is_train).sum()),
        "train_period": [str(history["received_at"].min().date()), str(cutoff.date())],
        "test_period": [str(cutoff.date()), str(history["received_at"].max().date())],
        "base_rate_test": float(yte.mean()),
        "roc_auc": float(roc_auc_score(yte, p)),
        "pr_auc": float(average_precision_score(yte, p)),
        "brier": float(brier_score_loss(yte, p)),
        "precision_at_top10pct": prec10,
        "recall_at_top10pct": rec10,
        "baseline": {
            "model": "Logistic regression",
            "roc_auc": float(roc_auc_score(yte, pb)),
            "pr_auc": float(average_precision_score(yte, pb)),
            "brier": float(brier_score_loss(yte, pb)),
        },
        "auc_by_sla_stage": _auc_by_stage(yte, p, Xte["frac_sla_used"].to_numpy()),
        "calibration": _calibration(yte, p),
        "feature_importance": importance,
    }

    # Refit on all history for serving; speed table from all history too.
    speed_all = analyst_speed_table(history)
    frame_all = _training_frame(history, analysts, speed_all)
    X_all = build_features(frame_all, snaps, work_type_codes)
    final = _make_clf(feats, seed)
    final.fit(X_all, y)
    return SlaModel(final, feats, work_type_codes, speed_all, metrics)
