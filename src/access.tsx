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
type WorkerReport = {
  workers: WorkerRow[]; heartbeat_age: number | null; error: string | null; mode: string;
  symbol: string; revision: number; quote_age: number | null; spec_age: number | null;
  closed: boolean; scan?: string | null; scalp_scan?: string | null;
};

function workerTone(status: string) {
  if (["running", "setup", "CONFIRM", "published"].includes(status)) return "positive" as const;
  if (["error", "REJECT"].includes(status)) return "negative" as const;
  return "neutral" as const;
}

function WorkerStatus() {
  const [report, setReport] = useState<WorkerReport | null>(null);
  const [error, setError] = useState("");

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
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, []);

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
      <table className="report-breakdown">
        <thead><tr><th scope="col">Worker</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col">Last reason</th><th scope="col">Age</th></tr></thead>
        <tbody>{report.workers.map(row => <tr key={row.name}>
          <th scope="row">{row.label}</th>
          <td>{row.role}</td>
          <td><Badge tone={workerTone(row.status)}>{row.status}</Badge></td>
          <td className="muted">{row.reason ?? "–"}</td>
          <td>{age(row.age_seconds)}</td>
        </tr>)}</tbody>
      </table>
      <p className="small muted">Logical stages in one worker process: Kaze analyses, Mizu checks risk and gates, Nanao reviews with AI, Hikari publishes. No model can override a failed gate.</p>
    </>}
  </section>;
}

export type AdminView = typeof adminViews[number][0];

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
