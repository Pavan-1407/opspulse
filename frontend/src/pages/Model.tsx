import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api";
import { Card, ErrorNote, Kpi, Loading, num, pct, useAsync } from "../components/ui";
import { C, axis, grid, tooltipStyle } from "../theme";

export default function ModelPage() {
  const { data: m, error } = useAsync(api.modelCard);
  if (error) return <ErrorNote error={error} />;
  if (!m) return <Loading />;
  const lift = m.precision_at_top10pct / m.base_rate_test;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Model card · SLA breach predictor</h1>
          <p className="muted">{m.model}. Time-based split: trained on {m.train_period.join(" → ")}, tested on unseen {m.test_period.join(" → ")}.</p>
        </div>
      </header>

      <div className="kpi-row">
        <Kpi label="ROC-AUC" value={m.roc_auc.toFixed(3)} hint={`baseline ${m.baseline.roc_auc.toFixed(3)}`} tone="good" />
        <Kpi label="PR-AUC" value={m.pr_auc.toFixed(3)} hint={`baseline ${m.baseline.pr_auc.toFixed(3)} · base rate ${pct(m.base_rate_test, 1)}`} tone="good" />
        <Kpi label="Brier score" value={m.brier.toFixed(3)} hint={`baseline ${m.baseline.brier.toFixed(3)} (lower is better)`} />
        <Kpi label="Precision @ top 10%" value={pct(m.precision_at_top10pct, 1)} hint={`${lift.toFixed(1)}× lift · catches ${pct(m.recall_at_top10pct)} of breaches`} />
        <Kpi label="Test tickets" value={num(m.n_test)} hint={`${num(m.n_train)} for training`} />
      </div>

      <div className="grid-2">
        <Card title="What drives breach risk" subtitle="Mean |SHAP| on the test set">
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={m.feature_importance} layout="vertical" margin={{ top: 4, right: 16, left: 40, bottom: 0 }} barCategoryGap={5}>
              <CartesianGrid {...grid} horizontal={false} vertical />
              <XAxis type="number" {...axis} />
              <YAxis type="category" dataKey="label" width={150} {...axis} />
              <Tooltip {...tooltipStyle} formatter={(v: number) => v.toFixed(3)} />
              <Bar isAnimationActive={false} dataKey="mean_abs_shap" name="Mean |SHAP|" fill={C.s1} radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Calibration" subtitle="When the model says 30%, about 30% breach">
          <ResponsiveContainer width="100%" height={320}>
            <LineChart data={m.calibration} margin={{ top: 8, right: 16, left: -12, bottom: 0 }}>
              <CartesianGrid {...grid} />
              <XAxis dataKey="predicted" type="number" domain={[0, 1]} tickFormatter={(v) => pct(v)} {...axis} />
              <YAxis domain={[0, 1]} tickFormatter={(v) => pct(v)} {...axis} />
              <Tooltip {...tooltipStyle} formatter={(v: number) => pct(v, 1)} labelFormatter={(v) => `Predicted ${pct(Number(v), 1)}`} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} data={[{ predicted: 0, observed: 0 }, { predicted: 1, observed: 1 }]} dataKey="observed" name="Perfect calibration"
                stroke={C.ink2} strokeDasharray="4 4" dot={false} strokeWidth={1.5} />
              <Line isAnimationActive={false} dataKey="observed" name="Model" stroke={C.s1} strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Accuracy over a ticket's life" subtitle="ROC-AUC by share of SLA already used when scored">
          <table className="table">
            <thead><tr><th>SLA used</th><th className="r">Test rows</th><th className="r">Breach rate</th><th className="r">ROC-AUC</th></tr></thead>
            <tbody>
              {(m.auc_by_sla_stage ?? []).map((s) => (
                <tr key={s.stage}><td>{s.stage}</td><td className="r">{num(s.n)}</td><td className="r">{pct(s.breach_rate, 1)}</td><td className="r">{s.roc_auc.toFixed(3)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="muted small">Earlier predictions are harder but more useful: there is still time to act.</p>
        </Card>
        <Card title="How it is used">
          <ul className="bullets">
            <li><b>Landmark framing.</b> "Given this ticket is still open now, will it breach?" Training rows are snapshots at random points in each ticket's life, so live scoring matches training.</li>
            <li><b>No leakage.</b> Queue pressure and assignee load are captured at intake; analyst speed is learned on the training window only.</li>
            <li><b>What-if scoring.</b> The same model scores every candidate analyst, which drives the recommendations and the auto-balancer.</li>
            <li><b>Explainable.</b> Each ticket shows its top SHAP drivers, so a team lead can see <i>why</i> it is flagged.</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
