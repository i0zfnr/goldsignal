import { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import { Chart } from "./chart";
import type { Dashboard, Profile } from "./types";
import "@fontsource/geist/latin-400.css";
import "@fontsource/geist/latin-600.css";
import "@fontsource/geist/latin-700.css";
import "./style.css";

const number = new Intl.NumberFormat("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const myt = new Intl.DateTimeFormat("en-MY", {
  timeZone: "Asia/Kuala_Lumpur", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const displayTime = (ts: number) => myt.format(ts * 1000);
const price = (value?: number | null) => value == null ? "–" : number.format(value);
const currentSignal = () => new URLSearchParams(location.search).get("signal");
const defaultProfile = (symbol: string): Profile => ({
  symbol, equity: 100, free_margin: 100, currency: "USD", units_per_currency: 1,
  risk_pct: 1, daily_loss_pct: 3, exit_policy: "split",
});

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "Request failed. Check the values and try again.");
  }
  return response.json();
}

function Account({ data, reload }: { data: Dashboard; reload: () => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const profile = data.profile ?? defaultProfile(data.symbol);
  const profileKey = [profile.equity, profile.free_margin, profile.currency, profile.symbol,
    profile.risk_pct, profile.daily_loss_pct, profile.units_per_currency, profile.exit_policy].join("|");
  const fit = data.fit;
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const payload = Object.fromEntries(form);
    const inputs = ["equity", "free_margin", "risk_pct", "daily_loss_pct", "units_per_currency"];
    for (const name of inputs) Object.assign(payload, { [name]: Number(form.get(name)) });
    setBusy(true);
    try {
      await api("/api/profile", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      setMessage("Profile saved.");
      reload();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel side-card" id="account" aria-labelledby="account-title">
    <div className="panel-heading"><h2 id="account-title">Account fit</h2>
      {fit && <span className={fit.decision === "FIT" ? "good" : "warn"}>{fit.decision === "FIT" ? "FIT" : "SKIP FOR THIS ACCOUNT"}</span>}
    </div>
    <p className="muted">{fit?.reason ?? "Waiting for a signal to estimate risk."}</p>
    {fit?.budget != null && <dl className="metrics">
      <div><dt>Risk budget</dt><dd>{price(fit.budget)} <small>{fit.currency}</small></dd></div>
      <div><dt>Minimum lot</dt><dd>{price(fit.minimum)}</dd></div>
      <div><dt>Est. stop loss</dt><dd>{price(fit.loss)} <small>{fit.currency} · {price(fit.loss_pct)}%</small></dd></div>
      <div><dt>Est. margin</dt><dd>{price(fit.margin)} <small>{fit.currency}</small></dd></div>
      {fit.lot != null && <div><dt>Proposed size</dt><dd>{price(fit.lot)} <small>lots</small></dd></div>}
    </dl>}
    {fit?.minimum_before_cost != null && <p className="small muted">Minimum-lot stop loss before costs {price(fit.minimum_before_cost)} {fit.currency}.</p>}
    <p className="muted small">Tracked daily P/L {price(data.daily)} {profile.currency}. Includes simulated exits tied to this profile.</p>
    <details>
      <summary>Edit account profile</summary>
      <form key={profileKey} onSubmit={save}>
        <div className="fields">
          <label>Equity<input name="equity" type="number" min="0.01" step="any" required defaultValue={profile.equity} /></label>
          <label>Free margin<input name="free_margin" type="number" min="0" step="any" required defaultValue={profile.free_margin} /></label>
          <label>Currency<input name="currency" required pattern="[A-Z]{3}" maxLength={3} defaultValue={profile.currency} /></label>
          <label>Broker symbol<input name="symbol" required maxLength={50} defaultValue={profile.symbol} /></label>
          <label>Risk cap (%)<input name="risk_pct" type="number" min="0.01" max="100" step="any" required defaultValue={profile.risk_pct} /></label>
          <label>Daily loss limit (%)<input name="daily_loss_pct" type="number" min="0.01" max="100" step="any" required defaultValue={profile.daily_loss_pct} /></label>
          <label>Account units<select name="units_per_currency" defaultValue={profile.units_per_currency}><option value="1">Standard</option><option value="100">Cent account</option></select></label>
          <label>Exit policy<select name="exit_policy" defaultValue={profile.exit_policy}><option value="split">TP1–TP3</option>{data.mode === "demo" && <option value="single">TP1 only</option>}</select></label>
        </div>
        <button className="primary" type="submit" disabled={busy}>Save profile</button>
        <p role="status" className="small">{message}</p>
      </form>
    </details>
  </section>;
}

function Alerts({ data, reload }: { data: Dashboard; reload: () => void }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && window.isSecureContext;
  async function toggle() {
    setBusy(true);
    try {
      if (!data.push_enabled && await Notification.requestPermission() !== "granted") {
        throw new Error("Notification permission is blocked.");
      }
      const registration = await navigator.serviceWorker.register("/sw.js");
      if (data.push_enabled) {
        await api("/api/push", { method: "DELETE" });
        await (await registration.pushManager.getSubscription())?.unsubscribe();
        setMessage("Phone alerts disabled.");
      } else {
        const ready = await navigator.serviceWorker.ready;
        const encoded = data.push_key!.replaceAll("-", "+").replaceAll("_", "/");
        const key = Uint8Array.from(atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, "=")), ch => ch.charCodeAt(0));
        const existing = await ready.pushManager.getSubscription();
        const subscription = existing ?? await ready.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
        try {
          await api("/api/push", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(subscription) });
        } catch (error) {
          if (!existing) await subscription.unsubscribe();
          throw error;
        }
        setMessage("Phone alerts enabled.");
      }
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
      reload();
    }
  }
  return <section id="alerts" className="panel below" aria-labelledby="alerts-title">
    <div className="panel-heading"><h2 id="alerts-title">Alert preview</h2>
      {data.push_key && supported && <button disabled={busy} onClick={() => void toggle()}>{data.push_enabled ? "Disable phone alerts" : "Enable phone alerts"}</button>}
    </div>
    <p className="muted small">{!data.push_key ? "Phone delivery requires HTTPS and Web Push keys." :
      !supported ? "Phone delivery requires a browser with Web Push on HTTPS." : "Save an account profile before enabling phone alerts."}</p>
    {message && <p role="status">{message}</p>}
    {data.alerts.length ? <ul className="rows">
      {data.alerts.slice(0, 6).map(alert => <li key={alert.id}><div><a href={alert.url}>{alert.title}</a>
        <p className="muted small">{alert.body}</p></div><span className="row-time">{displayTime(alert.time)}<small>{alert.delivery}</small></span></li>)}
    </ul> : <p className="muted">Eligible entries and tracking updates appear here.</p>}
  </section>;
}

