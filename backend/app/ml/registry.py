"""Lazy model registry: load the trained model from disk, or train it on first use."""

from __future__ import annotations

import logging
import threading
from datetime import date

from sqlalchemy.orm import Session

from ..config import settings
from . import data
from .sla_model import SlaModel, train

log = logging.getLogger(__name__)


class ModelRegistry:
    def __init__(self) -> None:
        self._sla: SlaModel | None = None
        self._lock = threading.Lock()
        self._forecast_cache: tuple[date, dict] | None = None

    @property
    def path(self):
        return settings.model_dir / "sla_model.joblib"

    def sla(self, session: Session) -> SlaModel:
        if self._sla is None:
            with self._lock:
                if self._sla is None:
                    if self.path.exists():
                        self._sla = SlaModel.load(self.path)
                    else:
                        self._sla = self.retrain(session)
        return self._sla

    def retrain(self, session: Session) -> SlaModel:
        log.info("Training SLA breach model...")
        history = data.history_frame(session)
        model = train(history, data.analyst_frame(session), data.work_type_codes(session), seed=settings.random_seed)
        model.save(self.path)
        self._sla = model
        self._forecast_cache = None
        log.info("SLA model trained: AUC=%.3f", model.metrics["roc_auc"])
        return model

    def invalidate(self) -> None:
        self._sla = None
        self._forecast_cache = None
        if self.path.exists():
            self.path.unlink()

    def cached_forecast(self, today: date) -> dict | None:
        if self._forecast_cache and self._forecast_cache[0] == today:
            return self._forecast_cache[1]
        return None

    def store_forecast(self, today: date, result: dict) -> None:
        self._forecast_cache = (today, result)


registry = ModelRegistry()
