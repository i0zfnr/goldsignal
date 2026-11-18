import { useEffect, useState } from "react";
import { api } from "./access";

const periods = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["all", "All"]] as const;
type Period = typeof periods[number][0];
type Results = { wins: number; losses: number; flat: number; pips: number };
type Report = Results & { signals: number; buckets: (Results & { label: string })[] };

const pipsFormat = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
const closedCount = (row: Results) => row.wins + row.losses + row.flat;
const winRate = (row: Results) => closedCount(row) ? `${(100 * row.wins / closedCount(row)).toFixed(1)}%` : "—";

export function Performance({ revision }: { revision?: string }) {
  const [period, setPeriod] = useState<Period>("day");
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    api<Report>(`/api/performance?period=${period}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setReport(result); })
      .catch(() => { if (!controller.signal.aborted) setError("Could not load performance."); });
    return () => controller.abort();
  }, [period, revision]);

  const scale = Math.max(1, ...(report?.buckets.map(row => Math.abs(row.pips)) ?? []));
  const count = report ? closedCount(report) : 0;
  return <section className="panel below performance" id="performance" aria-labelledby="performance-title">
    <div className="panel-heading"><h2 id="performance-title">Performance</h2><span className="muted">Simulated · MYT</span></div>
    <div className="report-periods" role="group" aria-label="Performance period">
      {periods.map(([value, title]) => <button type="button" aria-pressed={value === period} key={value}
        onClick={() => { if (value !== period) { setReport(null); setPeriod(value); } }}>{title}</button>)}
    </div>
    {error && <p className="warn" role="status">{error}</p>}
    {!report && !error && <p className="muted" role="status">Loading performance…</p>}
    {report && <>
      <dl className="report-stats">
        <div><dt>Signals issued</dt><dd>{report.signals}</dd></div>
        <div><dt>Win rate</dt><dd>{winRate(report)}</dd><span className="small muted">{count} closed {count === 1 ? "trade" : "trades"}</span></div>
        <div><dt>Net pips before fees</dt><dd className={report.pips < 0 ? "warn" : report.pips > 0 ? "good" : ""}>{count ? pipsFormat.format(report.pips) : "—"}</dd></div>
      </dl>
      {count > 0 ? <>
        <div className="report-outcomes">
          <div className="win-gauge" aria-hidden="true" style={{ background: `conic-gradient(var(--gold) ${100 * report.wins / count}%, var(--line) 0)` }}>
            <span>{winRate(report)}</span>
          </div>
          <dl><div><dt>Profitable</dt><dd className="good">{report.wins}</dd></div>
            <div><dt>Break-even</dt><dd>{report.flat}</dd></div>
            <div><dt>Losing</dt><dd className="warn">{report.losses}</dd></div></dl>
        </div>
        <table className="report-breakdown">
          <thead><tr><th scope="col">{period === "all" ? "Month" : "Date"}</th><th scope="col">Win rate</th><th scope="col">Net pips</th></tr></thead>
          <tbody>{report.buckets.map(row => <tr key={row.label}>
            <th scope="row">{row.label}</th>
            <td>{winRate(row)} <span className="muted">({closedCount(row)})</span></td>
            <td className={row.pips < 0 ? "warn" : "good"}><span className="report-bar" aria-hidden="true"><i style={{ width: `${Math.abs(row.pips) / scale * 100}%` }} /></span>{pipsFormat.format(row.pips)}</td>
          </tr>)}</tbody>
        </table>
      </> : <p className="small muted">No trades closed in this period.</p>}
    </>}
  </section>;
}