function App() {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState(currentSignal);
  const cursor = useState(() => ({ revision: undefined as number | undefined }))[0];
  useEffect(() => {
    function change() { setSelected(currentSignal()); }
    addEventListener("popstate", change);
    return () => removeEventListener("popstate", change);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    let timer = 0;
    async function poll() {
      const query = new URLSearchParams();
      if (cursor.revision !== undefined) query.set("after", String(cursor.revision));
      if (selected) query.set("signal", selected);
      try {
        const next = await api<Dashboard>(`/api/dashboard?${query}`, { signal: abort.signal });
        if (abort.signal.aborted) return;
        cursor.revision = next.revision;
        setData(next);
        setError("");
      } catch {
        if (!abort.signal.aborted) setError("Dashboard connection lost. Retrying…");
      }
      if (!abort.signal.aborted) timer = window.setTimeout(poll, 2000);
    }
    void poll();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [selected, reload, cursor]);
  function refresh() { setReload(value => value + 1); }
  function select(event: React.MouseEvent<HTMLAnchorElement>, id: string | null) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.pushState(null, "", event.currentTarget.href);
    setSelected(id);
    document.getElementById("signal")?.scrollIntoView();
  }
  const signal = data?.active;
  const session = data?.session;
  return <>
    <header className="site-header"><div className="header-inner">
      <a className="wordmark" href="/" aria-label="Goldsignal dashboard"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
      <nav aria-label="Dashboard sections"><a href="#signal">Signal</a><a href="#history">History</a><a href="#alerts">Alerts</a></nav>
    </div></header>
    <main>
      <div className="market-heading">
        <div><p className="instrument">GOLD / US DOLLAR</p><h1>{data?.symbol ?? "XAUUSD"} <span>M15</span></h1></div>
        <div className={`feed-state ${data?.status === "STALE" || error ? "warn" : ""}`}>
          <span className="status-dot" aria-hidden="true" />{error ? "STALE" : data?.status ?? "CONNECTING"}
        </div>
      </div>
      {error && <p className="connection" role="status">{error}</p>}
      <div className="session-strip">
        <div><span>US entries</span><strong>{session ? session.open ? "Window open" : "Window closed" : "Waiting for worker"}</strong></div>
        <div><span>{session?.open ? "Cutoff" : "Next opening"}</span><strong>{session?.next_myt ? `${displayTime(session.open ? session.cutoff : session.opening)} MYT` : "–"}</strong></div>
        <div><span>{data?.mode === "demo" ? "Replay clock" : "Last quote"}</span><strong>{data?.quote ? `${displayTime(data.quote.time)} MYT` : "–"}</strong></div>
      </div>
      <div className="workspace">
        <section className="panel chart-panel" aria-labelledby="chart-title">
          <div className="chart-header">
            <div><h2 id="chart-title">Price chart</h2><span className="muted small">15-minute candles · UTC</span></div>
            <div className="quote"><div><span>Bid</span><strong>{price(data?.quote?.bid)}</strong></div><div><span>Ask</span><strong>{price(data?.quote?.ask)}</strong></div></div>
          </div>
          <Chart candles={data?.candles ?? []} signal={signal ?? null} />
          <div className="chart-footer"><span><i className="key entry" /> Entry zone</span><span><i className="key stop" /> Stop</span><span><i className="key target" /> Targets</span></div>
        </section>
        <div className="side">
          <section className="panel side-card signal" id="signal" aria-labelledby="signal-title">
            <div className="panel-heading"><h2 id="signal-title">{selected ? "Selected signal" : "Latest signal"}</h2>
              {signal && <span className={signal.direction === "SELL" ? "warn" : "good"}>{signal.direction} · {signal.status}</span>}
            </div>
            {selected && <a className="small" href="/#signal" onClick={event => select(event, null)}>Back to latest signal</a>}
            {signal ? <>
              <div className="entry-value"><span>Entry zone</span><strong>{price(signal.entry[0])}–{price(signal.entry[1])}</strong></div>
              <dl className="levels"><div><dt>Current SL</dt><dd className="warn">{price(signal.stop)}</dd></div>
                {signal.targets.map((target, i) => <div key={target}><dt>TP{i + 1}{signal.hits > i ? " ✓" : ""}</dt><dd className="good">{price(target)} <small>{Math.round(Math.abs(target - signal.reference) / 0.10)} pips</small></dd></div>)}
              </dl>
              <p className="small muted">Initial SL {price(signal.initial_stop)} · Fill {price(signal.fill)}
                {signal.hits === 1 && signal.fill !== signal.reference ? " · Stop moved to reference" : ""}</p>
              <p className="reason"><strong>{signal.evidence.grade}</strong> · {signal.evidence.reason}</p>
              <p className="small muted">Published {displayTime(signal.created)} · Entry expiry {displayTime(signal.expiry)} MYT</p>
            </> : <p className="muted">{selected ? "Signal unavailable." : "Waiting for a confirmed setup."}</p>}
            {data?.candidate && <p className="gate">Latest review · <strong>{data.candidate.decision}</strong> · {data.candidate.reason}</p>}
          </section>
          {data && <Account data={data} reload={refresh} />}
        </div>
      </div>
      <div className="lower">
        <section className="panel below" id="history" aria-labelledby="history-title">
          <div className="panel-heading"><h2 id="history-title">Signal history</h2><span className="muted small">Simulated execution</span></div>
          {data?.history.length ? <ul className="rows">{data.history.map(item =>
            <li key={item.id}><div><a href={`/?signal=${item.id}#signal`} onClick={event => select(event, item.id)}>{item.direction} · {price(item.reference)}</a>
              <p className="muted small">{displayTime(item.created)} MYT</p></div><span>{item.status}</span></li>)}</ul> : <p className="muted">No signals saved yet.</p>}
          <details><summary>Lifecycle and comparison</summary>
            {data?.events.map(event => <p className="small" key={event.id}>{displayTime(event.time)} MYT · {event.kind} · SL {price(event.stop)}{event.note ? ` · ${event.note}` : ""}</p>)}
            {data && (["with_news", "without_news"] as const).map(key => {
              const row = data.metrics[key];
              return <p className="small muted" key={key}>{key === "with_news" ? "With news" : "Without news"} · {row.fills}/{row.entries} filled · {row.tp1}/{row.fills} reached TP1 · {price(row.result)} simulated P/L per lot</p>;
            })}
          </details>
        </section>
        <section className="panel below" id="news" aria-labelledby="news-title">
          <div className="panel-heading"><h2 id="news-title">USD calendar</h2><span className="muted small">{data?.mode === "demo" ? "Mock feed" : "Official sources"}</span></div>
          {data?.calendar.restriction && <p className="warn">{data.calendar.restriction}</p>}
          {data?.calendar.events?.length ? <ul className="rows">{data.calendar.events.map(event =>
            <li key={`${event.source}-${event.time}-${event.title}`}><div>{event.url ? <a href={event.url}>{event.title}</a> : event.title}
              <p className="muted small">{event.source}
                {(["actual", "forecast", "previous"] as const).filter(key => event[key] != null).map(key => ` · ${key} ${event[key]}`)}</p></div>
              <span className="row-time">{displayTime(event.time)}<small>MYT</small></span></li>)}</ul> : <p className="muted">No upcoming releases loaded.</p>}
          <details><summary>Headlines and feed freshness</summary>
            {Object.entries(data?.calendar.sources ?? {}).map(([source, ts]) => <p key={source} className="small">{source} · refreshed {displayTime(ts)} MYT</p>)}
            {Object.entries(data?.calendar.errors ?? {}).map(([source, reason]) => <p key={source} className="small warn">{source} · {reason}</p>)}
            {data?.calendar.headlines?.slice(0, 5).map(item => <p className="small" key={`${item.source}-${item.title}`}>
              {item.url ? <a href={item.url}>{item.title}</a> : item.title} · {displayTime(item.time)} MYT</p>)}
          </details>
        </section>
        {data && <Alerts data={data} reload={refresh} />}
      </div>
    </main>
    <footer><a href="https://www.tradingview.com/">TradingView Lightweight Charts™</a> · <a href="/NOTICE">Attribution notice</a></footer>
  </>;
}

createRoot(document.getElementById("root")!).render(<App />);
