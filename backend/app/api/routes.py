from __future__ import annotations

from typing import Literal

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..ml import data
from ..ml.registry import registry
from ..models import Ticket, WorkType
from ..repositories.sql import AnalystRepository, TicketRepository, TimeEntryRepository, WorkTypeRepository
from ..schemas import (
    AnalystOut,
    AssignIn,
    IngestReport,
    PlanItem,
    StatusIn,
    TicketCreate,
    TicketDetail,
    TicketOut,
    TimerOut,
    TimerStart,
    WorkTypeOut,
)
from ..services import analytics_service, ingest_service, risk_service
from ..services.ops_service import TicketService, TimerService

router = APIRouter(prefix="/api")
DB = Depends(get_session)


# --------------------------------------------------------------------------- helpers
def _wt_map(s: Session) -> dict[int, WorkTypeOut]:
    return {w.id: WorkTypeOut.model_validate(w) for w in WorkTypeRepository(s).list()}


def _analyst_names(s: Session) -> dict[int, str]:
    return {a.id: a.name for a in AnalystRepository(s).list()}


def _rows_to_out(df: pd.DataFrame, s: Session) -> list[TicketOut]:
    wts, names = _wt_map(s), _analyst_names(s)
    out = []
    for r in df.itertuples():
        a = None if pd.isna(r.assigned_to) else int(r.assigned_to)
        out.append(
            TicketOut(
                id=int(r.id),
                external_ref=r.external_ref,
                title=r.title,
                priority=r.priority,
                channel=r.channel,
                complexity=int(r.complexity),
                line_items=int(r.line_items),
                status=r.status,
                received_at=r.received_at.to_pydatetime(),
                due_at=r.due_at.to_pydatetime(),
                closed_at=None if pd.isna(r.closed_at) else r.closed_at.to_pydatetime(),
                work_type=wts[int(r.work_type_id)],
                assigned_to=a,
                analyst_name=names.get(a) if a else None,
                sla_risk=None if not hasattr(r, "sla_risk") or pd.isna(r.sla_risk) else round(float(r.sla_risk), 4),
                risk_band=getattr(r, "risk_band", None),
                risk_basis=getattr(r, "risk_basis", None),
            )
        )
    return out


def _orm_to_out(t: Ticket) -> TicketOut:
    out = TicketOut.model_validate(t)
    out.analyst_name = t.analyst.name if t.analyst else None
    return out


def _timer_out(e) -> TimerOut:
    out = TimerOut.model_validate(e)
    out.ticket_ref, out.ticket_title = e.ticket.external_ref, e.ticket.title
    return out


# --------------------------------------------------------------------------- reference data
@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/work-types", response_model=list[WorkTypeOut])
def work_types(s: Session = DB):
    return s.execute(select(WorkType).order_by(WorkType.id)).scalars().all()


@router.get("/analysts", response_model=list[AnalystOut])
def analysts(s: Session = DB):
    repo = AnalystRepository(s)
    loads = repo.open_loads()
    out = []
    for a in repo.active():
        o = AnalystOut.model_validate(a)
        o.open_tickets = loads.get(a.id, 0)
        out.append(o)
    return out


# --------------------------------------------------------------------------- tickets
@router.get("/tickets", response_model=list[TicketOut])
def list_tickets(
    s: Session = DB,
    scope: Literal["open", "closed"] = "open",
    assigned_to: int | None = None,
    unassigned: bool = False,
    risk_band: str | None = None,
    work_type: str | None = None,
    limit: int = Query(500, le=2000),
):
    if scope == "open":
        df = risk_service.score_open(s)
        if df.empty:
            return []
        if assigned_to is not None:
            df = df[df["assigned_to"] == assigned_to]
        if unassigned:
            df = df[df["assigned_to"].isna()]
        if risk_band:
            df = df[df["risk_band"].isin(risk_band.split(","))]
        if work_type:
            df = df[df["work_type_code"] == work_type]
        df = df.sort_values(["sla_risk", "due_at"], ascending=[False, True])
    else:
        df = data.ticket_frame(s)
        df = df[df["status"] == "CLOSED"]
        if assigned_to is not None:
            df = df[df["assigned_to"] == assigned_to]
        if work_type:
            df = df[df["work_type_code"] == work_type]
        df = df.sort_values("closed_at", ascending=False)
    return _rows_to_out(df.head(limit), s)


