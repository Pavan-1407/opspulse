import { ReactNode, useEffect, useState } from "react";
import type { RiskBand } from "../api";

export const pct = (v: number | null | undefined, d = 0) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
export const num = (v: number | null | undefined, d = 0) => (v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: d }));
export const shortDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });

export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let live = true;
    fn().then((d) => live && (setData(d), setError(null))).catch((e) => live && setError(String(e.message ?? e)));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { data, error, reload: () => setTick((t) => t + 1) };
}

export function Card({ title, subtitle, children, actions, className = "" }:
  { title?: string; subtitle?: string; children: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            {title && <h3>{title}</h3>}
            {subtitle && <p className="muted">{subtitle}</p>}
          </div>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function Kpi({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {hint && <div className={`kpi-hint ${tone ?? ""}`}>{hint}</div>}
    </div>
  );
}

const BAND_ICON: Record<RiskBand, string> = { low: "●", medium: "▲", high: "◆", breached: "✕" };
const BAND_LABEL: Record<RiskBand, string> = { low: "Low", medium: "Medium", high: "High", breached: "Past due" };

export function RiskBadge({ band, risk }: { band: RiskBand | null; risk?: number | null }) {
  if (!band) return <span className="muted">—</span>;
  return (
    <span className={`risk risk-${band}`} title={risk != null ? `Predicted breach probability ${pct(risk, 1)}` : undefined}>
      <span aria-hidden>{BAND_ICON[band]}</span> {BAND_LABEL[band]}
      {risk != null && band !== "breached" && <b>{pct(risk)}</b>}
    </span>
  );
}

export function Priority({ p }: { p: string }) {
  return <span className={`prio prio-${p}`}>{p}</span>;
}

export function DueIn({ iso }: { iso: string }) {
  const now = useNow(30000);
  const h = (new Date(iso).getTime() - now) / 3.6e6;
  const txt = Math.abs(h) < 48 ? `${Math.abs(h).toFixed(0)}h` : `${(Math.abs(h) / 24).toFixed(1)}d`;
  return <span className={h < 0 ? "due-over" : h < 8 ? "due-soon" : ""}>{h < 0 ? `${txt} overdue` : `in ${txt}`}</span>;
}

export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

/** Server-authoritative timer: renders now - started_at; holds no state of its own. */
export function LiveTimer({ startedAt }: { startedAt: string }) {
  const now = useNow(1000);
  const s = Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
  const hh = String(Math.floor(s / 3600)).padStart(2, "0");
  const mm = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return <span className="timer">{hh}:{mm}:{ss}</span>;
}

export function ErrorNote({ error }: { error: string | null }) {
  return error ? <div className="error">⚠ {error}</div> : null;
}

export function Loading() {
  return <div className="loading">Loading…</div>;
}
