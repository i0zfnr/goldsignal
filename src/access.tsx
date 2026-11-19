import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { InstallButton } from "./install";
import { ThemeToggle } from "./theme";
import { Badge, EmptyState, LoadingState, PanelHeading } from "./ui";

type Role = "admin" | "viewer" | "demo" | null;
type Settings = {
  configured: boolean;
  enabled: boolean;
  model: string;
  paused?: boolean;
  keys: Array<{ id: string; label: string; revoked: boolean }>;
};

export class ApiError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new ApiError(typeof data.detail === "string" ? data.detail : "Request failed. Try again.", response.status);
  }
  return response.json();
}

function send<T>(path: string, method: string, value: unknown) {
  return api<T>(path, { method, body: JSON.stringify(value), headers: { "Content-Type": "application/json" } });
}

function AccessHeader({ adminShortcut = false }: { adminShortcut?: boolean }) {
  return <header className="site-header"><div className="header-inner">
    <a className="wordmark" href="/"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
    {adminShortcut && <a className="admin-shortcut" href="/admin" aria-label="Admin sign-in"><span>Admin sign-in</span></a>}
    <div className="toolbar-actions"><InstallButton /><ThemeToggle /></div>
  </div></header>;
}

function LoginPage({ isAdmin, complete }: { isAdmin: boolean; complete: (role: Role) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true);
    setError("");
    try {
      const result = await send<{ role: Role }>(`/api/auth/${isAdmin ? "admin" : "viewer"}`, "POST", values);
      complete(result.role);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return <><AccessHeader adminShortcut={!isAdmin} />
    <main className="access-page login-layout">
      <section className="panel access-panel" aria-labelledby="login-title">
        <h1 id="login-title">{isAdmin ? "Admin sign-in" : "Sign in to Goldsignal"}</h1>
        <p className="muted">{isAdmin ? "Manage user access and Gemini review." : "Enter the access key your admin gave you."}</p>
        <form className="access-form" onSubmit={submit}>
          {isAdmin && <label>Email address<input name="email" type="email" required autoComplete="username" maxLength={254} /></label>}
          <label>{isAdmin ? "Password" : "Access key"}
            <input name="credential" type="password" autoComplete={isAdmin ? "current-password" : "off"} required maxLength={256} />
          </label>
          <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          {error && <p className="warn" role="alert">{error}</p>}
        </form>
      </section>
    </main>
  </>;
}

type ChatTurn = { role: "user" | "model"; text: string };

function AdminChat({ configured, model }: { configured: boolean; model: string }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!message.trim() || busy) return;
    const user: ChatTurn = { role: "user", text: message.trim() };
    const context = [...turns.slice(-38), user];
    const size = () => new TextEncoder().encode(JSON.stringify({ turns: context })).length;
    while (context.length > 1 && size() > 7800) context.splice(0, 2);
    if (!context.length || size() > 7800) {
      setError("This message is too large. Send it in smaller parts.");
      return;
    }
    setBusy(true);
    setError("");
    setTurns([...turns, user]);
    setMessage("");
    try {
      const { id } = await send<{ id: string }>("/api/admin/chat", "POST", { turns: context });
      for (let attempt = 0; attempt < 45; attempt++) {
        await new Promise(resolve => setTimeout(resolve, 1200));
        const result = await api<{ text?: string; error?: string }>(`/api/admin/chat?id=${encodeURIComponent(id)}`);
        if (result.error) throw new Error(result.error);
        if (result.text) {
          setTurns([...turns, user, { role: "model", text: result.text }]);
          return;
        }
      }
      throw new Error("Gemini took too long to respond.");
    } catch (failure) {
      setTurns(turns);
      setMessage(user.text);
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return <section className="panel access-panel admin-chat chat-panel" aria-labelledby="gemini-chat-title">
    <PanelHeading title="Gemini chat" id="gemini-chat-title" as="h3">
      {configured && <Badge>{model}</Badge>}
    </PanelHeading>
    {configured ? <>
      <div className="chat-turns" role="log" aria-label="Conversation">
        {turns.map((turn, index) => <article key={index} data-speaker={turn.role}>
          <strong>{turn.role === "user" ? "You" : "Gemini"}</strong>
          <p>{turn.text}</p>
        </article>)}
      </div>
      <form className="access-form" onSubmit={submit}>
        <label>Message<textarea value={message} onChange={event => setMessage(event.target.value)} rows={3} required disabled={busy} /></label>
        <button className="primary" type="submit" disabled={busy}>{busy ? "Waiting for Gemini…" : "Send message"}</button>
      </form>
      {error && <p className="warn" role="alert">{error}</p>}
    </> : <EmptyState>Save your API key in Gemini review to start chatting.</EmptyState>}
  </section>;
}

type BackendLogEntry = { time: number; source: string; level: "error" | "info"; message: string };

function BackendLog() {
  const [entries, setEntries] = useState<BackendLogEntry[] | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ entries: BackendLogEntry[] }>("/api/admin/errors");
      setEntries(result.entries);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => { void refresh(); }, []);

  return <section className="panel access-panel admin-chat" aria-labelledby="backend-log-title">
    <PanelHeading title="Backend error log" id="backend-log-title" as="h3">
      <button type="button" disabled={busy} onClick={() => void refresh()}>{busy ? "Refreshing…" : "Refresh log"}</button>
    </PanelHeading>
    {error && <p className="warn" role="alert">{error}{entries && " Showing last loaded entries."}</p>}
    {!entries && busy && <LoadingState>Loading backend log…</LoadingState>}
    {entries?.length === 0 && <EmptyState>No backend errors recorded yet.</EmptyState>}
    {!!entries?.length && <ol className="backend-log">
      {entries.map((entry, index) => <li key={`${entry.time}-${index}`}>
        <div className="backend-log-meta small">
          <Badge tone={entry.level === "error" ? "negative" : "neutral"}>{entry.level === "error" ? "Error" : "Info"}</Badge>
          <span>{entry.source}</span>
          <time className="muted" dateTime={new Date(entry.time).toISOString()}>{new Date(entry.time).toLocaleString()}</time>
        </div>
        <p>{entry.message}</p>
      </li>)}
    </ol>}
  </section>;
}

