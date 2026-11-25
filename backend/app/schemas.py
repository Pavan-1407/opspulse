from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer


def _iso_utc(d: datetime | None) -> str | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.isoformat().replace("+00:00", "Z")


UTC = Annotated[datetime, PlainSerializer(_iso_utc, return_type=str | None)]

Priority = Literal["P1", "P2", "P3", "P4"]
Channel = Literal["email", "portal", "batch"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class WorkTypeOut(ORM):
    id: int
    code: str
    name: str
    sla_hours: float
    target_aht_min: float


class AnalystOut(ORM):
    id: int
    name: str
    email: str
    team: str
    skills: list[str]
    daily_capacity_min: float
    active: bool
    open_tickets: int = 0


class Driver(BaseModel):
    feature: str
    label: str
    value: float
    impact: float


class TicketOut(ORM):
    id: int
    external_ref: str
    title: str
    priority: str
    channel: str
    complexity: int
    line_items: int
    status: str
    received_at: UTC
    due_at: UTC
    assigned_at: UTC | None = None
    closed_at: UTC | None = None
    work_type: WorkTypeOut
    assigned_to: int | None = None
    analyst_name: str | None = None
    sla_risk: float | None = None
    risk_band: str | None = None
    risk_basis: str | None = None


class TicketCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    work_type_code: str
    priority: Priority = "P3"
    channel: Channel = "portal"
    complexity: int = Field(1, ge=1, le=3)
    line_items: int = Field(1, ge=1, le=500)
    external_ref: str | None = None


class AssignIn(BaseModel):
    analyst_id: int


class StatusIn(BaseModel):
    status: Literal["ASSIGNED", "IN_PROGRESS", "ON_HOLD", "CLOSED"]


class TimerStart(BaseModel):
    analyst_id: int
    ticket_id: int


class TimerOut(ORM):
    id: int
    ticket_id: int
    analyst_id: int
    started_at: UTC
    ended_at: UTC | None = None
    auto_closed: bool
    minutes: float | None = None
    ticket_ref: str | None = None
    ticket_title: str | None = None


class Recommendation(BaseModel):
    analyst_id: int
    name: str
    team: str
    predicted_risk: float
    load: int
    skill_match: bool
    score: float
    reasons: list[str]


class TicketDetail(BaseModel):
    ticket: TicketOut
    drivers: list[Driver]
    recommendations: list[Recommendation]
    time_entries: list[TimerOut]
    logged_minutes: float


class PlanItem(BaseModel):
    ticket_id: int
    external_ref: str
    analyst_id: int
    analyst_name: str
    predicted_risk: float


class IngestReport(BaseModel):
    inserted: int
    updated: int
    rejected: int
    errors: list[dict]
