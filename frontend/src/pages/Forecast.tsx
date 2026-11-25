import { Area, Bar, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Card, ErrorNote, Kpi, Loading, num, pct, shortDate, useAsync } from "../components/ui";
import { C, axis, grid, tooltipStyle } from "../theme";

export default function ForecastPage() {
  const { data, error } = useAsync(api.forecast);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Loading />;
  const cap = data.capacity;

  const series = [
    ...data.history.slice(-56).map((h) => ({ date: h.date, actual: h.actual })),
    ...data.forecast.map((f) => ({ date: f.date, forecast: f.forecast, band: [f.lower, f.upper] as [number, number] })),
  ];
  const staffing = data.forecast.filter((f) => new Date(f.date).getUTCDay() % 6 !== 0);
  const gain = 1 - data.backtest.holt_winters_wape / data.backtest.seasonal_naive_wape;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Forecast & capacity</h1>
          <p className="muted">28-day ticket inflow forecast (Holt-Winters per work type), turned into required FTE using each type's median handle time.</p>
        </div>
      </header>

      <div className="kpi-row">
        <Kpi label="Forecast · next 7 days" value={num(data.forecast.slice(0, 7).reduce((s, f) => s + f.forecast, 0))} hint="tickets" />
        <Kpi label="Avg weekday FTE needed" value={num(cap.avg_weekday_required_fte, 1)} hint={`of ${num(cap.available_fte, 1)} available`} />
        <Kpi label="Peak FTE needed" value={num(cap.peak_required_fte, 1)} tone={cap.peak_required_fte > cap.available_fte ? "bad" : "good"}
          hint={cap.peak_required_fte > cap.available_fte ? `short by ${num(cap.peak_required_fte - cap.available_fte, 1)} FTE` : "within capacity"} />
        <Kpi label="Days over capacity" value={num(cap.days_over_capacity)} hint="next 28 days" tone={cap.days_over_capacity ? "warn" : "good"} />
        <Kpi label="Back-test error (WAPE)" value={pct(data.backtest.holt_winters_wape, 1)} hint={`${pct(gain)} better than seasonal naive`} tone="good" />
      </div>

      <Card title="Daily inflow: actuals and forecast" subtitle="Shaded band = 90% prediction interval">
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={series} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
            <CartesianGrid {...grid} />
            <XAxis dataKey="date" tickFormatter={shortDate} {...axis} minTickGap={28} />
            <YAxis {...axis} />
            <Tooltip {...tooltipStyle} labelFormatter={shortDate}
              formatter={(v: number | [number, number], n: string) => (Array.isArray(v) ? [`${v[0]} – ${v[1]}`, n] : [v, n])} />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
            <Area isAnimationActive={false} dataKey="band" name="90% interval" stroke="none" fill={C.band} fillOpacity={0.6} />
            <Line isAnimationActive={false} dataKey="actual" name="Actual" stroke={C.ink2} strokeWidth={2} dot={false} connectNulls={false} />
            <Line isAnimationActive={false} dataKey="forecast" name="Forecast" stroke={C.s1} strokeWidth={2} strokeDasharray="5 3" dot={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid-2">
        <Card title="Staffing: required vs available FTE" subtitle="Working days; weekend inflow carried to Monday">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={staffing} margin={{ top: 8, right: 12, left: -12, bottom: 0 }} barCategoryGap={4}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="date" tickFormatter={shortDate} {...axis} minTickGap={20} />
              <YAxis {...axis} />
              <Tooltip {...tooltipStyle} labelFormatter={shortDate} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar isAnimationActive={false} dataKey="required_fte" name="Required FTE" fill={C.s1} radius={[4, 4, 0, 0]} />
              <Line isAnimationActive={false} dataKey="available_fte" name="Available FTE" stroke={C.s2} strokeWidth={2} dot={false} type="stepAfter" />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title={`Back-test · last ${data.backtest.days} days`} subtitle="Forecast made without seeing these days">
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={data.backtest.series} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="date" tickFormatter={shortDate} {...axis} minTickGap={20} />
              <YAxis {...axis} />
              <Tooltip {...tooltipStyle} labelFormatter={shortDate} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} dataKey="actual" name="Actual" stroke={C.ink2} strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} dataKey="holt_winters" name={`Holt-Winters (WAPE ${pct(data.backtest.holt_winters_wape, 1)})`} stroke={C.s1} strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} dataKey="seasonal_naive" name={`Seasonal naive (WAPE ${pct(data.backtest.seasonal_naive_wape, 1)})`} stroke={C.s2} strokeWidth={2} strokeDasharray="4 3" dot={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <Card title="Next 7 days by work type" subtitle="Forecast volume × median handle time">
        <table className="table">
          <thead><tr><th>Work type</th><th className="r">Tickets</th><th className="r">Median AHT</th><th className="r">Workload (hrs)</th></tr></thead>
          <tbody>
            {Object.entries(data.by_type_next_7d).sort((a, b) => b[1] - a[1]).map(([code, n]) => (
              <tr key={code}>
                <td className="mono">{code}</td>
                <td className="r">{num(n)}</td>
                <td className="r">{num(cap.aht_by_type[code])} min</td>
                <td className="r">{num((n * (cap.aht_by_type[code] ?? 0)) / 60)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
