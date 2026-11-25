import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Card, ErrorNote, Kpi, Loading, num, pct, shortDate, useAsync } from "../components/ui";
import { C, axis, grid, tooltipStyle } from "../theme";

export default function Overview() {
  const { data, error } = useAsync(api.overview);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const k = data.kpis;
  const delta = k.sla_attainment_30d != null && k.sla_attainment_prev_30d != null ? k.sla_attainment_30d - k.sla_attainment_prev_30d : null;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Operations overview</h1>
          <p className="muted">Live queue health, SLA performance and team load · as of {new Date(data.as_of).toLocaleString()}</p>
        </div>
      </header>

      <div className="kpi-row">
        <Kpi label="SLA attainment · 30d" value={pct(k.sla_attainment_30d, 1)}
          hint={delta != null ? `${delta >= 0 ? "▲" : "▼"} ${Math.abs(delta * 100).toFixed(1)} pts vs prior 30d` : undefined}
          tone={delta != null ? (delta >= 0 ? "good" : "bad") : undefined} />
        <Kpi label="Open backlog" value={num(k.open_backlog)} hint={`${k.unassigned} unassigned`} />
        <Kpi label="High breach risk" value={num(k.high_risk)} hint="predicted ≥ 60%" tone={k.high_risk ? "warn" : undefined} />
        <Kpi label="Past due" value={num(k.past_due)} tone={k.past_due ? "bad" : "good"} hint={k.past_due ? "needs action now" : "none"} />
        <Kpi label="Median handle time · 30d" value={`${num(k.median_aht_30d)} min`} hint={`${num(k.closed_30d)} tickets closed`} />
        <Kpi label="Live timers" value={num(k.active_timers)} hint={`backlog pressure ${k.queue_pressure.toFixed(2)} days`} />
      </div>

      <div className="grid-2">
        <Card title="Daily flow · last 60 days" subtitle="Tickets received vs closed">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data.flow} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="date" tickFormatter={shortDate} {...axis} minTickGap={28} />
              <YAxis {...axis} />
              <Tooltip {...tooltipStyle} labelFormatter={shortDate} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} dataKey="received" name="Received" stroke={C.s1} strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} dataKey="closed" name="Closed" stroke={C.s2} strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card title="SLA attainment by work type · 30d" subtitle="Sorted worst first">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={data.by_work_type} layout="vertical" margin={{ top: 4, right: 36, left: 24, bottom: 0 }} barCategoryGap={6}>
              <CartesianGrid {...grid} horizontal={false} vertical />
              <XAxis type="number" domain={[0, 1]} tickFormatter={(v) => pct(v)} {...axis} />
              <YAxis type="category" dataKey="work_type" width={92} {...axis} />
              <Tooltip {...tooltipStyle} formatter={(v: number) => pct(v, 1)} />
              <Bar isAnimationActive={false} dataKey="attainment" name="SLA attainment" fill={C.s1} radius={[0, 4, 4, 0]}
                label={{ position: "right", fontSize: 11, fill: C.ink2, formatter: (v: number) => pct(v) }} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Work type scorecard" subtitle="Handle time vs target, last 30 days">
          <table className="table">
            <thead><tr><th>Work type</th><th className="r">Closed</th><th className="r">Open</th><th className="r">Median AHT</th><th className="r">Target</th><th className="r">SLA</th></tr></thead>
            <tbody>
              {data.by_work_type.map((w) => {
                const over = w.median_aht_min != null && w.median_aht_min > w.target_aht_min * 1.1;
                return (
                  <tr key={w.work_type}>
                    <td className="mono">{w.work_type}</td>
                    <td className="r">{num(w.closed)}</td>
                    <td className="r">{num(w.open)}</td>
                    <td className={`r ${over ? "txt-bad" : ""}`}>{num(w.median_aht_min)} min</td>
                    <td className="r muted">{num(w.target_aht_min)} min</td>
                    <td className="r">{pct(w.attainment, 1)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>

        <Card title="Team load" subtitle="Open tickets and 7-day logged utilization">
          <table className="table">
            <thead><tr><th>Analyst</th><th>Team</th><th className="r">Open</th><th className="r">At risk</th><th>Utilization · 7d</th></tr></thead>
            <tbody>
              {data.analysts.slice(0, 12).map((a) => (
                <tr key={a.analyst_id}>
                  <td>{a.name}</td>
                  <td className="muted">{a.team}</td>
                  <td className="r">{a.open}</td>
                  <td className={`r ${a.high_risk ? "txt-bad" : "muted"}`}>{a.high_risk}</td>
                  <td>
                    <div className="meter" title={pct(a.utilization_7d)}>
                      <span style={{ width: `${Math.min(a.utilization_7d, 1.2) / 1.2 * 100}%` }} className={a.utilization_7d > 1 ? "over" : ""} />
                      <em>{pct(a.utilization_7d)}</em>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </>
  );
}
