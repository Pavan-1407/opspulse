import { useState } from "react";
import { api } from "../api";
import { DueIn, ErrorNote, Loading, pct, Priority, RiskBadge, useAsync } from "./ui";
import { C } from "../theme";

export default function TicketDrawer({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const d = useAsync(() => api.ticket(id), [id]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function assign(analystId: number) {
    setBusy(true);
    try {
      await api.assign(id, analystId);
      d.reload();
      onChanged();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }

  const t = d.data?.ticket;
  const maxImpact = Math.max(0.01, ...(d.data?.drivers.map((x) => Math.abs(x.impact)) ?? [0]));

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()} role="dialog" aria-label="Ticket detail">
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        {!t ? <Loading /> : (
          <>
            <p className="mono muted">{t.external_ref} · {t.work_type.name}</p>
            <h2>{t.title}</h2>
            <div className="row wrap">
              <Priority p={t.priority} />
              <span className={`status s-${t.status}`}>{t.status.replace("_", " ")}</span>
              <span className="muted">Due <DueIn iso={t.due_at} /></span>
              <span className="muted">Complexity {t.complexity} · {t.line_items} line items · via {t.channel}</span>
            </div>

            <div className="risk-hero">
              <div>
                <div className="kpi-label">Predicted SLA-breach risk</div>
                <div className="big">{t.risk_band === "breached" ? "Past due" : pct(t.sla_risk, 1)}</div>
                <div className="muted small">Basis: {t.risk_basis}</div>
              </div>
              <RiskBadge band={t.risk_band} />
            </div>

            {d.data!.drivers.length > 0 && (
              <section>
                <h4>Why? Top risk drivers <span className="muted small">(SHAP, log-odds)</span></h4>
                <ul className="drivers">
                  {d.data!.drivers.map((x) => (
                    <li key={x.feature}>
                      <span className="dl">{x.label}<em>{fmtValue(x.feature, x.value)}</em></span>
                      <span className="dbar">
                        <span className="axis" />
                        <span className="fill" style={{
                          width: `${(Math.abs(x.impact) / maxImpact) * 50}%`,
                          left: x.impact >= 0 ? "50%" : `${50 - (Math.abs(x.impact) / maxImpact) * 50}%`,
                          background: x.impact >= 0 ? C.critical : C.s1,
                        }} />
                      </span>
                      <span className="dv">{x.impact >= 0 ? "▲ raises" : "▼ lowers"}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {d.data!.recommendations.length > 0 && (
              <section>
                <h4>Recommended assignees <span className="muted small">(what-if risk per analyst + load balance)</span></h4>
                <ErrorNote error={err} />
                {d.data!.recommendations.map((r, i) => (
                  <div className="rec" key={r.analyst_id}>
                    <div>
                      <strong>{i === 0 && "★ "}{r.name}</strong> <span className="muted">· {r.team}</span>
                      <div className="muted small">{r.reasons.join(" · ")}</div>
                    </div>
                    <div className="rec-right">
                      <span className="small">risk {pct(r.predicted_risk, 1)}</span>
                      {t.assigned_to === r.analyst_id
                        ? <span className="tag">Current</span>
                        : <button className="btn sm" disabled={busy} onClick={() => assign(r.analyst_id)}>Assign</button>}
                    </div>
                  </div>
                ))}
              </section>
            )}

            <section>
              <h4>Time log · {d.data!.logged_minutes.toFixed(0)} min</h4>
              {d.data!.time_entries.length === 0 ? <p className="muted small">No time logged yet.</p> : (
                <ul className="log">
                  {d.data!.time_entries.map((e) => (
                    <li key={e.id}>{new Date(e.started_at).toLocaleString()} — {e.ended_at ? `${e.minutes?.toFixed(0)} min` : "running"}{e.auto_closed && " (auto-closed)"}</li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
        <ErrorNote error={d.error} />
      </aside>
    </div>
  );
}

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
function fmtValue(feature: string, v: number): string {
  if (feature === "received_dow") return DOW[v] ?? String(v);
  if (feature === "received_hour") return `${String(v).padStart(2, "0")}:00 UTC`;
  if (feature === "frac_sla_used") return `${Math.round(v * 100)}%`;
  if (feature === "skill_match") return v ? "yes" : "no";
  if (feature.startsWith("wt_") || feature.startsWith("ch_")) return v ? "yes" : "no";
  if (feature.endsWith("_h") || feature === "hours_to_due") return `${v.toFixed(1)}h`;
  return Number.isInteger(v) ? String(v) : v.toFixed(2);
}
