import { useEffect, useState } from "react";
import { api } from "./access";
import { Badge, EmptyState, LoadingState, Metric, PanelHeading } from "./ui";

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
  return <section className="performance" id="performance" aria-labelledby="performance-title">
    <PanelHeading id="performance-title" title="Performance"><Badge>Simulated · MYT</Badge></PanelHeading>
    <div className="report-periods segment-group" role="group" aria-label="Performance period">
      {periods.map(([value, title]) => <button type="button" aria-pressed={value === period} key={value}
        onClick={() => { if (value !== period) { setReport(null); setPeriod(value); } }}>{title}</button>)}
    </div>
    {error && <p className="warn" role="status">{error}</p>}
    {!report && !error && <LoadingState>Loading performance…</LoadingState>}
    {report && <>
      <dl className="report-stats">
        <Metric label="Signals issued">{report.signals}</Metric>
        <Metric label="Win rate" note={`${count} closed ${count === 1 ? "trade" : "trades"}`}>{winRate(report)}</Metric>
        <Metric label="Net pips before fees" tone={report.pips < 0 ? "negative" : report.pips > 0 ? "positive" : "neutral"}>
          {count ? pipsFormat.format(report.pips) : "—"}
        </Metric>
      </dl>
      {count > 0 ? <div className="performance-detail">
        <div className="panel below profitability">
          <PanelHeading title="Trade outcomes" as="h3" />
          <div className="report-outcomes">
          <div className="win-gauge" aria-hidden="true" style={{ background: `conic-gradient(var(--gold) ${100 * report.wins / count}%, var(--line) 0)` }}>
            <span>{winRate(report)}</span>
          </div>
          <dl><div><dt>Profitable</dt><dd className="good">{report.wins}</dd></div>
            <div><dt>Break-even</dt><dd>{report.flat}</dd></div>
            <div><dt>Losing</dt><dd className="warn">{report.losses}</dd></div></dl>
          </div>
        </div>
        <div className="panel below">
        <PanelHeading title="Performance history" as="h3" />
        <table className="report-breakdown">
          <thead><tr><th scope="col">{period === "all" ? "Month" : "Date"}</th><th scope="col">Win rate</th><th scope="col">Net pips</th></tr></thead>
          <tbody>{report.buckets.map(row => <tr key={row.label}>
            <th scope="row">{row.label}</th>
            <td>{winRate(row)} <span className="muted">({closedCount(row)})</span></td>
            <td className={row.pips < 0 ? "warn" : "good"}><span className="report-bar" aria-hidden="true"><i style={{ width: `${Math.abs(row.pips) / scale * 100}%` }} /></span>{pipsFormat.format(row.pips)}</td>
          </tr>)}</tbody>
        </table>
        </div>
      </div> : <EmptyState>No trades closed in this period.</EmptyState>}
    </>}
  </section>;
}
