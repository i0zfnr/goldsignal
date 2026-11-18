import { useEffect, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { Chart } from "./chart";
import { Access, ApiError, api } from "./access";
import { InstallButton } from "./install";
import type { Dashboard, Frame } from "./types";
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
const frames: Frame[] = ["M1", "M5", "M15", "M30", "H1", "H4"];
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
      !supported ? "Phone delivery requires a browser with Web Push on HTTPS." : "Opt in to receive shared entry and target updates."}</p>
    {message && <p role="status">{message}</p>}
    {data.alerts.length ? <ul className="rows">
      {data.alerts.slice(0, 6).map(alert => <li key={alert.id}><div><a href={alert.url}>{alert.title}</a>
        <p className="muted small">{alert.body}</p></div><span className="row-time">{displayTime(alert.time)}<small>{alert.delivery}</small></span></li>)}
    </ul> : <p className="muted">Shared entries and tracking updates appear here.</p>}
  </section>;
}

function App({ role, signOut, expired, settings }: {
  role: string | null; signOut: () => Promise<void>; expired: () => void; settings?: ReactNode;
}) {
  const page = settings ? "/admin" : "/";
  const [frame, setFrame] = useState<Frame>("M15");
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState(currentSignal);
  const cursor = useState(() => ({ frame: "M15" as Frame, revision: undefined as number | undefined }))[0];
  useEffect(() => {
    function change() { setSelected(currentSignal()); }
    addEventListener("popstate", change);
    return () => removeEventListener("popstate", change);
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    let timer = 0;
    async function poll() {
      const query = new URLSearchParams({ frame });
      if (cursor.frame === frame && cursor.revision !== undefined) query.set("after", String(cursor.revision));
      if (selected) query.set("signal", selected);
      try {
        const next = await api<Dashboard>(`/api/dashboard?${query}`, { signal: abort.signal });
        if (abort.signal.aborted) return;
        cursor.frame = frame;
        cursor.revision = next.revision;
        setData(next);
        setError("");
      } catch (failure) {
        if (failure instanceof ApiError && failure.status === 401 && !abort.signal.aborted) {
          expired();
          return;
        }
        if (!abort.signal.aborted) setError("Dashboard connection lost. Retrying…");
      }
      if (!abort.signal.aborted) timer = window.setTimeout(poll, 1000);
    }
    void poll();
    return () => { abort.abort(); clearTimeout(timer); };
  }, [selected, reload, cursor, expired, frame]);
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
  const pattern = data?.candidate?.evidence.pattern;
  return <>
    <header className="site-header"><div className="header-inner">
      <a className="wordmark" href={page} aria-label="Goldsignal dashboard"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
      <nav aria-label="Dashboard sections"><a href="#signal">Signal</a><a href="#history">History</a><a href="#alerts">Alerts</a></nav>
    </div></header>
    <main>
      {role !== "demo" && <div className="session-actions">
        <InstallButton />
        {role === "admin" && <a href={settings ? "#admin-settings" : "/admin"}>Admin settings</a>}
        <button type="button" onClick={() => void signOut()}>Sign out</button>
      </div>}
      <div className="market-heading">
        <div><p className="instrument">GOLD / US DOLLAR</p><h1>{data?.symbol ?? "XAUUSD"} <span>M15</span></h1></div>
        <div className={`feed-state ${data?.status === "STALE" || error ? "warn" : ""}`}>
          <span className="status-dot" aria-hidden="true" />{error ? "STALE" : data?.status ?? "CONNECTING"}
        </div>
      </div>
      {error && <p className="connection" role="status">{error}</p>}
      <div className="session-strip">
        <div><span>Active sessions</span><strong>{session ? session.open ? session.active?.join(" + ") || "Open" : "Closed" : "Waiting for worker"}</strong></div>
        <div><span>{session?.open ? "Entry cutoff" : session?.next?.length ? `Next · ${session.next.join(" + ")}` : "Next opening"}</span><strong>{session?.next_myt ? `${displayTime(session.open ? session.cutoff : session.opening)} MYT` : "–"}</strong></div>
        <div><span>{data?.mode === "demo" ? "Replay clock" : "Last quote"}</span><strong>{data?.quote ? `${displayTime(data.quote.time)} MYT` : "–"}</strong></div>
      </div>
      <div className="workspace">
        <section className="panel chart-panel" aria-labelledby="chart-title">
          <div className="chart-header">
            <div><h2 id="chart-title">Price chart</h2><span className="muted small">{frame} candles · UTC</span></div>
            <div className="quote"><div><span>Bid</span><strong>{price(data?.quote?.bid)}</strong></div><div><span>Ask</span><strong>{price(data?.quote?.ask)}</strong></div></div>
          </div>
          <div className="chart-frames" role="group" aria-label="Chart timeframe">
            {frames.map(value => <button key={value} type="button" aria-pressed={frame === value} onClick={() => {
              if (value !== frame) {
                cursor.revision = undefined;
                setFrame(value);
              }
            }}>{value}</button>)}
          </div>
          <Chart key={frame} frame={frame} candles={data?.frame === frame ? data.candles : []} signal={signal ?? null}
            quote={!error && ["LIVE", "DEMO"].includes(data?.status ?? "") ? data?.quote ?? null : null} />
          <div className="chart-footer"><span><i className="key entry" /> Entry zone</span><span><i className="key stop" /> Stop</span><span><i className="key target" /> Targets</span></div>
        </section>
        <div className="side">
          <section className="panel side-card signal" id="signal" aria-labelledby="signal-title">
            <div className="panel-heading"><h2 id="signal-title">{selected ? "Selected signal" : "Latest signal"}</h2>
              {signal && <span className={signal.direction === "SELL" ? "warn" : "good"}>{signal.direction} · {signal.status}</span>}
            </div>
            {selected && <a className="small" href={`${page}#signal`} onClick={event => select(event, null)}>Back to latest signal</a>}
            {signal ? <>
              <div className="entry-value"><span>Entry zone</span><strong>{price(signal.entry[0])}–{price(signal.entry[1])}</strong></div>
              <dl className="levels"><div><dt>Current SL</dt><dd className="warn">{price(signal.stop)}</dd></div>
                {signal.targets.map((target, i) => <div key={target}><dt>TP{i + 1}{signal.hits > i ? " ✓" : ""}</dt><dd className="good">{price(target)} <small>{Math.round(Math.abs(target - signal.reference) / 0.10)} pips</small></dd></div>)}
              </dl>
              <p className="small muted">Initial SL {price(signal.initial_stop)} · Fill {price(signal.fill)}
                {signal.hits === 1 && signal.fill !== signal.reference ? " · Stop moved to reference" : ""}</p>
              <p className="reason"><strong>{signal.evidence.grade}</strong> · {signal.evidence.reason}</p>
              {signal.review?.provider === "gemini" && <p className="small"><strong>Gemini</strong> · {signal.review.reason}</p>}
              <p className="small muted">Published {displayTime(signal.created)} · Entry expiry {displayTime(signal.expiry)} MYT</p>
            </> : <p className="muted">{selected ? "Signal unavailable." : "Waiting for a confirmed setup."}</p>}
            {data?.scan && <p className="gate">{data.scan.reason}{data.scan.closed_at && <span className="muted"> · M15 close {displayTime(data.scan.closed_at)} MYT</span>}</p>}
            {data?.candidate && <p className="gate">Last candidate · <strong>{data.candidate.decision}</strong> · {data.candidate.reason}</p>}
            {pattern && <p className="small muted">M15 RSI(8) {pattern.rsi8 ?? "unavailable"} · {pattern.history.toLocaleString()} historical candles · {pattern.matches} nearest matches</p>}
          </section>
          <section className="panel below" id="history" aria-labelledby="history-title">
            <div className="panel-heading"><h2 id="history-title">Signal history</h2><span className="muted small">Simulated execution</span></div>
            {data?.history.length ? <ul className="rows">{data.history.map(item =>
              <li key={item.id}><div><a href={`${page}?signal=${item.id}#signal`} onClick={event => select(event, item.id)}>{item.direction} · {price(item.reference)}</a>
                <p className="muted small">{displayTime(item.created)} MYT</p></div><span>{item.status}</span></li>)}</ul> : <p className="muted">No signals saved yet.</p>}
            <details><summary>Lifecycle and comparison</summary>
              {data?.events.map(event => <p className="small" key={event.id}>{displayTime(event.time)} MYT · {event.kind} · SL {price(event.stop)}{event.note ? ` · ${event.note}` : ""}</p>)}
              {data && (["with_news", "without_news"] as const).map(key => {
                const row = data.metrics[key];
                return <p className="small muted" key={key}>{key === "with_news" ? "With news" : "Without news"} · {row.fills}/{row.entries} filled · {row.tp1}/{row.fills} reached TP1 · {price(row.result)} simulated P/L per lot</p>;
              })}
            </details>
          </section>
          {data && <Alerts data={data} reload={refresh} />}
        </div>
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
      </div>
      {settings}
    </main>
    <footer><a href="https://www.tradingview.com/">TradingView Lightweight Charts™</a> · <a href="/NOTICE">Attribution notice</a></footer>
  </>;
}

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register("/sw.js").catch(() => {});
}

createRoot(document.getElementById("root")!).render(<Access
  dashboard={(role, signOut, expired, settings) => <App role={role} signOut={signOut} expired={expired} settings={settings} />} />);