@router.post("/tickets", response_model=TicketOut, status_code=201)
def create_ticket(body: TicketCreate, s: Session = DB):
    return _orm_to_out(TicketService(s).create(body))


@router.post("/tickets/upload", response_model=IngestReport)
async def upload_tickets(file: UploadFile = File(...), s: Session = DB):
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 5 MB)")
    df = ingest_service.read_table(file.filename or "", content)
    return ingest_service.ingest(s, df)


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
def ticket_detail(ticket_id: int, s: Session = DB):
    t = TicketRepository(s).get(ticket_id)
    if t is None:
        raise HTTPException(404, "Ticket not found")
    out = _orm_to_out(t)
    drivers, recs = [], []
    if t.status != "CLOSED":
        scored = risk_service.score_open(s)
        row = scored[scored["id"] == ticket_id]
        if not row.empty:
            out.sla_risk = round(float(row["sla_risk"].iloc[0]), 4)
            out.risk_band, out.risk_basis = row["risk_band"].iloc[0], row["risk_basis"].iloc[0]
        drivers, recs = risk_service.ticket_insight(s, ticket_id)
    entries = TimeEntryRepository(s).for_ticket(ticket_id)
    logged = sum((e.minutes or 0) for e in entries)
    return TicketDetail(
        ticket=out,
        drivers=drivers,
        recommendations=recs,
        time_entries=[_timer_out(e) for e in entries],
        logged_minutes=round(logged, 1),
    )


@router.post("/tickets/{ticket_id}/assign", response_model=TicketOut)
def assign(ticket_id: int, body: AssignIn, s: Session = DB):
    return _orm_to_out(TicketService(s).assign(ticket_id, body.analyst_id))


@router.post("/tickets/{ticket_id}/status", response_model=TicketOut)
def set_status(ticket_id: int, body: StatusIn, s: Session = DB):
    return _orm_to_out(TicketService(s).set_status(ticket_id, body.status))


# --------------------------------------------------------------------------- timers
@router.get("/timers/active", response_model=list[TimerOut])
def active_timers(s: Session = DB):
    return [_timer_out(e) for e in TimeEntryRepository(s).running()]


@router.post("/timers/start", response_model=TimerOut)
def start_timer(body: TimerStart, s: Session = DB):
    return _timer_out(TimerService(s).start(body.analyst_id, body.ticket_id))


@router.post("/timers/{timer_id}/stop", response_model=TimerOut)
def stop_timer(timer_id: int, s: Session = DB):
    return _timer_out(TimerService(s).stop(timer_id))


@router.post("/timers/reconcile")
def reconcile(s: Session = DB):
    return {"force_closed": TimerService(s).reconcile()}


# --------------------------------------------------------------------------- analytics & ML
@router.get("/kpis/overview")
def kpi_overview(s: Session = DB):
    return analytics_service.overview(s)


@router.get("/forecast")
def forecast(s: Session = DB):
    return analytics_service.capacity_forecast(s)


@router.get("/ml/model-card")
def model_card(s: Session = DB):
    return registry.sla(s).metrics


@router.post("/ml/retrain")
def retrain(s: Session = DB):
    return registry.retrain(s).metrics


@router.get("/ml/auto-balance", response_model=list[PlanItem])
def auto_balance_preview(s: Session = DB, max_open: int = Query(8, ge=1, le=50)):
    return risk_service.auto_balance_plan(s, max_open)


@router.post("/ml/auto-balance/apply", response_model=list[PlanItem])
def auto_balance_apply(plan: list[PlanItem], s: Session = DB):
    svc = TicketService(s)
    for p in plan:
        svc.assign(p.ticket_id, p.analyst_id)
    return plan
