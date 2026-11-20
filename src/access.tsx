import { Fragment, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  AlertTriangle, ArrowUp, Check, CheckCircle2, Copy, Download, Edit2,
  Gauge, Key, MessageSquare, Plus, RefreshCw, RotateCcw, RotateCw,
  Search, Send, Sparkles, Trash2, UserPlus, Users, X
} from "lucide-react";
import { InstallButton } from "./install";
import { ThemeToggle } from "./theme";
import { Badge, EmptyState, LoadingState, PanelHeading } from "./ui";

type Role = "admin" | "viewer" | "demo" | null;
type AccessKey = {
  id: string;
  label: string;
  revoked: boolean;
  token?: string;
  created?: number;
};
type Settings = {
  configured: boolean;
  enabled: boolean;
  model: string;
  paused?: boolean;
  keys: AccessKey[];
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

function renderMarkdown(text: string) {
  return text.split("\n").map((line, lIdx) => {
    const isBullet = line.trim().startsWith("- ") || line.trim().startsWith("* ");
    const content = isBullet ? line.trim().slice(2) : line;
    const parts = content.split(/(\*\*.*?\*\*|`.*?`)/g);
    const parsed = parts.map((part, pIdx) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={pIdx}>{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={pIdx} className="chat-code">{part.slice(1, -1)}</code>;
      }
      return part;
    });
    if (isBullet) {
      return <li key={lIdx} className="chat-bullet">{parsed}</li>;
    }
    return <p key={lIdx} className="chat-line">{parsed || "\u00A0"}</p>;
  });
}

