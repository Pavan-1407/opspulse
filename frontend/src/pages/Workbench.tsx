import { useEffect, useState } from "react";
import { api, Timer } from "../api";
import { Card, DueIn, ErrorNote, LiveTimer, Loading, Priority, RiskBadge, useAsync } from "../components/ui";

export default function Workbench() {
  const analysts = useAsync(api.analysts);
  const [me, setMe] = useState<number | null>(null);
  const [timers, setTimers] = useState<Timer[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const mine = useAsync(() => (me ? api.tickets({ assigned_to: me }) : Promise.resolve([])), [me]);

  useEffect(() => {
    if (me == null && analysts.data?.length) setMe(analysts.data[0].id);
  }, [analysts.data, me]);

  // Poll the server for the team board; each client renders elapsed time locally.
  useEffect(() => {
    const load = () => api.activeTimers().then(setTimers).catch(() => undefined);
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, []);

  const names = Object.fromEntries((analysts.data ?? []).map((a) => [a.id, a.name]));
  const running = timers.find((t) => t.analyst_id === me);

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      setTimers(await api.activeTimers());
      mine.reload();
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Analyst workbench</h1>
          <p className="muted">Start and stop work timers. Timers live on the server, so they survive refreshes, tabs and devices.</p>
        </div>
        <label className="actas">
          Acting as
          <select value={me ?? ""} onChange={(e) => setMe(Number(e.target.value))}>
            {analysts.data?.map((a) => <option key={a.id} value={a.id}>{a.name} · {a.team}</option>)}
          </select>
        </label>
      </header>
      <ErrorNote error={err ?? analysts.error ?? mine.error} />

      <div className="grid-2 wide-left">
        <Card title="My open tickets" subtitle={running ? `Working on ${running.ticket_ref}` : "No timer running"}>
          {!mine.data ? <Loading /> : mine.data.length === 0 ? <p className="muted">No open tickets assigned. Pick some from the work queue.</p> : (
            <table className="table">
              <thead><tr><th>Ticket</th><th>Due</th><th>Risk</th><th>Timer</th><th></th></tr></thead>
              <tbody>
                {mine.data.map((t) => {
                  const isRunning = running?.ticket_id === t.id;
                  return (
                    <tr key={t.id} className={isRunning ? "sel" : ""}>
                      <td><div className="row"><Priority p={t.priority} /><span className="mono">{t.external_ref}</span></div><div className="muted small ellipsis narrow">{t.title}</div></td>
                      <td><DueIn iso={t.due_at} /></td>
                      <td><RiskBadge band={t.risk_band} risk={t.sla_risk} /></td>
                      <td>{isRunning ? <LiveTimer startedAt={running!.started_at} /> : <span className="muted">—</span>}</td>
                      <td><div className="actions">
                        {isRunning
                          ? <button className="btn sm" onClick={() => act(() => api.stopTimer(running!.id))}>❚❚ Pause</button>
                          : <button className="btn sm primary" onClick={() => act(() => api.startTimer(me!, t.id))}>▶ Start</button>}
                        <button className="btn sm" onClick={() => act(() => api.setStatus(t.id, "ON_HOLD"))} disabled={t.status === "ON_HOLD"}>Hold</button>
                        <button className="btn sm" onClick={() => act(() => api.setStatus(t.id, "CLOSED"))}>✓ Close</button>
                      </div></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </Card>

        <Card title={`Live team board · ${timers.length} running`} subtitle="Refreshes every 15s">
          {timers.length === 0 ? <p className="muted">Nobody is timing work right now.</p> : (
            <ul className="board">
              {timers.map((t) => (
                <li key={t.id} className={t.analyst_id === me ? "me" : ""}>
                  <span className="pulse" aria-hidden />
                  <div>
                    <strong>{names[t.analyst_id] ?? `Analyst ${t.analyst_id}`}</strong>
                    <div className="muted small ellipsis">{t.ticket_ref} · {t.ticket_title}</div>
                  </div>
                  <LiveTimer startedAt={t.started_at} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
