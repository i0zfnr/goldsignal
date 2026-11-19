import { useState, type FormEvent } from "react";
import { api } from "./access";
import { PanelHeading } from "./ui";

type Result = {
  lot: number; risk_cash: number; loss_per_lot: number; loss_per_lot_unit: number;
  stop_price: number; pips: number; min_capital: number; margin: number | null;
  minimum: number; step: number; maximum: number; spec_source: string; warnings: string[];
};

const money = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const risks = [0.5, 1, 2, 5];

export function LotSize() {
  const [capital, setCapital] = useState("100");
  const [risk, setRisk] = useState("1");
  const [pips, setPips] = useState("10");
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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

  const size = (value?: number | null) => value == null ? "–" : money.format(value);

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
  </section>;
}