export const adminViews = [
  ["admin-users", "Users"],
  ["admin-workers", "Workers"],
  ["admin-ai", "AI Configuration"],
  ["admin-chat", "AI Chat"],
  ["admin-errors", "Error Log"],
] as const;
type WorkerRow = { name: string; label: string; role: string; status: string; reason: string | null; age_seconds: number | null };
type WorkerLane = { id: string; label: string; stages: WorkerRow[] };
type WorkerReport = {
  kuro: WorkerRow; lanes: WorkerLane[]; heartbeat_age: number | null; error: string | null; mode: string;
  symbol: string; revision: number; quote_age: number | null; spec_age: number | null;
  closed: boolean; scan?: string | null; scalp_scan?: string | null;
};

function workerClass(status: string) {
  if (["running", "setup", "CONFIRM", "published"].includes(status)) return "live";
  if (status === "error" || status === "REJECT") return "error";
  if (status === "WAIT") return "warn";
  return "idle";
}

function shortReason(value: string | null) {
  if (!value) return null;
  return value.length > 34 ? `${value.slice(0, 33)}…` : value;
}

function CrewCard({ row }: { row: WorkerRow }) {
  const tone = workerClass(row.status);
  return <article className={`crew-card crew-${tone}`} title={row.reason ?? row.role}>
    <span className="crew-bubble">{shortReason(row.reason) ?? row.status}</span>
    <div className={`crew-face face-${row.name}`} aria-hidden="true"><i /><i /><b /></div>
    <strong>{row.label}</strong>
    <small>{row.role}</small>
    <span className={`crew-chip chip-${tone}`}>
      {row.status}{row.age_seconds != null ? ` · ${row.age_seconds}s` : ""}
    </span>
  </article>;
}

