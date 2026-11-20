import { Fragment, useEffect, useRef, useState, type CSSProperties, type FormEvent, type ReactNode } from "react";
import {
  Activity, AlertTriangle, ArrowUp, BrainCircuit, Check, CheckCircle2, Copy, Cpu,
  Dices, Download, Edit2, Gauge, Key, LineChart, Megaphone, MessageSquare, Plus,
  Radio, RefreshCw, RotateCcw, RotateCw, Search, Send, ShieldCheck, Sparkles,
  Trash2, TrendingUp, UserPlus, Users, Waypoints, Wind, X
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

const OPERATOR_ICONS: Record<string, ReactNode> = {
  kuro: <Radio size={12} />,
  kaze: <Wind size={12} />,
  mizu: <ShieldCheck size={12} />,
  nanao: <BrainCircuit size={12} />,
  hayate: <Cpu size={12} />,
  ryu: <Send size={12} />,
  shinra: <LineChart size={12} />,
  taka: <TrendingUp size={12} />,
  ren: <Waypoints size={12} />,
  kai: <Dices size={12} />,
  hikari: <Megaphone size={12} />,
};

const OPERATOR_COLORS: Record<string, string> = {
  kuro: "#38bdf8",
  kaze: "#f5a524",
  mizu: "#60a5fa",
  nanao: "#34d399",
  hayate: "#fb923c",
  ryu: "#f87171",
  shinra: "#a78bfa",
  taka: "#fbbf24",
  ren: "#2dd4bf",
  kai: "#4ade80",
  hikari: "#f472b6",
};

function OperatorAvatar({ name, tone }: { name: string; tone: string }) {
  const icon = OPERATOR_ICONS[name] ?? <Activity size={20} />;
  const color = OPERATOR_COLORS[name] ?? "#94a3b8";
  return (
    <div className={`operator-badge tone-${tone}`}>
      <div className="operator-avatar" style={{ "--op": color } as CSSProperties}>
        <span className="operator-icon">{icon}</span>
        <span className="operator-status-dot" />
      </div>
    </div>
  );
}

function CrewCard({ row, isCore = false }: { row: WorkerRow; isCore?: boolean }) {
  const tone = workerClass(row.status);
  return (
    <article className={`crew-card crew-${tone} ${isCore ? "crew-core" : ""}`} title={row.reason ?? row.role}>
      <span className="crew-bubble">{shortReason(row.reason) ?? row.status}</span>
      <div className="crew-avatar-frame">
        <OperatorAvatar name={row.name} tone={tone} />
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
            <span className="hub-tag">CORE SERVICES</span>
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
              <span className="division-badge">RESEARCH DESK</span>
              <strong style={{ fontSize: "0.875rem" }}>Shinra Quant Desk</strong>
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
        <strong>Execution Desk</strong>
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
