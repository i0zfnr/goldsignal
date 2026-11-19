import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { Bell, CalendarDays, ChartCandlestick, ChartNoAxesCombined, CircleAlert, History, Menu, MessageSquare, Settings2, Upload, UserRound, Users, X } from "lucide-react";
import { Chart } from "./chart";
import { Performance } from "./performance";
import { Access, AdminSettings, adminViews, ApiError, api, type AdminView } from "./access";
import { InstallButton } from "./install";
import { CandleClock } from "./candle-clock";
import type { Dashboard, EntryCheck, Frame } from "./types";
import { applyTheme, readTheme, ThemeToggle } from "./theme";
import { Badge, EmptyState, LoadingState, PanelHeading } from "./ui";
import "@fontsource/geist/latin-400.css";
import "@fontsource/geist/latin-500.css";
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
const dashboardViews = [
  ["signal", "Live dashboard"],
  ["performance", "Performance"],
  ["history", "Signal History"],
  ["news", "USD Calendar"],
  ["alerts", "Notifications"],
] as const;
type DashboardView = typeof dashboardViews[number][0] | AdminView | "profile";
const viewIcons = {
  signal: ChartCandlestick, performance: ChartNoAxesCombined, history: History, news: CalendarDays,
  alerts: Bell, profile: UserRound, "admin-users": Users, "admin-ai": Settings2,
  "admin-chat": MessageSquare, "admin-errors": CircleAlert,
};

function currentView(isAdmin: boolean): DashboardView {
  const hash = location.hash.slice(1);
  if (isAdmin) {
    const adminView = adminViews.find(([id]) => id === hash)?.[0];
    if (adminView) return adminView;
    if (hash === "admin-settings") return "admin-users";
  }
  if (hash === "profile") return hash;
  return dashboardViews.find(([id]) => hash === id)?.[0] ??
    (isAdmin && location.pathname === "/admin" && !currentSignal() ? "admin-users" : "signal");
}
type PushStatus = { enabled: boolean; test: "queued" | "sent" | "failed" | "expired" | null };
type ViewerProfile = { display_name: string; role: string; photo: string | null };

async function resizeProfilePhoto(file: File) {
  if (file.size > 12 * 1024 * 1024) throw new Error("Choose a photo smaller than 12 MB.");
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 96;
    const context = canvas.getContext("2d");
    if (!context || !image.naturalWidth || !image.naturalHeight) throw new Error("Could not read this photo.");
    const size = Math.min(image.naturalWidth, image.naturalHeight);
    context.drawImage(image, (image.naturalWidth - size) / 2, (image.naturalHeight - size) / 2, size, size, 0, 0, 96, 96);
    for (const quality of [0.83, 0.68, 0.50, 0.3]) {
      const photo = canvas.toDataURL("image/jpeg", quality);
      if (photo.startsWith("data:image/jpeg;base64,") && photo.length <= 7000) return photo;
    }
    throw new Error("Could not resize this photo.");
  } finally {
    URL.revokeObjectURL(url);
  }
}