function AdminChat({ configured, model }: { configured: boolean; model: string }) {
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const quickPrompts = [
    "📊 Analyze current XAUUSD price & structure",
    "📍 Where are the nearest SMC liquidity zones?",
    "📅 Check today's high-impact economic news",
    "⚡ What is Kaze Strategy B status right now?",
  ];

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [turns, busy]);

  async function sendTurn(textToSend: string) {
    if (!textToSend.trim() || busy) return;
    const user: ChatTurn = { role: "user", text: textToSend.trim() };
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
      throw new Error("AI took too long to respond.");
    } catch (failure) {
      setTurns(turns);
      setMessage(user.text);
      setError((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function handleCopy(text: string, idx: number) {
    void navigator.clipboard.writeText(text);
    setCopiedIdx(idx);
    setTimeout(() => setCopiedIdx(null), 2000);
  }

  return (
    <section className="panel access-panel modern-chat-card" aria-labelledby="ai-chat-title">
      <div className="modern-chat-header">
        <div className="chat-header-info">
          <div className="chat-avatar-ai"><Sparkles size={18} /></div>
          <div>
            <h3 id="ai-chat-title" className="chat-title">GoldSignal AI Copilot</h3>
            <span className="chat-telemetry-badge">
              <span className="telemetry-online-dot" /> Connected to live market telemetry
            </span>
          </div>
        </div>
        <Badge tone="accent">{model}</Badge>
      </div>

      {configured ? (
        <div className="modern-chat-container">
          <div ref={scrollRef} className="modern-chat-messages" role="log" aria-label="Conversation history">
            {turns.length === 0 && (
              <div className="chat-welcome-state">
                <div className="chat-welcome-icon"><Sparkles size={28} /></div>
                <h4>Institutional Market Copilot</h4>
                <p className="small muted">Ask anything about live XAUUSD price action, SMC liquidity zones, MTF bias, active trade signals, or economic news.</p>
              </div>
            )}
            {turns.map((turn, index) => {
              const isUser = turn.role === "user";
              return (
                <div key={index} className={`chat-bubble-row ${isUser ? "user-row" : "ai-row"}`}>
                  {!isUser && (
                    <div className="chat-message-avatar ai"><Sparkles size={16} /></div>
                  )}
                  <div className={`chat-bubble ${isUser ? "user-bubble" : "ai-bubble"}`}>
                    <div className="chat-bubble-author">
                      <span>{isUser ? "You" : "GoldSignal AI"}</span>
                      {!isUser && (
                        <button
                          type="button"
                          className="chat-copy-btn"
                          title="Copy response"
                          onClick={() => handleCopy(turn.text, index)}
                        >
                          {copiedIdx === index ? <Check size={12} /> : <Copy size={12} />}
                          <span>{copiedIdx === index ? "Copied" : "Copy"}</span>
                        </button>
                      )}
                    </div>
                    <div className="chat-bubble-content">
                      {isUser ? <p>{turn.text}</p> : renderMarkdown(turn.text)}
                    </div>
                  </div>
                </div>
              );
            })}
            {busy && (
              <div className="chat-bubble-row ai-row">
                <div className="chat-message-avatar ai"><Sparkles size={16} /></div>
                <div className="chat-bubble ai-bubble typing-bubble">
                  <div className="typing-dots">
                    <span /><span /><span />
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="chat-bottom-dock">
            <div className="chat-prompts-strip">
              {quickPrompts.map(p => (
                <button
                  key={p}
                  type="button"
                  className="quick-prompt-btn"
                  disabled={busy}
                  onClick={() => void sendTurn(p)}
                >
                  {p}
                </button>
              ))}
            </div>

            <form
              className="chat-input-form"
              onSubmit={e => {
                e.preventDefault();
                void sendTurn(message);
              }}
            >
              <textarea
                className="chat-input-area"
                value={message}
                onChange={e => setMessage(e.target.value)}
                onKeyDown={e => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendTurn(message);
                  }
                }}
                rows={1}
                placeholder="Ask about price, zones, bias, or trade execution… (Enter to send)"
                disabled={busy}
              />
              <button className="chat-send-btn" type="submit" disabled={busy || !message.trim()} aria-label="Send">
                <ArrowUp size={18} />
              </button>
            </form>
          </div>
        </div>
      ) : (
        <EmptyState>Save your API key in AI Configuration to activate the copilot.</EmptyState>
      )}
      {error && <p className="warn small" role="alert" style={{ marginTop: 8 }}>{error}</p>}
    </section>
  );
}

type BackendLogEntry = { time: number; source: string; level: "error" | "info"; message: string };

function BackendLog() {
  const [entries, setEntries] = useState<BackendLogEntry[] | null>(null);
  const [timeframe, setTimeframe] = useState<"24h" | "7d" | "all">("24h");
  const [levelFilter, setLevelFilter] = useState<"all" | "error" | "info">("all");
  const [busy, setBusy] = useState(true);
  const [clearing, setClearing] = useState(false);
  const [error, setError] = useState("");

  async function refresh(isInitial = false) {
    if (isInitial) setBusy(true);
    setError("");
    try {
      const result = await api<{ entries: BackendLogEntry[] }>(`/api/admin/errors?timeframe=${timeframe}`);
      setEntries(result.entries);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      if (isInitial) setBusy(false);
    }
  }

  useEffect(() => {
    void refresh(true);
    const timer = setInterval(() => void refresh(false), 5000);
    return () => clearInterval(timer);
  }, [timeframe]);

  async function clearLogs() {
    if (!confirm("Are you sure you want to permanently clear all backend error logs?")) return;
    setClearing(true);
    try {
      await api("/api/admin/errors", { method: "DELETE" });
      setEntries([]);
    } catch (failure) {
      setError((failure as Error).message);
    } finally {
      setClearing(false);
    }
  }

  const filtered = (entries ?? []).filter(e => levelFilter === "all" || e.level === levelFilter);

  return (
    <section className="panel access-panel log-page-card" aria-labelledby="backend-log-title">
      <PanelHeading title="Backend Error & Telemetry Log" id="backend-log-title" as="h3">
        <div style={{ display: "flex", gap: 6 }}>
          <button type="button" disabled={busy} onClick={() => void refresh(true)}>
            <RotateCw size={14} /> Refresh
          </button>
          <button type="button" className="danger-button" disabled={clearing || !entries?.length} onClick={() => void clearLogs()}>
            <Trash2 size={14} /> Clear Log
          </button>
        </div>
      </PanelHeading>

      <div className="log-filter-bar">
        <div className="segment-group" role="group" aria-label="Timeframe">
          {(["24h", "7d", "all"] as const).map(tf => (
            <button
              key={tf}
              type="button"
              className={timeframe === tf ? "primary small" : "small"}
              onClick={() => setTimeframe(tf)}
            >
              {tf === "24h" ? "Last 24 Hours" : tf === "7d" ? "Last 7 Days" : "All Time"}
            </button>
          ))}
        </div>

        <div className="segment-group" role="group" aria-label="Level">
          {(["all", "error", "info"] as const).map(lvl => (
            <button
              key={lvl}
              type="button"
              className={levelFilter === lvl ? "primary small" : "small"}
              onClick={() => setLevelFilter(lvl)}
            >
              {lvl === "all" ? "All Levels" : lvl === "error" ? "Errors Only" : "Info"}
            </button>
          ))}
        </div>
      </div>

      {error && <p className="warn" role="alert">{error}{entries && " Showing cached entries."}</p>}
      {!entries && busy && <LoadingState>Loading backend logs…</LoadingState>}
      {entries?.length === 0 && <EmptyState>No backend error records found in this timeframe.</EmptyState>}
      {!!filtered.length && (
        <ol className="backend-log modern-log-list">
          {filtered.map((entry, index) => (
            <li key={`${entry.time}-${index}`} className={`log-item log-${entry.level}`}>
              <div className="backend-log-meta small">
                <Badge tone={entry.level === "error" ? "negative" : "neutral"}>
                  {entry.level === "error" ? "ERROR" : "INFO"}
                </Badge>
                <strong className="log-source">{entry.source}</strong>
                <time className="muted" dateTime={new Date(entry.time).toISOString()}>
                  {new Date(entry.time).toLocaleString()}
                </time>
              </div>
              <p className="log-msg">{entry.message}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export const adminViews = [
  ["admin-users", "Users"],
  ["admin-workers", "Workers"],
  ["admin-ai", "AI Configuration"],
  ["admin-chat", "AI Chat"],
  ["admin-performance", "Performance Control"],
  ["admin-errors", "Error Log"],
] as const;
type WorkerRow = { name: string; label: string; role: string; status: string; reason: string | null; age_seconds: number | null };
type WorkerLane = { id: string; label: string; stages: WorkerRow[] };
type WorkerReport = {
  kuro: WorkerRow;
  hayate?: WorkerRow;
  ryu?: WorkerRow;
  shinra?: WorkerRow;
  division?: WorkerRow[];
  lanes: WorkerLane[]; heartbeat_age: number | null; error: string | null; mode: string;
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

function CyberAvatar({ name, tone }: { name: string; tone: string }) {
  const isLive = tone === "live";

  if (name === "kuro") {
    return (
      <div className={`cyber-avatar avatar-kuro ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <radialGradient id="kuro-metal" cx="35%" cy="30%" r="70%">
              <stop offset="0%" stopColor="#475569" />
              <stop offset="60%" stopColor="#1e293b" />
              <stop offset="100%" stopColor="#090d16" />
            </radialGradient>
            <linearGradient id="kuro-cyan" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#38bdf8" />
              <stop offset="100%" stopColor="#0284c7" />
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="30" fill="none" stroke="#334155" strokeWidth="1" strokeDasharray="3 3" className="avatar-radar" />
          <polygon points="32,6 54,18 54,46 32,58 10,46 10,18" fill="url(#kuro-metal)" stroke="#94a3b8" strokeWidth="1.5" />
          <rect x="18" y="26" width="28" height="10" rx="3" fill="#020617" stroke="#38bdf8" strokeWidth="1" />
          <line x1="20" y1="31" x2="44" y2="31" stroke="url(#kuro-cyan)" strokeWidth="2.5" strokeLinecap="round" className="avatar-scan-bar" />
          <circle cx="32" cy="31" r="2.5" fill="#ffffff" />
          <circle cx="32" cy="49" r="2.5" fill="#38bdf8" className={isLive ? "pulse-dot" : ""} />
        </svg>
      </div>
    );
  }

  if (name === "kaze") {
    return (
      <div className={`cyber-avatar avatar-kaze ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="kaze-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#27272a" />
              <stop offset="70%" stopColor="#18181b" />
              <stop offset="100%" stopColor="#09090b" />
            </linearGradient>
            <linearGradient id="kaze-gold" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#fbbf24" />
              <stop offset="100%" stopColor="#f59e0b" />
            </linearGradient>
          </defs>
          <path d="M12 20 Q32 8 52 20 L56 42 Q32 58 8 42 Z" fill="url(#kaze-metal)" stroke="#f59e0b" strokeWidth="1.5" />
          <path d="M6 24 L14 26 L12 36 Z" fill="#f59e0b" opacity="0.8" />
          <path d="M58 24 L50 26 L52 36 Z" fill="#f59e0b" opacity="0.8" />
          <path d="M16 26 Q32 20 48 26 L46 36 Q32 30 18 36 Z" fill="#09090b" stroke="#f59e0b" strokeWidth="1" />
          <circle cx="25" cy="30" r="3" fill="url(#kaze-gold)" className={isLive ? "avatar-eye-pulse" : ""} />
          <circle cx="39" cy="30" r="3" fill="url(#kaze-gold)" className={isLive ? "avatar-eye-pulse" : ""} />
          <line x1="26" y1="44" x2="26" y2="48" stroke="#f59e0b" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="30" y1="42" x2="30" y2="50" stroke="#f59e0b" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="34" y1="42" x2="34" y2="50" stroke="#f59e0b" strokeWidth="1.5" strokeLinecap="round" />
          <line x1="38" y1="44" x2="38" y2="48" stroke="#f59e0b" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
    );
  }

  if (name === "mizu") {
    return (
      <div className={`cyber-avatar avatar-mizu ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="mizu-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#1e3a8a" />
              <stop offset="60%" stopColor="#0f172a" />
              <stop offset="100%" stopColor="#020617" />
            </linearGradient>
            <linearGradient id="mizu-cyan" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#67e8f9" />
              <stop offset="100%" stopColor="#38bdf8" />
            </linearGradient>
          </defs>
          <path d="M32 6 L54 14 L50 44 Q32 58 14 44 L10 14 Z" fill="url(#mizu-metal)" stroke="#38bdf8" strokeWidth="1.5" />
          <polygon points="32,10 40,16 32,22 24,16" fill="#38bdf8" opacity="0.6" />
          <path d="M18 28 L46 28 L42 40 L22 40 Z" fill="#020617" stroke="#38bdf8" strokeWidth="1" />
          <rect x="23" y="32" width="6" height="4" fill="url(#mizu-cyan)" className={isLive ? "avatar-eye-pulse" : ""} />
          <rect x="35" y="32" width="6" height="4" fill="url(#mizu-cyan)" className={isLive ? "avatar-eye-pulse" : ""} />
          <line x1="28" y1="48" x2="36" y2="48" stroke="#38bdf8" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
    );
  }

  if (name === "nanao") {
    return (
      <div className={`cyber-avatar avatar-nanao ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="nanao-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#064e3b" />
              <stop offset="60%" stopColor="#022c22" />
              <stop offset="100%" stopColor="#020617" />
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="24" fill="url(#nanao-metal)" stroke="#10b981" strokeWidth="1.5" />
          <path d="M18 18 L24 24 M46 18 L40 24 M32 10 L32 18" stroke="#10b981" strokeWidth="1.2" strokeLinecap="round" opacity="0.75" />
          <circle cx="18" cy="18" r="2" fill="#34d399" />
          <circle cx="46" cy="18" r="2" fill="#34d399" />
          <circle cx="32" cy="10" r="2" fill="#34d399" />
          <path d="M18 28 Q32 24 46 28 L44 38 Q32 34 20 38 Z" fill="#020617" stroke="#10b981" strokeWidth="1" />
          <circle cx="26" cy="32" r="2.5" fill="#34d399" className={isLive ? "avatar-eye-pulse" : ""} />
          <circle cx="32" cy="32" r="2.5" fill="#34d399" className={isLive ? "avatar-eye-pulse" : ""} />
          <circle cx="38" cy="32" r="2.5" fill="#34d399" className={isLive ? "avatar-eye-pulse" : ""} />
          <path d="M26 46 Q32 50 38 46" fill="none" stroke="#10b981" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      </div>
    );
  }

  if (name === "hayate") {
    return (
      <div className={`cyber-avatar avatar-hayate ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="hayate-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#451a03" />
              <stop offset="50%" stopColor="#78350f" />
              <stop offset="100%" stopColor="#18181b" />
            </linearGradient>
            <linearGradient id="hayate-plasma" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#fef08a" />
              <stop offset="50%" stopColor="#f59e0b" />
              <stop offset="100%" stopColor="#d97706" />
            </linearGradient>
          </defs>
          <polygon points="32,4 44,16 58,20 48,36 50,56 32,48 14,56 16,36 6,20 20,16" fill="url(#hayate-metal)" stroke="#f59e0b" strokeWidth="1.5" />
          <polygon points="32,10 40,22 48,34 32,40 16,34 24,22" fill="#09090b" stroke="#fbbf24" strokeWidth="1" />
          <path d="M20 25 L44 25 L38 32 L26 32 Z" fill="url(#hayate-plasma)" className={isLive ? "avatar-scan-bar" : ""} />
          <circle cx="32" cy="22" r="3" fill="#ffffff" className={isLive ? "pulse-dot" : ""} />
          <line x1="20" y1="46" x2="14" y2="58" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
          <line x1="44" y1="46" x2="50" y2="58" stroke="#f59e0b" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
    );
  }

  if (name === "ryu") {
    return (
      <div className={`cyber-avatar avatar-ryu ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="ryu-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#7f1d1d" />
              <stop offset="60%" stopColor="#450a0a" />
              <stop offset="100%" stopColor="#0a0505" />
            </linearGradient>
            <linearGradient id="ryu-laser" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#f87171" />
              <stop offset="50%" stopColor="#ef4444" />
              <stop offset="100%" stopColor="#dc2626" />
            </linearGradient>
          </defs>
          <polygon points="32,4 52,14 60,34 50,56 32,60 14,56 4,34 12,14" fill="url(#ryu-metal)" stroke="#ef4444" strokeWidth="1.5" />
          <polygon points="26,16 38,16 44,28 32,40 20,28" fill="#180505" stroke="#f87171" strokeWidth="1" />
          <polygon points="12,18 20,8 26,18" fill="#dc2626" />
          <polygon points="52,18 44,8 38,18" fill="#dc2626" />
          <line x1="16" y1="30" x2="48" y2="30" stroke="url(#ryu-laser)" strokeWidth="3" strokeLinecap="round" className={isLive ? "avatar-scan-bar" : ""} />
          <circle cx="24" cy="30" r="2.5" fill="#ffffff" />
          <circle cx="40" cy="30" r="2.5" fill="#ffffff" />
          <polygon points="32,44 38,52 26,52" fill="#ef4444" />
        </svg>
      </div>
    );
  }

  if (name === "shinra") {
    return (
      <div className={`cyber-avatar avatar-shinra ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <radialGradient id="shinra-core" cx="40%" cy="30%" r="70%">
              <stop offset="0%" stopColor="#7c3aed" />
              <stop offset="60%" stopColor="#4c1d95" />
              <stop offset="100%" stopColor="#0f0728" />
            </radialGradient>
            <linearGradient id="shinra-glow" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#e9d5ff" />
              <stop offset="100%" stopColor="#a855f7" />
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="30" fill="none" stroke="#a855f7" strokeWidth="1" strokeDasharray="4 2" className="avatar-radar" />
          <polygon points="32,6 56,20 56,44 32,58 8,44 8,20" fill="url(#shinra-core)" stroke="#c084fc" strokeWidth="1.5" />
          <circle cx="32" cy="32" r="14" fill="#0f0728" stroke="#a855f7" strokeWidth="1" />
          <polygon points="32,22 39,32 32,42 25,32" fill="url(#shinra-glow)" className={isLive ? "avatar-eye-pulse" : ""} />
          <circle cx="32" cy="32" r="3" fill="#ffffff" />
          <circle cx="32" cy="12" r="2" fill="#c084fc" />
          <circle cx="32" cy="52" r="2" fill="#c084fc" />
        </svg>
      </div>
    );
  }

  if (name === "taka") {
    return (
      <div className={`cyber-avatar avatar-taka ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="taka-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#78350f" />
              <stop offset="60%" stopColor="#451a03" />
              <stop offset="100%" stopColor="#18181b" />
            </linearGradient>
          </defs>
          <polygon points="32,6 56,24 46,56 18,56 8,24" fill="url(#taka-metal)" stroke="#f59e0b" strokeWidth="1.5" />
          <line x1="12" y1="20" x2="52" y2="20" stroke="#fbbf24" strokeWidth="1" strokeDasharray="2 2" />
          <line x1="32" y1="10" x2="32" y2="52" stroke="#fbbf24" strokeWidth="1" strokeDasharray="2 2" />
          <polygon points="20,28 32,36 44,28 32,44" fill="#18181b" stroke="#f59e0b" strokeWidth="1" />
          <circle cx="26" cy="32" r="2.5" fill="#f59e0b" className={isLive ? "avatar-eye-pulse" : ""} />
          <circle cx="38" cy="32" r="2.5" fill="#f59e0b" className={isLive ? "avatar-eye-pulse" : ""} />
        </svg>
      </div>
    );
  }

  if (name === "ren") {
    return (
      <div className={`cyber-avatar avatar-ren ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="ren-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#0e7490" />
              <stop offset="60%" stopColor="#164e63" />
              <stop offset="100%" stopColor="#082f49" />
            </linearGradient>
          </defs>
          <polygon points="32,6 54,18 54,46 32,58 10,46 10,18" fill="url(#ren-metal)" stroke="#38bdf8" strokeWidth="1.5" />
          <rect x="20" y="20" width="24" height="24" rx="4" fill="#082f49" stroke="#67e8f9" strokeWidth="1" />
          <rect x="24" y="24" width="16" height="5" fill="#38bdf8" opacity="0.8" />
          <rect x="24" y="35" width="16" height="5" fill="#38bdf8" opacity="0.8" />
          <line x1="22" y1="32" x2="42" y2="32" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="2 2" className={isLive ? "avatar-scan-bar" : ""} />
        </svg>
      </div>
    );
  }

  if (name === "kai") {
    return (
      <div className={`cyber-avatar avatar-kai ${tone}`}>
        <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
          <defs>
            <linearGradient id="kai-metal" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#065f46" />
              <stop offset="60%" stopColor="#064e3b" />
              <stop offset="100%" stopColor="#022c22" />
            </linearGradient>
          </defs>
          <circle cx="32" cy="32" r="26" fill="url(#kai-metal)" stroke="#10b981" strokeWidth="1.5" />
          <circle cx="22" cy="24" r="3" fill="#34d399" />
          <circle cx="42" cy="24" r="3" fill="#34d399" />
          <circle cx="32" cy="38" r="4" fill="#6ee7b7" className={isLive ? "avatar-eye-pulse" : ""} />
          <line x1="22" y1="24" x2="32" y2="38" stroke="#10b981" strokeWidth="1.2" />
          <line x1="42" y1="24" x2="32" y2="38" stroke="#10b981" strokeWidth="1.2" />
          <circle cx="32" cy="18" r="2" fill="#34d399" />
          <line x1="32" y1="18" x2="32" y2="38" stroke="#10b981" strokeWidth="1" strokeDasharray="2 2" />
        </svg>
      </div>
    );
  }

  // hikari
  return (
    <div className={`cyber-avatar avatar-hikari ${tone}`}>
      <svg viewBox="0 0 64 64" className="cyber-svg" aria-hidden="true">
        <defs>
          <linearGradient id="hikari-metal" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor="#581c87" />
            <stop offset="60%" stopColor="#3b0764" />
            <stop offset="100%" stopColor="#0f051d" />
          </linearGradient>
          <linearGradient id="hikari-laser" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#f472b6" />
            <stop offset="50%" stopColor="#c084fc" />
            <stop offset="100%" stopColor="#a855f7" />
          </linearGradient>
        </defs>
        <polygon points="4,20 16,28 12,40" fill="#a855f7" opacity="0.8" />
        <polygon points="60,20 48,28 52,40" fill="#a855f7" opacity="0.8" />
        <path d="M16 16 L48 16 L52 42 Q32 58 12 42 Z" fill="url(#hikari-metal)" stroke="#a855f7" strokeWidth="1.5" />
        <polygon points="12,30 52,30 46,36 18,36" fill="#0f051d" stroke="#c084fc" strokeWidth="1" />
        <line x1="14" y1="33" x2="50" y2="33" stroke="url(#hikari-laser)" strokeWidth="2.5" strokeLinecap="round" className={isLive ? "avatar-scan-bar" : ""} />
        <polygon points="32,44 35,49 29,49" fill="#c084fc" />
      </svg>
    </div>
  );
}

function CrewCard({ row, isCore = false }: { row: WorkerRow; isCore?: boolean }) {
  const tone = workerClass(row.status);
  return (
    <article className={`crew-card crew-${tone} ${isCore ? "crew-core" : ""}`} title={row.reason ?? row.role}>
      <span className="crew-bubble">{shortReason(row.reason) ?? row.status}</span>
      <div className="crew-avatar-frame">
        <CyberAvatar name={row.name} tone={tone} />
      </div>
      <div className="crew-info">
        <strong>{row.label}</strong>
        <small>{row.role}</small>
      </div>
      <span className={`crew-chip chip-${tone}`}>
        <span className={`chip-dot dot-${tone}`} />
        {row.status}{row.age_seconds != null ? ` · ${row.age_seconds}s` : ""}
      </span>
    </article>
  );
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
  return <section className="panel access-panel worker-status-panel" aria-labelledby="worker-status-title">
    <PanelHeading title="Worker pipeline" id="worker-status-title" as="h3">
      <Badge tone={report?.error ? "negative" : report && (report.heartbeat_age ?? 99) <= 30 ? "positive" : "neutral"}>
        {report?.error ? "Error" : report ? `Heartbeat ${age(report.heartbeat_age)}` : "Loading"}
      </Badge>
    </PanelHeading>
    {error && <p className="warn" role="alert">{error}</p>}
    {!report && !error && <LoadingState>Loading worker status…</LoadingState>}
    {report && <>
      {/* 1. Master Command Center & High-Speed Core Squadron */}
      <div className="kuro-hub-card">
        <div className="kuro-hub-avatar-area">
          <CrewCard row={report.kuro} isCore />
          {report.hayate && <CrewCard row={report.hayate} isCore />}
          {report.ryu && <CrewCard row={report.ryu} isCore />}
          {report.shinra && <CrewCard row={report.shinra} isCore />}
        </div>
        <div className="kuro-hub-body">
          <div className="kuro-hub-header">
            <span className="hub-tag">CORE COMMAND SQUADRON</span>
            <span className="hub-subhead">Kuro (Feed) · Hayate (Parallel Compute) · Ryu (Dispatch) · Shinra (Quantitative)</span>
          </div>
          <div className="kuro-hud-grid">
            <div className="kuro-hud-stat">
              <span className="hud-label">INSTRUMENT</span>
              <strong className="hud-val">{report.symbol}</strong>
            </div>
            <div className="kuro-hud-stat">
              <span className="hud-label">FEED SOURCE</span>
              <strong className="hud-val">{report.mode.toUpperCase()}</strong>
            </div>
            <div className="kuro-hud-stat">
              <span className="hud-label">REVISION</span>
              <strong className="hud-val">#{report.revision}</strong>
            </div>
            <div className="kuro-hud-stat">
              <span className="hud-label">QUOTE AGE</span>
              <strong className={`hud-val ${(report.quote_age ?? 99) <= 2 ? "good" : "warn"}`}>{age(report.quote_age)}</strong>
            </div>
            <div className="kuro-hud-stat">
              <span className="hud-label">SPEC CLOCK</span>
              <strong className="hud-val">{age(report.spec_age)}</strong>
            </div>
            <div className="kuro-hud-stat">
              <span className="hud-label">MARKET STATE</span>
              <strong className={`hud-val ${report.closed ? "warn" : "good"}`}>{report.closed ? "CLOSED" : "OPEN"}</strong>
            </div>
          </div>
        </div>
      </div>

      {/* 2. Shinra Quantitative Research Division (Sub-workers & Graph Intelligence) */}
      {report.division && report.division.length > 0 && (
        <div className="shinra-division-card">
          <div className="shinra-division-head">
            <div className="shinra-title-group">
              <span className="division-badge">RESEARCH DIVISION</span>
              <strong style={{ color: "#ffffff", fontSize: "0.875rem" }}>Shinra Quantitative Intelligence</strong>
              <span className="small muted">· 1,000-candle structural geometry, Fair Value Gaps & probability engine</span>
            </div>
            <Badge tone="accent">Active Matrix</Badge>
          </div>
          <div className="shinra-staff-track">
            {report.division.map((staff, idx) => (
              <div key={staff.name} className="shinra-staff-node">
                <span className="pipeline-step-idx">RESEARCHER 0{idx + 1}</span>
                <CrewCard row={staff} />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="crew-head">
        <strong>Execution Pipeline</strong>
        <span className="pipeline-count-badge">
          {report.lanes.flatMap(lane => lane.stages).concat(report.kuro)
            .filter(row => workerClass(row.status) === "live").length} live · {report.lanes.length} strategy lanes
        </span>
      </div>

      {report.lanes.map(lane => {
        const active = lane.stages.some(row => workerClass(row.status) === "live");
        return <section className="crew-lane-box" key={lane.id}>
          <div className="crew-lane-head">
            <div className="lane-title-group">
              <span className="lane-seq-pill">LANE {lane.id}</span>
              <strong>{lane.label}</strong>
            </div>
            <Badge tone={active ? "positive" : "neutral"}>{active ? "Active Flow" : "Standby"}</Badge>
          </div>
          {lane.id === "B" && (
            <div className="lane-config-bar">
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
          <div className="pipeline-flow-track">
            {lane.stages.map((row, idx) => {
              const tone = workerClass(row.status);
              const isFlowing = tone === "live";
              return (
                <Fragment key={row.name}>
                  <div className="pipeline-node">
                    <span className="pipeline-step-idx">STAGE 0{idx + 1}</span>
                    <CrewCard row={row} />
                  </div>
                  {idx < lane.stages.length - 1 && (
                    <div className={`pipeline-bus ${isFlowing ? "flowing" : ""}`} aria-hidden="true">
                      <div className="bus-wire" />
                      <div className="bus-particle" />
                      <div className="bus-arrow">▶</div>
                    </div>
                  )}
                </Fragment>
              );
            })}
          </div>
        </section>;
      })}
      <p className="small muted" style={{ marginTop: 14 }}>
        Three strategy lanes share one feed. Each lane has its own Kaze (analysis), Mizu (risk), Nanao (AI confirmation) and Hikari (delivery). No model can override a failed gate. Strategy C trades Asian range liquidity sweeps.
      </p>
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

function AdminUsers({
  settings,
  refresh,
  action,
  busy,
}: {
  settings: Settings;
  refresh: () => Promise<void>;
  action: (w: () => Promise<void>) => void;
  busy: boolean;
}) {
  const [search, setSearch] = useState("");
  const [newKey, setNewKey] = useState<{ key: string; label: string } | null>(null);
  const [newLabel, setNewLabel] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLabelText, setEditLabelText] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [filterTab, setFilterTab] = useState<"all" | "active" | "revoked">("all");

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!newLabel.trim()) return;
    action(async () => {
      const res = await send<{ key: string; id: string; label: string }>("/api/admin/keys", "POST", { label: newLabel.trim() });
      setNewKey({ key: res.key, label: res.label });
      setNewLabel("");
      await refresh();
    });
  }

  async function saveEdit(id: string) {
    if (!editLabelText.trim()) return;
    action(async () => {
      await api("/api/admin/keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, label: editLabelText.trim() }),
      });
      setEditingId(null);
      await refresh();
    });
  }

  async function toggleRevoke(key: AccessKey) {
    const nextRevoked = !key.revoked;
    action(async () => {
      await api("/api/admin/keys", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: key.id, label: key.label, revoked: nextRevoked }),
      });
      await refresh();
    });
  }

  async function deleteKey(id: string, label: string) {
    if (!confirm(`Permanently delete user "${label}"? This key will be erased.`)) return;
    action(async () => {
      await api(`/api/admin/keys?id=${encodeURIComponent(id)}&permanent=true`, { method: "DELETE" });
      await refresh();
    });
  }

  function copyText(text: string, id: string) {
    void navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  }

  const keys = settings.keys || [];
  const filtered = keys.filter(k => {
    const matchSearch = k.label.toLowerCase().includes(search.toLowerCase()) || (k.token && k.token.includes(search));
    const matchTab = filterTab === "all" || (filterTab === "active" ? !k.revoked : k.revoked);
    return matchSearch && matchTab;
  });

  return (
    <section className="panel access-panel modern-users-card">
      <PanelHeading title="User Access Management" as="h3">
        <Badge tone="positive">{keys.filter(k => !k.revoked).length} active users</Badge>
      </PanelHeading>

      {/* New Key Generated Success Banner with Immediate 1-Click Copy */}
      {newKey && (
        <div className="new-key-banner">
          <div className="new-key-header">
            <CheckCircle2 size={20} className="good" />
            <div>
              <strong>New User Access Key Generated!</strong>
              <p className="small muted">Key for <b>{newKey.label}</b>. Copy this key now to share privately.</p>
            </div>
          </div>
          <div className="new-key-copy-box">
            <input value={newKey.key} readOnly onFocus={e => e.currentTarget.select()} className="new-key-input" />
            <button
              type="button"
              className="primary new-key-copy-btn"
              onClick={() => copyText(newKey.key, "new-key-btn")}
            >
              {copiedId === "new-key-btn" ? <Check size={16} /> : <Copy size={16} />}
              {copiedId === "new-key-btn" ? "Copied!" : "Copy Key"}
            </button>
            <button type="button" className="close-banner-btn" onClick={() => setNewKey(null)} title="Close">
              <X size={16} />
            </button>
          </div>
        </div>
      )}

      {/* Add User Bar & Search */}
      <div className="users-action-row">
        <form className="add-user-inline-form" onSubmit={create}>
          <input
            value={newLabel}
            onChange={e => setNewLabel(e.target.value)}
            placeholder="Enter new user name / label…"
            required
            maxLength={80}
            disabled={busy}
          />
          <button className="primary" type="submit" disabled={busy || !newLabel.trim()}>
            <UserPlus size={16} /> Add User
          </button>
        </form>

        <div className="user-search-wrapper">
          <Search size={15} className="search-icon" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search users…"
            className="user-search-input"
          />
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="user-filter-tabs segment-group" style={{ marginBlock: "10px 14px" }}>
        {(["all", "active", "revoked"] as const).map(tab => (
          <button
            key={tab}
            type="button"
            className={filterTab === tab ? "primary small" : "small"}
            onClick={() => setFilterTab(tab)}
          >
            {tab === "all" ? `All (${keys.length})` : tab === "active" ? `Active (${keys.filter(k => !k.revoked).length})` : `Revoked (${keys.filter(k => k.revoked).length})`}
          </button>
        ))}
      </div>

      {/* Users Table */}
      {filtered.length > 0 ? (
        <div className="users-table-container">
          <table className="users-management-table" role="table">
            <thead>
              <tr>
                <th scope="col">User / Label</th>
                <th scope="col">Status</th>
                <th scope="col">Key Token</th>
                <th scope="col" style={{ textAlign: "end" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(key => {
                const isEditing = editingId === key.id;
                const tokenToShow = key.token || key.id;
                const isCopied = copiedId === key.id;
                return (
                  <tr key={key.id} className={key.revoked ? "user-row-revoked" : ""}>
                    <td>
                      {isEditing ? (
                        <div className="inline-edit-box">
                          <input
                            value={editLabelText}
                            onChange={e => setEditLabelText(e.target.value)}
                            maxLength={80}
                            autoFocus
                          />
                          <button type="button" className="primary tiny-btn" onClick={() => void saveEdit(key.id)} disabled={busy}><Check size={14} /></button>
                          <button type="button" className="tiny-btn" onClick={() => setEditingId(null)}><X size={14} /></button>
                        </div>
                      ) : (
                        <div className="user-name-cell">
                          <strong>{key.label}</strong>
                          <button
                            type="button"
                            className="inline-pencil-btn"
                            title="Edit label"
                            onClick={() => { setEditingId(key.id); setEditLabelText(key.label); }}
                          >
                            <Edit2 size={13} />
                          </button>
                        </div>
                      )}
                    </td>
                    <td>
                      <Badge tone={key.revoked ? "neutral" : "positive"}>
                        {key.revoked ? "Revoked" : "Active"}
                      </Badge>
                    </td>
                    <td>
                      <div className="token-copy-cell">
                        <code>{tokenToShow.slice(0, 10)}…{tokenToShow.slice(-4)}</code>
                        <button
                          type="button"
                          className="table-copy-btn"
                          title="Copy full key token"
                          onClick={() => copyText(tokenToShow, key.id)}
                        >
                          {isCopied ? <Check size={13} className="good" /> : <Copy size={13} />}
                        </button>
                      </div>
                    </td>
                    <td style={{ textAlign: "end" }}>
                      <div className="table-actions-cell">
                        <button
                          type="button"
                          className={key.revoked ? "restore-btn" : "revoke-btn"}
                          disabled={busy}
                          onClick={() => void toggleRevoke(key)}
                          title={key.revoked ? "Restore access" : "Revoke access"}
                        >
                          {key.revoked ? "Restore" : "Revoke"}
                        </button>
                        <button
                          type="button"
                          className="danger-button delete-btn"
                          disabled={busy}
                          onClick={() => void deleteKey(key.id, key.label)}
                          title="Delete user permanently"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState>No matching user keys found.</EmptyState>
      )}
    </section>
  );
}

function AdminPerformance({ action, busy }: { action: (w: () => Promise<void>) => void; busy: boolean }) {
  const [data, setData] = useState<{
    signals_count: number; shadow_count: number; fills_count: number;
    wins: number; losses: number; win_rate: number; total_pnl_per_lot: number;
    signals: any[];
  } | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      setData(await api<any>("/api/admin/performance"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => { void load(); }, []);

  async function handleReset() {
    if (!confirm("⚠️ RESET PERFORMANCE DATA?\n\nThis will clear all current signals and shadow trades, archive history to a backup, and reset counters. Continue?")) return;
    action(async () => {
      const res = await api<{ reset: boolean; archive_id: string }>("/api/admin/performance/reset", { method: "POST" });
      setMsg(`Performance data reset successfully! Archived as ${res.archive_id}`);
      await load();
    });
  }

  function handleExport() {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `goldsignal-performance-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="panel access-panel admin-performance-card">
      <PanelHeading title="Admin Performance Controls" as="h3">
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" onClick={handleExport} disabled={!data || !data.signals_count}>
            <Download size={14} /> Export JSON
          </button>
          <button type="button" className="danger-button" onClick={() => void handleReset()} disabled={busy}>
            <RotateCcw size={14} /> Reset Performance Data
          </button>
        </div>
      </PanelHeading>

      {msg && <p className="small good" style={{ marginBottom: 10 }}>{msg}</p>}
      {error && <p className="small warn">{error}</p>}

      {data && (
        <>
          <div className="admin-perf-grid">
            <div className="admin-perf-card">
              <span className="perf-label">TOTAL SIGNALS</span>
              <strong className="perf-val">{data.signals_count}</strong>
            </div>
            <div className="admin-perf-card">
              <span className="perf-label">COMPLETED FILLS</span>
              <strong className="perf-val">{data.fills_count}</strong>
            </div>
            <div className="admin-perf-card">
              <span className="perf-label">WIN RATE</span>
              <strong className={`perf-val ${data.win_rate >= 50 ? "good" : ""}`}>{data.win_rate}%</strong>
              <small className="muted">{data.wins}W / {data.losses}L</small>
            </div>
            <div className="admin-perf-card">
              <span className="perf-label">TOTAL P/L PER LOT</span>
              <strong className={`perf-val ${data.total_pnl_per_lot >= 0 ? "good" : "warn"}`}>${data.total_pnl_per_lot.toFixed(2)}</strong>
            </div>
            <div className="admin-perf-card">
              <span className="perf-label">SHADOW SIMULATIONS</span>
              <strong className="perf-val">{data.shadow_count}</strong>
            </div>
          </div>

          <h4 style={{ margin: "18px 0 8px", fontSize: "0.875rem", fontWeight: 700 }}>Recent Executed Signals ({data.signals.length})</h4>
          {data.signals.length > 0 ? (
            <div className="admin-signals-table-wrap">
              <table className="report-breakdown">
                <thead>
                  <tr>
                    <th>Signal ID</th>
                    <th>Side</th>
                    <th>Entry Band</th>
                    <th>Status</th>
                    <th>Result / Lot</th>
                  </tr>
                </thead>
                <tbody>
                  {data.signals.map(s => (
                    <tr key={s.id}>
                      <td><code>{s.id}</code></td>
                      <td><Badge tone={s.direction === "SELL" ? "negative" : "positive"}>{s.direction}</Badge></td>
                      <td>{s.entry ? `${s.entry[0]} – ${s.entry[1]}` : "–"}</td>
                      <td><Badge>{s.status}</Badge></td>
                      <td className={s.result_per_lot > 0 ? "good" : s.result_per_lot < 0 ? "warn" : ""}>
                        {s.result_per_lot != null ? `$${s.result_per_lot.toFixed(2)}` : "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState>No trade records found.</EmptyState>
          )}
        </>
      )}
    </section>
  );
}

export function AdminSettings({ view }: { view: AdminView | undefined }) {
  const [settings, setSettings] = useState<Settings | null>(null);
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
      {view === "admin-ai" && message && <p role="status">{message}</p>}
      {settings ? <>
        <div hidden={view !== "admin-users"}>
          <AdminUsers settings={settings} refresh={refresh} action={action} busy={busy} />
        </div>

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
        <div hidden={view !== "admin-performance"}><AdminPerformance action={action} busy={busy} /></div>
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
