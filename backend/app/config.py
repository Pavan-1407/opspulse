"""Runtime configuration, read from environment variables (12-factor style)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _normalize_db_url(url: str) -> str:
    # Render / Heroku / Neon hand out "postgres://" URLs; SQLAlchemy wants "postgresql+psycopg2://".
    if url.startswith("postgres://"):
        return "postgresql+psycopg2://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _normalize_db_url(os.getenv("DATABASE_URL", "sqlite:///./opspulse.db"))
    )
    # Seed synthetic demo data when the database is empty.
    seed_on_startup: bool = field(default_factory=lambda: os.getenv("SEED_ON_STARTUP", "true").lower() == "true")
    # Wipe and reseed on every boot (useful for a public demo so data never goes stale).
    reset_on_startup: bool = field(default_factory=lambda: os.getenv("RESET_ON_STARTUP", "false").lower() == "true")
    model_dir: Path = field(default_factory=lambda: Path(os.getenv("MODEL_DIR", "./models")))
    static_dir: Path = field(default_factory=lambda: Path(os.getenv("STATIC_DIR", "./static")))
    random_seed: int = field(default_factory=lambda: int(os.getenv("RANDOM_SEED", "42")))
    history_days: int = field(default_factory=lambda: int(os.getenv("HISTORY_DAYS", "365")))

    # Capacity-planning assumptions
    shift_minutes: int = 480
    utilization: float = 0.80  # productive share of a shift
    shrinkage: float = 0.08  # leave / training / meetings
    stale_timer_hours: float = 10.0  # timers open longer than this are force-closed
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    @property
    def productive_minutes(self) -> float:
        return self.shift_minutes * self.utilization


settings = Settings()