function WorkerStatus() {
  const [report, setReport] = useState<WorkerReport | null>(null);
  const [error, setError] = useState("");
  const [bMtf, setBMtf] = useState<"M15" | "H1">("M15");
  const [bMtfBusy, setBMtfBusy] = useState(false);

  async function refresh() {
    try {
      setReport(await api<WorkerReport>("/api/admin/workers"));
      setError("");
    } catch (failure) {
      setError((failure as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
    api<{ mtf: "M15" | "H1" }>("/api/strategy-b/config")
      .then(res => setBMtf(res.mtf))
      .catch(() => {});
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, []);

  async function updateBMtf(mtf: "M15" | "H1") {
    if (bMtfBusy || mtf === bMtf) return;
    setBMtfBusy(true);
    try {
      await api("/api/admin/strategy-b/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mtf }),
      });
      setBMtf(mtf);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setBMtfBusy(false);
    }
  }

  const age = (value: number | null) => value == null ? "–" : `${value}s`;
  return <section className="panel access-panel" aria-labelledby="worker-status-title">
    <PanelHeading title="Worker pipeline" id="worker-status-title" as="h3">
      <Badge tone={report?.error ? "negative" : report && (report.heartbeat_age ?? 99) <= 30 ? "positive" : "neutral"}>
        {report?.error ? "Error" : report ? `Heartbeat ${age(report.heartbeat_age)}` : "Loading"}
      </Badge>
    </PanelHeading>
    {error && <p className="warn" role="alert">{error}</p>}
    {!report && !error && <LoadingState>Loading worker status…</LoadingState>}
    {report && <>
      <dl className="report-stats">
        <div><dt>Feed</dt><dd>{report.symbol} · {report.mode} · rev {report.revision}</dd></div>
        <div><dt>Quote age</dt><dd>{age(report.quote_age)}</dd></div>
        <div><dt>Spec age</dt><dd>{age(report.spec_age)}</dd></div>
        <div><dt>Market</dt><dd>{report.closed ? "Closed" : "Open"}</dd></div>
      </dl>
      <div className="crew-head">
        <strong>Crew</strong>
        <span>{report.lanes.flatMap(lane => lane.stages).concat(report.kuro)
          .filter(row => workerClass(row.status) === "live").length} live · {report.lanes.length} lanes</span>
      </div>
      <div className="crew-grid crew-kuro">
        <CrewCard row={report.kuro} />
      </div>
      {report.lanes.map(lane => {
        const active = lane.stages.some(row => workerClass(row.status) === "live");
        return <section className="crew-lane" key={lane.id}>
          <div className="crew-lane-head">
            <strong>{lane.label}</strong>
            <Badge tone={active ? "positive" : "neutral"}>{active ? "Active" : "Waiting"}</Badge>
          </div>
          {lane.id === "B" && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8, margin: "6px 0 12px", padding: "8px 12px", background: "var(--raised)", border: "1px solid var(--line)", borderRadius: 8 }}>
              <div>
                <strong className="small" style={{ display: "block" }}>Kaze Strategy B Direction Filter:</strong>
                <span className="small muted">Configure whether Kaze evaluates M15 intraday swings or H1 macro structure.</span>
              </div>
              <div className="segment-group" style={{ gap: 2 }}>
                <button
                  type="button"
                  className={bMtf === "M15" ? "primary small" : "small"}
                  style={{ minHeight: 28, padding: "2px 10px", fontSize: ".75rem" }}
                  disabled={bMtfBusy}
                  onClick={() => void updateBMtf("M15")}
                >
                  M15 (Active Scalp)
                </button>
                <button
                  type="button"
                  className={bMtf === "H1" ? "primary small" : "small"}
                  style={{ minHeight: 28, padding: "2px 10px", fontSize: ".75rem" }}
                  disabled={bMtfBusy}
                  onClick={() => void updateBMtf("H1")}
                >
                  H1 (Macro Trend)
                </button>
              </div>
            </div>
          )}
          <div className="crew-grid">
            {lane.stages.map(row => <CrewCard row={row} key={row.name} />)}
          </div>
        </section>;
      })}
      <p className="small muted">Three strategy lanes share one feed. Each lane has its own Kaze (analysis), Mizu (risk), Nanao (AI confirmation) and Hikari (delivery). No model can override a failed gate. Strategy C trades Asian range liquidity sweeps.</p>
    </>}
  </section>;
}

export type AdminView = typeof adminViews[number][0];