function Profile() {
  const [profile, setProfile] = useState<ViewerProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    api<ViewerProfile>("/api/viewer-profile", { signal: abort.signal })
      .then(result => { if (!abort.signal.aborted) setProfile(result); })
      .catch(() => { if (!abort.signal.aborted) setMessage("Could not load your profile."); });
    return () => abort.abort();
  }, []);
  async function choosePhoto(input: HTMLInputElement) {
    const file = input.files?.[0];
    input.value = "";
    if (!file || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const photo = await resizeProfilePhoto(file);
      setProfile(previous => previous && { ...previous, photo });
    } catch {
      setMessage("Could not use this photo. Choose a readable image smaller than 12 MB.");
    } finally {
      setBusy(false);
    }
  }
  async function save(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile) return;
    setBusy(true);
    setMessage("");
    try {
      const saved = await api<ViewerProfile>("/api/viewer-profile", {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: profile.display_name, photo: profile.photo }),
      });
      setProfile(saved);
      setMessage("Profile saved.");
    } catch (failure) {
      setMessage((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <section className="panel below profile-panel" id="profile" aria-labelledby="profile-title">
    <PanelHeading id="profile-title" title="Profile">
      {profile && <Badge>{profile.role === "admin" ? "Admin" : "Viewer"}</Badge>}
    </PanelHeading>
    {profile ? <form className="profile-form" onSubmit={event => void save(event)}>
      <div className="profile-photo">
        {profile.photo ? <img src={profile.photo} width="64" height="64" alt="Your profile photo" /> :
          <span className="profile-photo-placeholder" aria-hidden="true">{profile.display_name.trim()[0]?.toUpperCase() || "G"}</span>}
        <label className="photo-picker">
          <input type="file" accept="image/*" disabled={busy} aria-label="Profile photo"
            onChange={event => void choosePhoto(event.currentTarget)} />
          <span aria-hidden="true"><Upload size={16} /> Choose photo</span>
        </label>
        {profile.photo && <button type="button" disabled={busy}
          onClick={() => { setProfile({ ...profile, photo: null }); setMessage(""); }}>Remove photo</button>}
      </div>
      <label>Display name<input value={profile.display_name} maxLength={60} autoComplete="nickname"
        disabled={busy} onChange={event => setProfile({ ...profile, display_name: event.target.value })} /></label>
      <button type="submit" className="primary" disabled={busy}>{busy ? "Saving…" : "Save profile"}</button>
    </form> : !message && <LoadingState>Loading profile…</LoadingState>}
    {message && <p role="status">{message}</p>}
  </section>;
}

function Alerts({ data }: { data: Dashboard }) {
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<PushStatus | null>(null);
  const supported = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window && window.isSecureContext;

  function deviceRequest<T>(path: string, method: string, endpoint: string) {
    return api<T>(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint }) });
  }

  async function check() {
    const registration = await navigator.serviceWorker.getRegistration();
    const subscription = await registration?.pushManager.getSubscription();
    const result = subscription && Notification.permission === "granted"
      ? await deviceRequest<PushStatus>("/api/push/status", "POST", subscription.endpoint)
      : { enabled: false, test: null };
    setStatus(result);
  }

  useEffect(() => {
    if (!supported || !data.push_key) return;
    const refresh = () => void check().catch(() => setMessage("Could not check notifications on this device."));
    refresh();
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [supported, data.push_key]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await work();
      await check();
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function toggle() {
    void action(async () => {
      if (!status?.enabled && await Notification.requestPermission() !== "granted") {
        throw new Error("Allow notifications for Goldsignal in your browser or device settings, then try again.");
      }
      const registration = await navigator.serviceWorker.register("/sw.js");
      if (status?.enabled) {
        const subscription = await registration.pushManager.getSubscription();
        if (subscription) {
          await deviceRequest("/api/push", "DELETE", subscription.endpoint);
          await subscription.unsubscribe();
        }
        setMessage("Notifications disabled on this device.");
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
        setMessage("Notifications enabled on this device.");
      }
    });
  }

  function sendTest() {
    void action(async () => {
      const subscription = await (await navigator.serviceWorker.getRegistration())?.pushManager.getSubscription();
      if (!subscription) throw new Error("Enable notifications on this device first.");
      await deviceRequest("/api/push/test", "POST", subscription.endpoint);
    });
  }
  return <section id="alerts" className="panel below" aria-labelledby="alerts-title">
    <PanelHeading id="alerts-title" title="Notifications">
      {data.push_key && supported && <button className={status?.enabled ? undefined : "primary"} disabled={busy} onClick={toggle}>{status?.enabled ? "Disable notifications" : "Enable notifications"}</button>}
    </PanelHeading>
    <p className="muted small">{!data.push_key ? "Phone delivery requires HTTPS and Web Push keys." :
      !supported ? "On iPhone or iPad, open Goldsignal from your Home Screen to enable notifications." :
        status?.enabled ? "This device is subscribed to entry and trade updates." : "Enable notifications on this device to receive entry and trade updates."}</p>
    {status?.enabled && <div className="push-actions">
      <button disabled={busy} onClick={sendTest}>Send test notification</button>
      <button disabled={busy} onClick={() => void action(async () => {})}>Check delivery</button>
    </div>}
    {status?.enabled && status.test && <p className="muted small" role="status">
      {status.test === "sent" ? "Push service accepted the test. Check this device for the notification." :
        status.test === "queued" ? "Test queued. Check delivery in a few seconds." : "Test delivery failed or expired. Check notification settings and try again."}
    </p>}
    {message && <p role="status">{message}</p>}
    {data.alerts.length ? <ul className="rows notification-rows">
      {data.alerts.slice(0, 6).map(alert => <li key={alert.id}>
        <span className="row-icon" aria-hidden="true"><Bell size={16} /></span>
        <div className="row-content"><a className="row-title" href={alert.url}>{alert.title}</a><p className="muted small">{alert.body}</p></div>
        <span className="row-time">{displayTime(alert.time)}<small>{alert.delivery}</small></span>
      </li>)}
    </ul> : <EmptyState icon={<Bell size={18} />}>Shared entries and tracking updates appear here.</EmptyState>}
  </section>;
}

function App({ role, signOut, expired }: {
  role: string | null; signOut: () => Promise<void>; expired: () => void;
}) {
  const page = location.pathname === "/admin" ? "/admin" : "/";
  const hasAdmin = role === "admin";
  const [view, setView] = useState(() => currentView(hasAdmin));
  const [menuOpen, setMenuOpen] = useState(false);
  const [frame, setFrame] = useState<Frame>(() => {
    const requested = new URLSearchParams(location.search).get("frame");
    return frames.find(value => value === requested) ?? "M15";
  });
  const [openedEntry, setOpenedEntry] = useState<{ signal: string; check: EntryCheck } | null>(null);
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(currentSignal);
  useEffect(() => {
    if (!selected || new URLSearchParams(location.search).get("alert") !== "1") return;
    let current = true;
    const query = new URLSearchParams({ signal: selected });
    const source = new URLSearchParams(location.search);
    for (const key of ["demo_alert", "demo_attempt"]) {
      const value = source.get(key);
      if (value) query.set(key, value);
    }
    navigator.serviceWorker?.controller?.postMessage({ type: "DEMO_FLUSH" });
    void api<EntryCheck>(`/api/entry-open?${query}`, { method: "POST" })
      .then(check => { if (current) setOpenedEntry({ signal: selected, check }); })
      .catch(() => {});
    return () => { current = false; };
  }, [selected]);
  const cursor = useState(() => ({
    frame: "M15" as Frame, revision: undefined as number | undefined,
    open: undefined as number | undefined, receivedAt: 0,
  }))[0];
  useEffect(() => {
    function change() {
      setSelected(currentSignal());
      setView(currentView(hasAdmin));
    }
    addEventListener("popstate", change);
    addEventListener("hashchange", change);
    return () => {
      removeEventListener("popstate", change);
      removeEventListener("hashchange", change);
    };
  }, [hasAdmin]);
  useEffect(() => {
    window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [view]);
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
        if (cursor.frame !== frame || cursor.revision === undefined) cursor.open = undefined;
        const latest = next.candles.at(-1)?.time;
        if (latest !== undefined && (cursor.open === undefined || latest > cursor.open)) cursor.open = latest;
        cursor.receivedAt = performance.now();
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
  }, [selected, cursor, expired, frame]);
  function select(event: React.MouseEvent<HTMLAnchorElement>, id: string | null) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.pushState(null, "", event.currentTarget.href);
    setSelected(id);
    setView("signal");
    window.scrollTo(0, 0);
  }
  const signal = data?.active;
  const entry = data?.entry_check;
  const session = data?.session;
  const candidate = data?.candidate;
  const pattern = candidate?.evidence.pattern;
  const viewLabel = [...dashboardViews, ...adminViews].find(([id]) => id === view)?.[1] ?? "Profile";
  const showNotificationSetup = !!data?.push_key && "Notification" in window &&
    (matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone) &&
    Notification.permission === "default";
  function viewLink(id: DashboardView, label: string) {
    const Icon = viewIcons[id];
    return <a key={id} href={id === "signal" ? `${page}#signal` : `#${id}`}
      aria-current={view === id ? "page" : undefined}
      onClick={event => {
        setMenuOpen(false);
        if (id === "signal") select(event, null);
      }}><Icon size={20} strokeWidth={1.7} aria-hidden="true" />{label}</a>;
  }
  return <div className="dashboard-shell">
    <aside className="dashboard-sidebar" id="dashboard-sidebar" data-open={menuOpen}>
      <a className="wordmark" href={`${page}#signal`} onClick={event => select(event, null)} aria-label="Goldsignal dashboard"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
      <h2 className="nav-group-label">Menu</h2>
      <nav aria-label="Dashboard sections">
        {dashboardViews.map(([id, label]) => viewLink(id, label))}
        {role !== "demo" && viewLink("profile", "Profile")}
      </nav>
      {hasAdmin && <div className="admin-nav-group">
        <h2 id="admin-nav-title">Admin</h2>
        <nav aria-labelledby="admin-nav-title">{adminViews.map(([id, label]) => viewLink(id, label))}</nav>
      </div>}
      {role !== "demo" && <button className="sidebar-sign-out" type="button" onClick={() => void signOut()}>Sign out</button>}
    </aside>
    <header className="dashboard-toolbar">
      <span className="toolbar-context" aria-hidden="true">{viewLabel}</span>
      <button className="toolbar-icon mobile-menu" type="button" aria-label={menuOpen ? "Close navigation" : "Open navigation"}
        aria-controls="dashboard-sidebar" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}>
        {menuOpen ? <X size={20} aria-hidden="true" /> : <Menu size={20} aria-hidden="true" />}
      </button>
      <a className="wordmark toolbar-brand" href={`${page}#signal`} onClick={event => select(event, null)}
        aria-label="Goldsignal dashboard"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
      <div className="toolbar-actions">
        <ThemeToggle />
        <a className="toolbar-icon" href="#alerts" aria-label="Notifications"><Bell size={19} aria-hidden="true" /></a>
        {role !== "demo" && <>
          <a className="toolbar-icon desktop-profile" href="#profile" aria-label="Profile"><UserRound size={19} aria-hidden="true" /></a>
          <button className="desktop-sign-out" type="button" onClick={() => void signOut()}>Sign out</button>
        </>}
      </div>
    </header>
    <main className="dashboard-main">
      {role !== "demo" && <div className="session-actions">
        <InstallButton />
        {showNotificationSetup && <a href="#alerts">Set up notifications</a>}
      </div>}
      <div hidden={view !== "signal"}>
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
          <section className="panel side-card signal" id="signal" aria-labelledby="signal-title">
            <div className="panel-heading"><h2 id="signal-title">{selected ? "Selected signal" : "Live signal"}</h2>
              {signal && <Badge tone={signal.direction === "SELL" ? "negative" : "positive"}>{signal.direction} · {signal.status}</Badge>}
            </div>
            {selected && <a className="small" href={`${page}#signal`} onClick={event => select(event, null)}>Back to live signal</a>}
            {signal ? <>
              <p className="small muted">{signal.strategy ?? "M15 baseline"}</p>
              <div className="entry-value"><span>Entry zone</span><strong>{price(signal.entry[0])}–{price(signal.entry[1])}</strong></div>
              <dl className="levels"><div><dt>Current SL</dt><dd className="warn">{price(signal.stop)}</dd></div>
                {signal.targets.map((target, i) => <div key={target}><dt>TP{i + 1}{signal.hits > i ? " ✓" : ""}</dt><dd className="good">{price(target)} <small>{Math.round(Math.abs(target - signal.reference) / 0.10)} pips</small></dd></div>)}
              </dl>
              <p className="small muted">Initial SL {price(signal.initial_stop)} · Fill {price(signal.fill)}
                {signal.hits === 1 && signal.fill !== signal.reference ? " · Stop moved to reference" : ""}</p>
              <p className="reason"><strong>{signal.evidence.grade}</strong> · {signal.evidence.reason}</p>
              {signal.review?.provider === "gemini" && <p className="small"><strong>Gemini</strong> · {signal.review.reason}</p>}
              <p className="small muted">Published {displayTime(signal.created)} · Entry expiry {displayTime(signal.expiry)} MYT</p>
              {entry && <p className={entry.valid ? "good small" : "warn small"}>
                {entry.side} {price(entry.price)} · {entry.valid ? "Entry valid" : entry.reason}
              </p>}
              {entry?.ratios && <p className="small muted">Reward/risk before costs · {entry.ratios.map((ratio, i) => `TP${i + 1} ${ratio}R`).join(" · ")}</p>}
              {openedEntry?.signal === signal.id && <p className="small muted">
                At alert open · {openedEntry.check.side} {price(openedEntry.check.price)} · {openedEntry.check.valid ? "Valid" : openedEntry.check.reason}
              </p>}
            </> : <EmptyState icon={<ChartCandlestick size={18} />}>{selected ? "Signal unavailable." : "Waiting for signal"}</EmptyState>}
          </section>
        <section className="panel chart-panel" aria-labelledby="chart-title">
          <div className="chart-header">
            <div><h2 id="chart-title">Price chart</h2><span className="muted small">{frame} candles · UTC</span></div>
            <div className="quote">
              <div><span>Bid</span><strong>{price(data?.quote?.bid)}</strong></div>
              <div><span>Ask</span><strong>{price(data?.quote?.ask)}</strong></div>
              <CandleClock frame={frame} open={data?.frame === frame ? cursor.open : undefined}
                clock={data?.clock} receivedAt={cursor.receivedAt} status={error ? "STALE" : data?.status} />
            </div>
          </div>
          <div className="chart-frames segment-group" role="group" aria-label="Chart timeframe">
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
          <section className="panel side-card insight" id="insight" aria-labelledby="insight-title">
            <div className="panel-heading"><h2 id="insight-title">AI Insight</h2>
              <span className="muted">{error || data?.status === "STALE" ? "Feed stale" : data?.status === "LIVE" ? "Live scan" : data?.status === "DEMO" ? "Replay scan" : "Scanner"}</span>
            </div>
            <details className="insight-details" open={matchMedia("(min-width: 850px)").matches}><summary>What the scanner is watching</summary>
            {data?.scan && <p className="gate"><strong>M15 baseline</strong> · {data.scan.reason}{data.scan.closed_at && <span className="muted"> · Closed {displayTime(data.scan.closed_at)} MYT</span>}</p>}
            {data?.scalp_scan && <p className="gate"><strong>M5 setup / M1 entry</strong> · {data.scalp_scan}</p>}
            {candidate && <p className="gate">Last candidate · <strong>{candidate.decision}</strong> · {candidate.reason}
              {candidate.evaluated && <span className="muted"> · {displayTime(candidate.evaluated)} MYT</span>}</p>}
            {pattern && <p className="small muted">M15 RSI(8) {pattern.rsi8 ?? "unavailable"} · {pattern.history.toLocaleString()} historical candles · {pattern.matches} nearest matches</p>}
            {!data?.scan && !data?.scalp_scan && !candidate && <p className="small muted">Waiting for a scanner update.</p>}
            </details>
          </section>
      </div>
      </div>
      <div className="dashboard-view" hidden={view !== "performance"}>
        {data ? <Performance revision={data.history.map(item => `${item.id}:${item.status}`).join(",")} /> : <p role="status">Loading performance…</p>}
      </div>
      <div className="dashboard-view" hidden={view !== "history"}>
          <section className="panel below" id="history" aria-labelledby="history-title">
            <PanelHeading id="history-title" title="Signal history"><Badge>Simulated execution</Badge></PanelHeading>
            {data?.history.length ? <ul className="rows history-rows">{data.history.map(item =>
              <li key={item.id}>
                <Badge tone={item.direction === "BUY" ? "positive" : "negative"}>{item.direction}</Badge>
                <div className="row-content"><a className="row-title" href={`${page}?signal=${item.id}#signal`}
                  aria-label={`${item.direction} · ${price(item.reference)}`} onClick={event => select(event, item.id)}>{price(item.reference)}</a>
                  <p className="muted small">{item.strategy ?? "M15 baseline"} · {displayTime(item.created)} MYT</p></div>
                <Badge tone={item.status === "STOPPED" ? "negative" : item.status === "COMPLETED" ? "positive" : "neutral"}>{item.status}</Badge>
              </li>)}</ul> : <EmptyState icon={<History size={18} />}>No signals saved yet.</EmptyState>}
            <details><summary>Lifecycle and comparison</summary>
              {data?.events.map(event => <p className="small" key={event.id}>{displayTime(event.time)} MYT · {event.kind} · SL {price(event.stop)}{event.note ? ` · ${event.note}` : ""}</p>)}
              {data && (["with_news", "without_news"] as const).map(key => {
                const row = data.metrics[key];
                return <p className="small muted" key={key}>{key === "with_news" ? "With news" : "Without news"} · {row.fills}/{row.entries} filled · {row.tp1}/{row.fills} reached TP1 · {price(row.result)} simulated P/L per lot</p>;
              })}
            </details>
          </section>
      </div>
      <div className="dashboard-view" hidden={view !== "news"}>
        <section className="panel below" id="news" aria-labelledby="news-title">
          <PanelHeading id="news-title" title="USD calendar"><Badge>{data?.mode === "demo" ? "Mock feed" : "Official sources"}</Badge></PanelHeading>
          {data?.calendar.restriction && <p className="warn">{data.calendar.restriction}</p>}
          {data?.calendar.events?.length ? <ul className="rows calendar-rows">{data.calendar.events.map(event =>
            <li key={`${event.source}-${event.time}-${event.title}`}><div className="row-content">{event.url ? <a className="row-title" href={event.url}>{event.title}</a> : <span className="row-title">{event.title}</span>}
              <p className="row-meta"><span>{event.source}</span><Badge tone={event.impact === "medium" ? "neutral" : "accent"}>{event.impact === "medium" ? "Timing watch" : "Entry pause"}</Badge>
                {(["actual", "forecast", "previous"] as const).filter(key => event[key] != null).map(key => ` · ${key} ${event[key]}`)}</p></div>
              <span className="row-time">{displayTime(event.time)}<small>MYT</small></span></li>)}</ul> : <EmptyState icon={<CalendarDays size={18} />}>No upcoming releases loaded.</EmptyState>}
          <details><summary>Headlines and feed freshness</summary>
            {Object.entries(data?.calendar.sources ?? {}).map(([source, ts]) => <p key={source} className="small">{source} · refreshed {displayTime(ts)} MYT</p>)}
            {Object.entries(data?.calendar.errors ?? {}).map(([source, reason]) => <p key={source} className="small warn">{source} · {reason}</p>)}
            {data?.calendar.headlines?.slice(0, 5).map(item => <p className="small" key={`${item.source}-${item.title}`}>
              {item.url ? <a href={item.url}>{item.title}</a> : item.title} · {displayTime(item.time)} MYT</p>)}
          </details>
        </section>
      </div>
      <div className="dashboard-view" hidden={view !== "alerts" && view !== "profile"}>
        {view === "profile" && (role === "demo" ? <p className="muted">Sign in to manage a profile.</p> : <Profile />)}
        {data ? <Alerts data={data} /> : <p role="status">Loading notifications…</p>}
      </div>
      {hasAdmin && <AdminSettings view={adminViews.find(([id]) => id === view)?.[0]} />}
    </main>
    <footer><a href="https://www.tradingview.com/">TradingView Lightweight Charts™</a> · <a href="/NOTICE">Attribution notice</a> · <a href="https://shadcndashboard.dev/">Shadcn Dashboard</a></footer>
  </div>;
}

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register("/sw.js").catch(() => {});
}

applyTheme(readTheme());
createRoot(document.getElementById("root")!).render(<Access
  dashboard={(role, signOut, expired) => <App role={role} signOut={signOut} expired={expired} />} />);
