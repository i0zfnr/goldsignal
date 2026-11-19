import { useEffect, useState } from "react";
import { api } from "./access";
import { Badge, EmptyState, LoadingState, Metric, PanelHeading } from "./ui";

const periods = [["day", "Day"], ["week", "Week"], ["month", "Month"], ["all", "All"]] as const;
type Period = typeof periods[number][0];
type Results = { wins: number; losses: number; flat: number; pips: number };
type Report = Results & { signals: number; buckets: (Results & { label: string })[] };
type SessionRow = {
  session: string; detected: number; published: number; closed: number; wins: number;
  losses: number; flat: number; pips: number; win_rate: number | null;
  low: number | null; high: number | null; status: string; last: number | null;
};

const pipsFormat = new Intl.NumberFormat("en-MY", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
const closedCount = (row: Results) => row.wins + row.losses + row.flat;
const winRate = (row: Results) => closedCount(row) ? `${(100 * row.wins / closedCount(row)).toFixed(1)}%` : "—";

export function Performance({ revision }: { revision?: string }) {
  const [period, setPeriod] = useState<Period>("day");
  const [report, setReport] = useState<Report | null>(null);
  const [sessions, setSessions] = useState<SessionRow[] | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    const controller = new AbortController();

    async function load(isFirst = false) {
      if (isFirst) {
        setError("");
        setSessionError("");
      }
      try {
        const rep = await api<Report>(`/api/performance?period=${period}`, { signal: controller.signal });
        if (current) setReport(rep);
      } catch (failure) {
        if (current && !controller.signal.aborted && isFirst) {
          setError("Could not load performance.");
        }
      }
      try {
        const sess = await api<{ sessions: SessionRow[] }>(`/api/sessions?period=${period}`, { signal: controller.signal });
        if (current) setSessions(sess.sessions);
      } catch (failure) {
        if (current && !controller.signal.aborted && isFirst) {
          setSessionError("Session evidence is unavailable. Performance totals remain available.");
        }
      }
    }

    void load(true);
    const interval = setInterval(() => {
      void load(false);
    }, 3000);

    return () => {
      current = false;
      controller.abort();
      clearInterval(interval);
    };
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
      {sessions && <div className="panel below">
        <PanelHeading title="Session evidence" as="h3" />
        <div className="session-table" role="region" aria-label="Session evidence table" tabIndex={0}>
        <table className="report-breakdown">
          <thead><tr>
            <th scope="col">Session</th><th scope="col">Detected</th><th scope="col">Closed</th>
            <th scope="col">Win rate before fees · 95% CI</th><th scope="col">Pips before fees</th><th scope="col">Evidence</th>
          </tr></thead>
          <tbody>{sessions.map(row => <tr key={row.session}>
            <th scope="row">{row.session}</th>
            <td>{row.detected}</td>
            <td>{row.closed}</td>
            <td>{row.win_rate === null ? "—" : `${row.win_rate}%`}
              {row.low !== null && <span className="muted"> ({row.low}–{row.high}%)</span>}</td>
            <td className={row.pips < 0 ? "warn" : row.pips > 0 ? "good" : ""}>
              {row.closed ? pipsFormat.format(row.pips) : "—"}</td>
            <td className="muted">{row.status}</td>
          </tr>)}</tbody>
        </table>
        </div>
        <p className="small muted">Historical simulated results before fees. These are not calibrated entry probabilities or a promise of an entry.</p>
      </div>}
      {sessionError && <p className="small muted" role="status">{sessionError}</p>}
    </>}
  </section>;
}
