export type RiskBand = "low" | "medium" | "high" | "breached";

export interface WorkType { id: number; code: string; name: string; sla_hours: number; target_aht_min: number }
export interface Analyst {
  id: number; name: string; email: string; team: string; skills: string[];
  daily_capacity_min: number; active: boolean; open_tickets: number;
}
export interface Ticket {
  id: number; external_ref: string; title: string; priority: string; channel: string;
  complexity: number; line_items: number; status: string; received_at: string; due_at: string;
  closed_at: string | null; work_type: WorkType; assigned_to: number | null; analyst_name: string | null;
  sla_risk: number | null; risk_band: RiskBand | null; risk_basis: string | null;
}
export interface Driver { feature: string; label: string; value: number; impact: number }
export interface Recommendation {
  analyst_id: number; name: string; team: string; predicted_risk: number; load: number;
  skill_match: boolean; score: number; reasons: string[];
}
export interface Timer {
  id: number; ticket_id: number; analyst_id: number; started_at: string; ended_at: string | null;
  auto_closed: boolean; minutes: number | null; ticket_ref: string | null; ticket_title: string | null;
}
export interface TicketDetail {
  ticket: Ticket; drivers: Driver[]; recommendations: Recommendation[]; time_entries: Timer[]; logged_minutes: number;
}
export interface PlanItem { ticket_id: number; external_ref: string; analyst_id: number; analyst_name: string; predicted_risk: number }

export interface Overview {
  as_of: string;
  kpis: {
    open_backlog: number; unassigned: number; high_risk: number; past_due: number; active_timers: number;
    sla_attainment_30d: number | null; sla_attainment_prev_30d: number | null; closed_30d: number;
    median_aht_30d: number | null; queue_pressure: number;
  };
  flow: { date: string; received: number; closed: number; attainment: number | null }[];
  by_work_type: { work_type: string; closed: number; attainment: number; median_aht_min: number | null; target_aht_min: number; open: number }[];
  analysts: { analyst_id: number; name: string; team: string; open: number; high_risk: number; utilization_7d: number }[];
}

export interface Forecast {
  history: { date: string; actual: number }[];
  forecast: { date: string; forecast: number; lower: number; upper: number; workload_min: number; required_fte: number; available_fte: number }[];
  by_type_next_7d: Record<string, number>;
  backtest: { days: number; holt_winters_wape: number; seasonal_naive_wape: number; series: { date: string; actual: number; holt_winters: number; seasonal_naive: number }[] };
  capacity: { headcount: number; available_fte: number; productive_minutes_per_fte: number; peak_required_fte: number; avg_weekday_required_fte: number; days_over_capacity: number; aht_by_type: Record<string, number> };
}

export interface ModelCard {
  model: string; n_train: number; n_test: number; train_period: string[]; test_period: string[];
  base_rate_test: number; roc_auc: number; pr_auc: number; brier: number;
  precision_at_top10pct: number; recall_at_top10pct: number;
  baseline: { model: string; roc_auc: number; pr_auc: number; brier: number };
  auc_by_sla_stage: { stage: string; n: number; breach_rate: number; roc_auc: number }[];
  calibration: { bin: string; predicted: number; observed: number; n: number }[];
  feature_importance: { feature: string; label: string; mean_abs_shap: number }[];
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.body instanceof FormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* not json */ }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const post = <T,>(path: string, body?: unknown) => req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  overview: () => req<Overview>("/kpis/overview"),
  forecast: () => req<Forecast>("/forecast"),
  modelCard: () => req<ModelCard>("/ml/model-card"),
  workTypes: () => req<WorkType[]>("/work-types"),
  analysts: () => req<Analyst[]>("/analysts"),
  tickets: (q: Record<string, string | number | boolean | undefined> = {}) => {
    const p = new URLSearchParams();
    Object.entries(q).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
    return req<Ticket[]>(`/tickets?${p}`);
  },
  ticket: (id: number) => req<TicketDetail>(`/tickets/${id}`),
  createTicket: (body: { title: string; work_type_code: string; priority: string; complexity: number; line_items: number; channel: string }) =>
    post<Ticket>("/tickets", body),
  assign: (id: number, analyst_id: number) => post<Ticket>(`/tickets/${id}/assign`, { analyst_id }),
  setStatus: (id: number, status: string) => post<Ticket>(`/tickets/${id}/status`, { status }),
  activeTimers: () => req<Timer[]>("/timers/active"),
  startTimer: (analyst_id: number, ticket_id: number) => post<Timer>("/timers/start", { analyst_id, ticket_id }),
  stopTimer: (id: number) => post<Timer>(`/timers/${id}/stop`),
  balancePreview: (max_open = 8) => req<PlanItem[]>(`/ml/auto-balance?max_open=${max_open}`),
  balanceApply: (plan: PlanItem[]) => post<PlanItem[]>("/ml/auto-balance/apply", plan),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ inserted: number; updated: number; rejected: number; errors: { row: number; error: string }[] }>(
      "/tickets/upload", { method: "POST", body: fd });
  },
};