function TelegramPanel({ action, busy }: { action: (w: () => Promise<void>) => void; busy: boolean }) {
  const [tg, setTg] = useState<{ configured: boolean; enabled: boolean; chat_id: string | null; masked_token: string | null } | null>(null);
  const [botToken, setBotToken] = useState("");
  const [chatId, setChatId] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    api<{ configured: boolean; enabled: boolean; chat_id: string | null; masked_token: string | null }>("/api/admin/telegram")
      .then(res => {
        setTg(res);
        if (res.chat_id) setChatId(res.chat_id);
      })
      .catch(() => {});
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    void action(async () => {
      await api("/api/admin/telegram", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ bot_token: botToken, chat_id: chatId, enabled: true }),
      });
      setMessage("Telegram settings saved!");
      setBotToken("");
      const res = await api<{ configured: boolean; enabled: boolean; chat_id: string | null; masked_token: string | null }>("/api/admin/telegram");
      setTg(res);
    });
  }

  async function test() {
    setMessage("");
    void action(async () => {
      await api("/api/admin/telegram/test", { method: "POST" });
      setMessage("Test message sent successfully to your Telegram channel!");
    });
  }

  return (
    <section className="panel access-panel" style={{ marginTop: 12 }}>
      <PanelHeading title="Telegram Channel Delivery" as="h3">
        <Badge tone={tg?.configured ? "positive" : "neutral"}>{tg?.configured ? "Connected" : "Not configured"}</Badge>
      </PanelHeading>
      <p className="muted small">Instant 0ms alert broadcast for entry ready signals, TP/SL lifecycle, and early M5 heads-up warnings.</p>
      {tg?.configured && (
        <p className="small good" style={{ margin: "6px 0" }}>
          Active channel: <code>{tg.chat_id}</code> ({tg.masked_token})
        </p>
      )}
      <form className="access-form" onSubmit={save} style={{ marginTop: 8 }}>
        <label>Telegram Bot Token
          <input
            type="password"
            value={botToken}
            onChange={e => setBotToken(e.target.value)}
            placeholder={tg?.masked_token ? `Saved (${tg.masked_token}). Enter new token to change.` : "e.g. 7891234567:AAH..."}
            required={!tg?.configured}
          />
        </label>
        <label>Telegram Channel / Group Chat ID
          <input
            type="text"
            value={chatId}
            onChange={e => setChatId(e.target.value)}
            placeholder="e.g. @my_channel or -1001234567890"
            required
          />
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginTop: 4 }}>
          <button className="primary" type="submit" disabled={busy}>Save Telegram Settings</button>
          {tg?.configured && (
            <button type="button" disabled={busy} onClick={test}>Send Test Message to Channel</button>
          )}
        </div>
      </form>
      {message && <p className="small good" style={{ marginTop: 8 }}>{message}</p>}
    </section>
  );
}

