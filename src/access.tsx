import { useEffect, useState, type FormEvent, type ReactNode } from "react";

type Role = "admin" | "viewer" | "demo" | null;
type Settings = {
  configured: boolean;
  enabled: boolean;
  model: string;
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

function AccessHeader({ children }: { children?: ReactNode }) {
  return <header className="site-header"><div className="header-inner">
    <a className="wordmark" href="/"><span className="brand-mark" aria-hidden="true"><i /><i /><i /></span> Goldsignal</a>
    {children}
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
  return <><AccessHeader><a href={isAdmin ? "/" : "/admin"}>{isAdmin ? "User sign-in" : "Admin sign-in"}</a></AccessHeader>
    <main className="access-page">
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

function AdminSettings() {
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

  return <section className="admin-page" id="admin-settings" aria-labelledby="admin-settings-title">
      <h2 id="admin-settings-title">Admin settings</h2>
      {error && <p className="warn" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {settings ? <div className="admin-grid">
        <section className="panel access-panel">
          <div className="panel-heading"><h3>Viewer access</h3><span className="muted">{settings.keys.filter(key => !key.revoked).length} active</span></div>
          <form className="access-form" onSubmit={create}>
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
            {key.revoked ? <span className="muted">Revoked</span> : <button disabled={busy} onClick={() => {
              if (confirm(`Revoke access for ${key.label}?`)) void action(async () => {
                await api(`/api/admin/keys?id=${encodeURIComponent(key.id)}`, { method: "DELETE" });
                await refresh();
              });
            }}>Revoke</button>}
          </li>)}</ul> : <p className="muted">No access keys issued.</p>}
        </section>
        <section className="panel access-panel">
          <div className="panel-heading"><h3>Gemini review</h3><span className={settings.enabled ? "good" : "muted"}>{settings.enabled ? "Enabled" : "Disabled"}</span></div>
          <p className="muted">Python sends eligible setups to {settings.model} for one shared review. Usage follows your Google AI Studio project limits.</p>
          <form className="access-form" key={String(settings.enabled)} onSubmit={save}>
            <label>Google AI Studio API key
              <input name="api_key" type="password" autoComplete="off" maxLength={256}
                placeholder={settings.configured ? "Saved. Enter a new key to replace it." : "Paste your API key"} />
            </label>
            <label className="check-row"><input name="enabled" type="checkbox" defaultChecked={settings.enabled} />Enable Gemini review</label>
            <button className="primary" disabled={busy}>Save Gemini settings</button>
          </form>
        </section>
      </div> : !error && <p role="status">Loading settings…</p>}
    </section>;
}

export function Access({ dashboard }: { dashboard: (
  role: Role, signOut: () => Promise<void>, expired: () => void, settings?: ReactNode
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
  return dashboard(role, signOut, () => setRole(null), isAdmin ? <AdminSettings /> : undefined);
}
