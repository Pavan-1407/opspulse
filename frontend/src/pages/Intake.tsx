import { FormEvent, useState } from "react";
import { api } from "../api";
import { Card, ErrorNote, useAsync } from "../components/ui";

type Report = Awaited<ReturnType<typeof api.upload>>;

export default function Intake() {
  const wts = useAsync(api.workTypes);
  const [form, setForm] = useState({ title: "", work_type_code: "DATA_FIX", priority: "P3", complexity: 1, line_items: 1, channel: "portal" });
  const [created, setCreated] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const t = await api.createTicket(form);
      setCreated(`${t.external_ref} created, due ${new Date(t.due_at).toLocaleString()}`);
      setForm({ ...form, title: "" });
    } catch (e) { setErr((e as Error).message); }
  }

  async function upload(f: File | undefined) {
    if (!f) return;
    setErr(null);
    setReport(null);
    try { setReport(await api.upload(f)); } catch (e) { setErr((e as Error).message); }
  }

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Intake & upload</h1>
          <p className="muted">Log a single ticket or bulk-load a CSV / Excel export. Every row is validated and the report shows what was rejected and why.</p>
        </div>
      </header>
      <ErrorNote error={err} />
      <div className="grid-2">
        <Card title="New ticket">
          <form className="form" onSubmit={submit}>
            <label>Title<input required minLength={3} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="e.g. Fix duplicate member records" /></label>
            <label>Work type
              <select value={form.work_type_code} onChange={(e) => setForm({ ...form, work_type_code: e.target.value })}>
                {wts.data?.map((w) => <option key={w.code} value={w.code}>{w.name} · SLA {w.sla_hours}h</option>)}
              </select>
            </label>
            <div className="form-row">
              <label>Priority
                <select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
                  {["P1", "P2", "P3", "P4"].map((p) => <option key={p}>{p}</option>)}
                </select>
              </label>
              <label>Complexity
                <select value={form.complexity} onChange={(e) => setForm({ ...form, complexity: Number(e.target.value) })}>
                  {[1, 2, 3].map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
              <label>Line items<input type="number" min={1} value={form.line_items} onChange={(e) => setForm({ ...form, line_items: Number(e.target.value) })} /></label>
              <label>Channel
                <select value={form.channel} onChange={(e) => setForm({ ...form, channel: e.target.value })}>
                  {["portal", "email", "batch"].map((c) => <option key={c}>{c}</option>)}
                </select>
              </label>
            </div>
            <button className="btn primary" type="submit">Create ticket</button>
            {created && <div className="note">✓ {created}</div>}
          </form>
        </Card>

        <Card title="Bulk upload" subtitle="Required columns: external_ref, title, work_type, priority. Optional: received_at, channel, complexity, line_items">
          <label className="drop">
            <input type="file" accept=".csv,.xlsx" onChange={(e) => upload(e.target.files?.[0])} />
            <span>⇪ Choose a .csv or .xlsx file</span>
          </label>
          <p className="small"><button type="button" className="linkbtn" onClick={downloadTemplate}>Download template CSV</button></p>
          {report && (
            <div className="report">
              <div className="row"><span className="tag good">{report.inserted} inserted</span><span className="tag">{report.updated} updated</span><span className={`tag ${report.rejected ? "bad" : ""}`}>{report.rejected} rejected</span></div>
              {report.errors.length > 0 && (
                <table className="table compact"><thead><tr><th>Row</th><th>Problem</th></tr></thead>
                  <tbody>{report.errors.map((e) => <tr key={e.row}><td>{e.row}</td><td>{e.error}</td></tr>)}</tbody></table>
              )}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function downloadTemplate() {
  const csv = "external_ref,title,work_type,priority,received_at,channel,complexity,line_items\n" +
    "EXT-1001,Fix duplicate member records,DATA_FIX,P2,,email,1,4\n" +
    "EXT-1002,Quarterly vendor reconciliation,RECON,P3,,batch,3,12\n";
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "opspulse_upload_template.csv";
  a.click();
  URL.revokeObjectURL(url);
}