export function AdminSettings({ view }: { view: AdminView | undefined }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [newKey, setNewKey] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() { setSettings(await api<Settings>("/api/admin/settings")); }
  useEffect(() => { void refresh().catch(failure => setError((failure as Error).message)); }, []);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try { await work(); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }

  function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const label = new FormData(form).get("label");
    void action(async () => {
      const result = await send<{ key: string }>("/api/admin/keys", "POST", { label });
      setNewKey(result.key);
      form.reset();
      await refresh();
    });
  }

  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const fields = new FormData(form);
    const enabled = fields.has("enabled");
    void action(async () => {
      await send("/api/admin/gemini", "PUT", { api_key: fields.get("api_key") || null, enabled });
      form.reset();
      await refresh();
      setMessage("Gemini settings saved.");
    });
  }

  return <section className="admin-page" id={view} hidden={!view} aria-labelledby="admin-settings-title">
      <h2 id="admin-settings-title">{adminViews.find(([id]) => id === view)?.[1]}</h2>
      {view !== "admin-errors" && error && <p className="warn" role="alert">{error}</p>}
      {(view === "admin-users" || view === "admin-ai") && message && <p role="status">{message}</p>}
      {settings ? <>
        <section className="panel access-panel" hidden={view !== "admin-users"}>
          <PanelHeading title="Viewer access" as="h3"><Badge tone="positive">{settings.keys.filter(key => !key.revoked).length} active</Badge></PanelHeading>
          <form className="access-form inline-form" onSubmit={create}>
            <label>Key label<input name="label" placeholder="e.g. Viewer name" required maxLength={80} /></label>
            <button className="primary" disabled={busy}>Create access key</button>
          </form>
          {newKey && <div className="issued-key">
            <label>New access key<input value={newKey} readOnly onFocus={event => event.currentTarget.select()} /></label>
            <p className="small muted">Copy and share this key privately. It is shown once.</p>
            <button onClick={() => void action(async () => { await navigator.clipboard.writeText(newKey); setMessage("Access key copied."); })}>Copy key</button>
          </div>}
          {settings.keys.length ? <ul className="key-list">{settings.keys.map(key => <li key={key.id}>
            <span>{key.label}</span>
            {key.revoked ? <Badge>Revoked</Badge> : <div className="key-actions"><Badge tone="positive">Active</Badge><button className="danger-button" disabled={busy} onClick={() => {
              if (confirm(`Revoke access for ${key.label}?`)) void action(async () => {
                await api(`/api/admin/keys?id=${encodeURIComponent(key.id)}`, { method: "DELETE" });
                await refresh();
              });
            }}>Revoke</button></div>}
          </li>)}</ul> : <EmptyState>No access keys issued.</EmptyState>}
        </section>
        <section className="panel access-panel" hidden={view !== "admin-ai"}>
          <PanelHeading title="Gemini review" as="h3"><Badge tone={settings.enabled ? "positive" : "neutral"}>{settings.enabled ? "Enabled" : "Disabled"}</Badge></PanelHeading>
          <dl className="model-display">
            <dt>Configured Gemini model</dt>
            <dd><code className="model-id">{settings.model}</code></dd>
          </dl>
          <p className="muted small">{settings.enabled ? "Used to review eligible signal setups." : "Gemini signal review is disabled."}</p>
          <form className="access-form" key={String(settings.enabled)} onSubmit={save}>
            <label>Google AI Studio API key
              <input name="api_key" type="password" autoComplete="off" maxLength={256}
                placeholder={settings.configured ? "Saved. Enter a new key to replace it." : "Paste your API key"} />
            </label>
            <label className="check-row"><input name="enabled" type="checkbox" defaultChecked={settings.enabled} />Enable Gemini review</label>
            <button className="primary" disabled={busy}>Save Gemini settings</button>
          </form>
        </section>
      <section className="panel access-panel admin-chat" hidden={view !== "admin-ai"}>
        <div className="panel-heading"><h3>Breaking-news pause</h3>
          <button type="button" disabled={busy} onClick={() => void action(async () => {
            await send("/api/admin/pause", "PUT", { paused: !settings.paused });
            await refresh();
          })}>{settings.paused ? "Resume entries" : "Pause entries for 1 hour"}</button>
        </div>
        <p className="muted">{settings.paused ? "New entries are paused. Filled signals are still tracked." : "Pause new entries during unexpected market events."}</p>
      </section>
      <div hidden={view !== "admin-ai"}><TelegramPanel action={action} busy={busy} /></div>
      <div hidden={view !== "admin-chat"}><AdminChat configured={settings.configured} model={settings.model} /></div>
      </> : !error && view !== "admin-errors" && <LoadingState>Loading settings…</LoadingState>}
      {view === "admin-errors" && <BackendLog />}
      {view === "admin-workers" && <WorkerStatus />}
    </section>;
}

export function Access({ dashboard }: { dashboard: (
  role: Role, signOut: () => Promise<void>, expired: () => void
) => ReactNode }) {
  const [role, setRole] = useState<Role | undefined>(undefined);
  const [error, setError] = useState("");
  const isAdmin = location.pathname === "/admin";
  function load() {
    setError("");
    void api<{ role: Role }>("/api/auth/session").then(result => setRole(result.role))
      .catch(failure => setError((failure as Error).message));
  }
  useEffect(load, []);

  async function signOut() {
    try {
      await api("/api/auth/session", { method: "DELETE" });
      setRole(null);
    } catch (failure) {
      setError((failure as Error).message);
    }
  }

  if (error) return <><AccessHeader /><main className="access-page">
    <p className="warn" role="alert">{error}</p><button onClick={load}>Retry</button>
  </main></>;
  if (role === undefined) return <><AccessHeader /><main className="access-page"><p role="status">Checking access…</p></main></>;
  if (isAdmin && role !== "admin") return <LoginPage key={role ?? "guest"} isAdmin complete={setRole} />;
  if (!role) return <LoginPage isAdmin={false} complete={setRole} />;
  return dashboard(role, signOut, () => setRole(null));
}
