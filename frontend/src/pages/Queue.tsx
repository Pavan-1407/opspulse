import { useState } from "react";
import { api, PlanItem, RiskBand, Ticket } from "../api";
import { Card, DueIn, ErrorNote, Loading, pct, Priority, RiskBadge, useAsync } from "../components/ui";
import TicketDrawer from "../components/TicketDrawer";

const BANDS: RiskBand[] = ["breached", "high", "medium", "low"];

export default function Queue() {
  const [bands, setBands] = useState<RiskBand[]>([]);
  const [workType, setWorkType] = useState("");
  const [unassigned, setUnassigned] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [plan, setPlan] = useState<PlanItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const wts = useAsync(api.workTypes);
  const q = useAsync(
    () => api.tickets({ risk_band: bands.join(","), work_type: workType, unassigned: unassigned || undefined }),
    [bands.join(","), workType, unassigned],
  );

  const toggle = (b: RiskBand) => setBands((xs) => (xs.includes(b) ? xs.filter((x) => x !== b) : [...xs, b]));

  async function previewPlan() {
    setBusy(true);
    try { setPlan(await api.balancePreview(8)); } catch (e) { setMsg(String((e as Error).message)); } finally { setBusy(false); }
  }
  async function applyPlan() {
    if (!plan) return;
    setBusy(true);
    try {
      await api.balanceApply(plan);
      setMsg(`Assigned ${plan.length} tickets.`);
      setPlan(null);
      q.reload();
    } catch (e) { setMsg(String((e as Error).message)); } finally { setBusy(false); }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Work queue</h1>
          <p className="muted">Open tickets ranked by predicted SLA-breach risk. Click a ticket for risk drivers and assignment recommendations.</p>
        </div>
        <button className="btn primary" onClick={previewPlan} disabled={busy}>⚖ Auto-balance unassigned</button>
      </header>

      <div className="filters">
        <div className="chips">
          {BANDS.map((b) => (
            <button key={b} className={`chip ${bands.includes(b) ? "on" : ""}`} onClick={() => toggle(b)}>
              <RiskBadge band={b} />
            </button>
          ))}
        </div>
        <select value={workType} onChange={(e) => setWorkType(e.target.value)}>
          <option value="">All work types</option>
          {wts.data?.map((w) => <option key={w.code} value={w.code}>{w.name}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={unassigned} onChange={(e) => setUnassigned(e.target.checked)} /> Unassigned only</label>
        {q.data && <span className="muted">{q.data.length} tickets</span>}
      </div>

      {msg && <div className="note" onClick={() => setMsg(null)}>{msg}</div>}

      {plan && (
        <Card title={`Proposed assignment plan · ${plan.length} tickets`}
          subtitle="Hungarian algorithm minimizing predicted breach risk + load imbalance, capped at 8 open tickets per analyst."
          actions={<div className="row"><button className="btn" onClick={() => setPlan(null)}>Discard</button><button className="btn primary" onClick={applyPlan} disabled={busy || !plan.length}>Apply plan</button></div>}>
          <table className="table compact">
            <thead><tr><th>Ticket</th><th>Assign to</th><th className="r">Predicted risk</th></tr></thead>
            <tbody>
              {plan.map((p) => (
                <tr key={p.ticket_id}><td className="mono">{p.external_ref}</td><td>{p.analyst_name}</td><td className="r">{pct(p.predicted_risk, 1)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <ErrorNote error={q.error} />
      {!q.data ? <Loading /> : (
        <Card>
          <table className="table hover">
            <thead>
              <tr><th>Ticket</th><th>Title</th><th>Type</th><th>Pri</th><th>Status</th><th>Assignee</th><th>Due</th><th>SLA risk</th></tr>
            </thead>
            <tbody>
              {q.data.map((t: Ticket) => (
                <tr key={t.id} onClick={() => setSelected(t.id)} className={selected === t.id ? "sel" : ""}>
                  <td className="mono">{t.external_ref}</td>
                  <td className="ellipsis">{t.title}</td>
                  <td className="mono muted">{t.work_type.code}</td>
                  <td><Priority p={t.priority} /></td>
                  <td><span className={`status s-${t.status}`}>{t.status.replace("_", " ")}</span></td>
                  <td>{t.analyst_name ?? <span className="muted">Unassigned</span>}</td>
                  <td><DueIn iso={t.due_at} /></td>
                  <td><RiskBadge band={t.risk_band} risk={t.sla_risk} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {selected != null && <TicketDrawer id={selected} onClose={() => setSelected(null)} onChanged={q.reload} />}
    </>
  );
}
