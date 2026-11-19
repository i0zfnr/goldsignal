import { useState, type FormEvent, useEffect } from "react";
import { api } from "./access";
import { PanelHeading, Badge } from "./ui";
import { ChevronLeft, ChevronRight, Plus, Trash2 } from "lucide-react";

type Result = {
  lot: number; risk_cash: number; loss_per_lot: number; loss_per_lot_unit: number;
  stop_price: number; pips: number; min_capital: number; margin: number | null;
  minimum: number; step: number; maximum: number; spec_source: string; warnings: string[];
};

type PnLEntry = { date: string; pnl: number; trades: number; note?: string | null };
type PnLResponse = { month: string; entries: PnLEntry[]; total_pnl: number; total_trades: number };

const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const risks = [0.5, 1, 2, 5];
const monthFormat = new Intl.DateTimeFormat("en-US", { month: "long", year: "numeric" });

export function LotSize() {
  const [capital, setCapital] = useState("100");
  const [risk, setRisk] = useState("1");
  const [pips, setPips] = useState("10");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const [pnlMonth, setPnlMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [pnlData, setPnlData] = useState<PnLResponse | null>(null);
  const [pnlBusy, setPnlBusy] = useState(false);
  const [pnlError, setPnlError] = useState("");
  const [newDate, setNewDate] = useState("");
  const [newPnl, setNewPnl] = useState("");
  const [newTrades, setNewTrades] = useState("0");
  const [newNote, setNewNote] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setResult(await api<Result>("/api/lot-size", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ capital: Number(capital), risk_pct: Number(risk), stop_pips: Number(pips) }),
      }));
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadPnL(isInitial = false) {
    if (isInitial) setPnlBusy(true);
    try {
      setPnlData(await api<PnLResponse>(`/api/pnl?month=${pnlMonth}`));
      setPnlError("");
    } catch (failure) {
      if (isInitial) setPnlError((failure as Error).message);
    } finally {
      if (isInitial) setPnlBusy(false);
    }
  }

  useEffect(() => {
    void loadPnL(true);
    const interval = setInterval(() => void loadPnL(false), 3000);
    return () => clearInterval(interval);
  }, [pnlMonth]);

  async function changeMonth(delta: number) {
    const [y, m] = pnlMonth.split("-").map(Number);
    const date = new Date(y, m - 1 + delta, 1);
    setPnlMonth(date.toISOString().slice(0, 7));
  }

  async function addPnL(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newDate || !newPnl) return;
    setPnlBusy(true);
    setPnlError("");
    try {
      await api("/api/pnl", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          date: newDate,
          pnl: Number(newPnl),
          trades: Number(newTrades),
          note: newNote || undefined,
        }),
      });
      setNewDate("");
      setNewPnl("");
      setNewTrades("0");
      setNewNote("");
      await loadPnL();
    } catch (failure) {
      setPnlError((failure as Error).message);
    } finally {
      setPnlBusy(false);
    }
  }

  async function deletePnL(date: string) {
    if (!confirm("Delete this PnL entry?")) return;
    setPnlBusy(true);
    try {
      await api(`/api/pnl?date=${date}`, { method: "DELETE" });
      await loadPnL();
    } catch (failure) {
      setPnlError((failure as Error).message);
    } finally {
      setPnlBusy(false);
    }
  }

  const size = (value?: number | null) => value == null ? "–" : money.format(value);

  const daysInMonth = (year: number, month: number) => new Date(year, month, 0).getDate();
  const [year, month] = pnlMonth.split("-").map(Number);
  const firstDay = new Date(year, month - 1, 1).getDay();
  const numDays = daysInMonth(year, month);
  const pnlMap = new Map(pnlData?.entries.map(e => [e.date, e]) ?? []);
  const todayStr = new Date().toISOString().slice(0, 10);

  return <section className="panel below lot-size" aria-labelledby="lot-size-title">
    <PanelHeading id="lot-size-title" title="Lot size calculator">
      {result && <span className="small muted">{result.spec_source === "live" ? "Broker spec" : "Default spec"}</span>}
    </PanelHeading>
    <p className="muted small">Position size from your own capital, risk and stop distance. Uses the broker&apos;s 0.01 step and 100 oz contract. This is a calculator, not a trade recommendation.</p>
    <form className="access-form lot-form" onSubmit={submit}>
      <label>Account capital (USD)
        <input type="number" min="1" step="1" value={capital} onChange={event => setCapital(event.target.value)} required />
      </label>
      <label>Risk per trade
        <select value={risk} onChange={event => setRisk(event.target.value)}>
          {risks.map(value => <option key={value} value={value}>{value}%</option>)}
        </select>
      </label>
      <label>Stop distance (pips)
        <input type="number" min="0.1" step="0.1" value={pips} onChange={event => setPips(event.target.value)} required />
      </label>
      <button className="primary" type="submit" disabled={busy}>{busy ? "Calculating…" : "Calculate lot size"}</button>
    </form>
    {error && <p className="warn" role="alert">{error}</p>}
    {result && <>
      <div className="lot-result">
        <span>Recommended lot size</span>
        <strong className={result.lot ? "" : "warn"}>{result.lot ? result.lot.toFixed(2) : "0.00"}</strong>
        <small>{result.lot
          ? `Risking $${money.format(result.loss_per_lot)} on ${result.pips} pips`
          : "Below broker minimum at this capital"}</small>
      </div>
      <dl className="report-stats lot-stats">
        <div><dt>Risk budget</dt><dd>${money.format(result.risk_cash)}</dd></div>
        <div><dt>Stop price distance</dt><dd>{result.stop_price.toFixed(2)}</dd></div>
        <div><dt>Loss per lot</dt><dd>${money.format(result.loss_per_lot_unit)}</dd></div>
        <div><dt>Margin estimate</dt><dd>{size(result.margin)}</dd></div>
        <div><dt>Minimum capital</dt><dd>${money.format(result.min_capital)}</dd></div>
        <div><dt>Broker limits</dt><dd>{result.minimum}–{result.maximum} / step {result.step}</dd></div>
      </dl>
      {result.warnings.map(message => <p className="small warn" key={message}>{message}</p>)}
      <p className="small muted">1 pip here = 0.10 price. For XAUUSD at 0.01 lot, 1.00 price move = $1.00.</p>
    </>}

    <hr style={{ margin: "24px 0" }} />
    <PanelHeading title="PnL Calendar" as="h3" />
    <div className="pnl-calendar">
      <div className="pnl-month-nav">
        <button onClick={() => changeMonth(-1)} disabled={pnlBusy} aria-label="Previous month"><ChevronLeft size={20} /></button>
        <span className="pnl-month-title">{monthFormat.format(new Date(year, month - 1, 1))}</span>
        <button onClick={() => changeMonth(1)} disabled={pnlBusy} aria-label="Next month"><ChevronRight size={20} /></button>
      </div>
      {pnlError && <p className="warn small" role="alert">{pnlError}</p>}
      {pnlData && (
        <div className="pnl-month-summary" style={{ marginBottom: 12, padding: 12, background: "var(--raised)", borderRadius: 8 }}>
          <div><strong>Month PnL:</strong> <span className={pnlData.total_pnl < 0 ? "warn" : "good"}>${money.format(pnlData.total_pnl)}</span></div>
          <div><strong>Total trades:</strong> {pnlData.total_trades}</div>
        </div>
      )}
      <table className="pnl-calendar-grid" role="grid" aria-label={`PnL calendar for ${pnlMonth}`}>
        <thead>
          <tr>{["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => <th key={d} scope="col">{d}</th>)}</tr>
        </thead>
        <tbody>
          {Array.from({ length: Math.ceil((firstDay + numDays) / 7) }, (_, week) => (
            <tr key={week}>
              {Array.from({ length: 7 }, (_, dayOfWeek) => {
                const dayIndex = week * 7 + dayOfWeek;
                const day = dayIndex - firstDay + 1;
                if (day < 1 || day > numDays) return <td key={dayIndex} className="empty" />;
                const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
                const entry = pnlMap.get(dateStr);
                const isToday = dateStr === todayStr;
                return (
                  <td key={dayIndex} className={isToday ? "today" : ""}>
                    <span className="day-number">{day}</span>
                    {entry && (
                      <div className="pnl-entry" style={{ background: entry.pnl < 0 ? "rgba(239,68,68,0.1)" : "rgba(34,197,94,0.1)" }}>
                        <span className={entry.pnl < 0 ? "warn" : "good"}>${money.format(entry.pnl)}</span>
                        {entry.trades && <span className="small muted"> · {entry.trades} trade{entry.trades !== 1 ? "s" : ""}</span>}
                        {entry.note && <span className="small muted" title={entry.note}> · {entry.note.slice(0, 12)}…</span>}
                        <button className="tiny" onClick={() => deletePnL(dateStr)} aria-label="Delete"><Trash2 size={10} /></button>
                      </div>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      <form className="pnl-add-form" onSubmit={addPnL} style={{ marginTop: 16, display: "grid", gridTemplateColumns: "auto auto auto 1fr auto", gap: 8, alignItems: "end" }}>
        <label className="small">Date<input type="date" value={newDate} onChange={e => setNewDate(e.target.value)} required max={todayStr} /></label>
        <label className="small">PnL ($)<input type="number" step="0.01" value={newPnl} onChange={e => setNewPnl(e.target.value)} placeholder="e.g. 12.50" required /></label>
        <label className="small">Trades<input type="number" step="1" min="0" value={newTrades} onChange={e => setNewTrades(e.target.value)} /></label>
        <label className="small">Note<input type="text" value={newNote} onChange={e => setNewNote(e.target.value)} placeholder="Optional note" /></label>
        <button className="primary" type="submit" disabled={pnlBusy}><Plus size={16} /> Add</button>
      </form>
    </div>
  </section>;
}
