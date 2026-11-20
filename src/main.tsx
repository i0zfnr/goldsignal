import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Bell, CalendarDays, Calculator, ChartCandlestick, ChartNoAxesCombined, CircleAlert,
  History, Menu, MessageSquare, Settings2, Upload, UserRound, Users, X, Activity,
  Gauge, ZoomIn, ZoomOut, Check, Crop, Trash2
} from "lucide-react";
import { Chart } from "./chart";
import { Performance } from "./performance";
import { LotSize } from "./lot";
import { Access, AdminSettings, adminViews, ApiError, api, type AdminView } from "./access";
import { InstallButton } from "./install";
import { CandleClock } from "./candle-clock";
import type { BAnalysis, BZone, Dashboard, EntryCheck, Frame, Signal } from "./types";
import { applyTheme, readTheme, ThemeToggle } from "./theme";
import { Badge, EmptyState, LoadingState, PanelHeading } from "./ui";
import "@fontsource/geist/latin-400.css";
import "@fontsource/geist/latin-500.css";
import "@fontsource/geist/latin-600.css";
import "@fontsource/geist/latin-700.css";
import "./style.css";

declare const __SW_VERSION__: string;
const serviceWorkerUrl = `/sw.js?v=${__SW_VERSION__}`;

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
  ["lot", "Lot size"],
  ["history", "Signal History"],
  ["news", "USD Calendar"],
  ["alerts", "Notifications"],
] as const;
type DashboardView = typeof dashboardViews[number][0] | AdminView | "profile";
const viewIcons = {
  signal: ChartCandlestick, performance: ChartNoAxesCombined, lot: Calculator, history: History, news: CalendarDays,
  alerts: Bell, profile: UserRound, "admin-users": Users, "admin-workers": Activity, "admin-ai": Settings2,
  "admin-chat": MessageSquare, "admin-performance": Gauge, "admin-errors": CircleAlert,
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

function PhotoCropModal({
  file,
  onApply,
  onCancel,
}: {
  file: File;
  onApply: (dataUrl: string) => void;
  onCancel: () => void;
}) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [zoom, setZoom] = useState(1.1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, panX: 0, panY: 0 });

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.src = url;
    img.onload = () => setImage(img);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function handlePointerDown(e: React.PointerEvent) {
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
    try { (e.target as HTMLElement).setPointerCapture(e.pointerId); } catch {}
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!dragging) return;
    const dx = e.clientX - dragStart.current.x;
    const dy = e.clientY - dragStart.current.y;
    setPan({ x: dragStart.current.panX + dx, y: dragStart.current.panY + dy });
  }

  function handlePointerUp(e: React.PointerEvent) {
    setDragging(false);
    try { (e.target as HTMLElement).releasePointerCapture(e.pointerId); } catch {}
  }

  function applyCrop() {
    if (!image) return;
    const canvas = document.createElement("canvas");
    canvas.width = 96;
    canvas.height = 96;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const viewportSize = 240;
    const minDim = Math.min(image.naturalWidth, image.naturalHeight);
    const scale = (minDim / viewportSize) / zoom;

    const cropW = viewportSize * scale;
    const cropH = viewportSize * scale;
    const centerX = (image.naturalWidth / 2) - (pan.x * scale);
    const centerY = (image.naturalHeight / 2) - (pan.y * scale);

    const sx = Math.max(0, Math.min(image.naturalWidth - cropW, centerX - cropW / 2));
    const sy = Math.max(0, Math.min(image.naturalHeight - cropH, centerY - cropH / 2));

    ctx.drawImage(image, sx, sy, cropW, cropH, 0, 0, 96, 96);

    for (const q of [0.82, 0.65, 0.48, 0.32]) {
      const dataUrl = canvas.toDataURL("image/jpeg", q);
      if (dataUrl.length <= 7000) {
        onApply(dataUrl);
        return;
      }
    }
    onApply(canvas.toDataURL("image/jpeg", 0.28));
  }

  return (
    <div className="crop-modal-overlay" role="dialog" aria-modal="true" aria-labelledby="crop-title">
      <div className="crop-modal-card">
        <div className="crop-modal-header">
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <Crop size={18} className="good" />
            <h3 id="crop-title" style={{ margin: 0 }}>Crop Profile Photo</h3>
          </div>
          <button type="button" className="close-btn" onClick={onCancel} aria-label="Close"><X size={18} /></button>
        </div>
        <p className="small muted">Drag photo to adjust position. Use slider to zoom in or out.</p>

        <div
          className="crop-viewport"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
        >
          {image && (
            <img
              src={image.src}
              alt="Crop preview"
              draggable={false}
              className="crop-preview-img"
              style={{
                transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              }}
            />
          )}
          <div className="crop-circle-frame" />
        </div>

        <div className="crop-slider-row">
          <button type="button" className="tiny-zoom-btn" onClick={() => setZoom(z => Math.max(0.6, z - 0.1))}><ZoomOut size={16} /></button>
          <input
            type="range"
            min="0.6"
            max="3.0"
            step="0.05"
            value={zoom}
            onChange={e => setZoom(Number(e.target.value))}
            className="crop-zoom-slider"
          />
          <button type="button" className="tiny-zoom-btn" onClick={() => setZoom(z => Math.min(3.0, z + 0.1))}><ZoomIn size={16} /></button>
        </div>

        <div className="crop-modal-footer">
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" className="primary" onClick={applyCrop}>
            <Check size={16} /> Apply & Use Photo
          </button>
        </div>
      </div>
    </div>
  );
}

function Profile() {
  const [profile, setProfile] = useState<ViewerProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [cropFile, setCropFile] = useState<File | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    api<ViewerProfile>("/api/viewer-profile", { signal: abort.signal })
      .then(result => { if (!abort.signal.aborted) setProfile(result); })
      .catch(() => { if (!abort.signal.aborted) setMessage("Could not load your profile."); });
    return () => abort.abort();
  }, []);

  function choosePhoto(input: HTMLInputElement) {
    const file = input.files?.[0];
    input.value = "";
    if (!file || busy) return;
    if (file.size > 12 * 1024 * 1024) {
      setMessage("Choose a photo smaller than 12 MB.");
      return;
    }
    setMessage("");
    setCropFile(file);
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
      setMessage("Profile saved successfully.");
    } catch (failure) {
      setMessage((failure as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel below profile-panel modern-profile-card" id="profile" aria-labelledby="profile-title">
      <PanelHeading id="profile-title" title="Trader Account Profile">
        {profile && <Badge tone={profile.role === "admin" ? "accent" : "positive"}>{profile.role === "admin" ? "Administrator" : "VIP Trader"}</Badge>}
      </PanelHeading>

      {cropFile && (
        <PhotoCropModal
          file={cropFile}
          onApply={dataUrl => {
            setProfile(prev => prev && { ...prev, photo: dataUrl });
            setCropFile(null);
            setMessage("Photo cropped. Click 'Save Profile' to apply changes.");
          }}
          onCancel={() => setCropFile(null)}
        />
      )}

      {profile ? (
        <form className="profile-form modern-profile-form" onSubmit={event => void save(event)}>
          <div className="profile-photo-hero">
            <div className="profile-avatar-container">
              {profile.photo ? (
                <img src={profile.photo} width="84" height="84" alt="Your profile photo" className="profile-avatar-img" />
              ) : (
                <span className="profile-photo-placeholder" aria-hidden="true">{profile.display_name.trim()[0]?.toUpperCase() || "G"}</span>
              )}
            </div>

            <div className="profile-photo-controls">
              <strong>Account Portrait</strong>
              <p className="small muted">Upload and crop your profile avatar. PNG or JPEG up to 12 MB.</p>
              <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
                <label className="photo-picker">
                  <input type="file" accept="image/*" disabled={busy} aria-label="Profile photo"
                    onChange={event => void choosePhoto(event.currentTarget)} />
                  <span aria-hidden="true"><Upload size={16} /> Choose & Crop Photo</span>
                </label>
                {profile.photo && (
                  <button type="button" disabled={busy} onClick={() => { setProfile({ ...profile, photo: null }); setMessage(""); }}>
                    <Trash2 size={15} /> Remove
                  </button>
                )}
              </div>
            </div>
          </div>

          <div className="profile-fields-grid">
            <label>Display Name
              <input
                value={profile.display_name}
                maxLength={60}
                autoComplete="nickname"
                disabled={busy}
                placeholder="Enter trader alias…"
                onChange={event => setProfile({ ...profile, display_name: event.target.value })}
              />
            </label>
            <label>Account Role
              <input value={profile.role === "admin" ? "Master Admin" : "Viewer Access"} disabled readOnly style={{ opacity: 0.75 }} />
            </label>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
            <button type="submit" className="primary" disabled={busy} style={{ minWidth: 140 }}>
              {busy ? "Saving…" : "Save Profile"}
            </button>
            {message && <p className="small good" role="status">{message}</p>}
          </div>
        </form>
      ) : !message && <LoadingState>Loading profile…</LoadingState>}
    </section>
  );
}

function BAnalysisPanel({ analysis, displayTime, price }: {
  analysis: BAnalysis; displayTime: (ts: number) => string; price: (value?: number | null) => string;
}) {
  const m15 = analysis.m15;
  const m5 = analysis.m5;
  const nextStep = analysis.next_step;
  const reason = analysis.reason;
  const candidate = analysis.candidate;
  const currentPrice = analysis.price;
  const nearestSell = analysis.nearest_sell;
  const nearestBuy = analysis.nearest_buy;

  const biasLabel = (b: { direction: string }) => {
    if (b.direction === "bullish") return <span className="good font-semibold">Bullish</span>;
    if (b.direction === "bearish") return <span className="warn font-semibold">Bearish</span>;
    return <span className="muted">Neutral</span>;
  };

  const stepBadge = (step: string) => {
    let tone: "positive" | "negative" | "neutral" | "accent" = "neutral";
    if (step === "ENTRY READY" || step.includes("BUY")) {
      tone = "positive";
    } else if (step.includes("SELL")) {
      tone = "negative";
    } else if (step.includes("WAITING") || step.includes("REJECTION") || step.includes("CONFIRMATION")) {
      tone = "accent";
    }
    return <span className={`badge badge-${tone} small`}>{step}</span>;
  };

  const isInside = (z: BZone) => currentPrice >= z.bottom && currentPrice <= z.top;
  const distanceToEdge = (z: BZone) => {
    if (isInside(z)) return "🎯 INSIDE";
    const dist = Math.min(Math.abs(currentPrice - z.top), Math.abs(currentPrice - z.bottom));
    return `${dist.toFixed(2)} away`;
  };

  return (
    <div className="b-analysis-panel" style={{ marginTop: 8 }}>
      {/* 1. Multi-Timeframe Structure - Compact */}
      <details className="insight-details" open>
        <summary>Multi-Timeframe Structure</summary>
        <div className="compact-mtf-row" style={{ display: "flex", justifyContent: "space-between", marginBlock: "6px 2px", fontSize: ".8125rem" }}>
          <div><strong>M15 Direction:</strong> {biasLabel(m15)}</div>
          <div><strong>M5 Context:</strong> {biasLabel(m5 ?? { direction: "neutral" })}</div>
        </div>
        <p className="small muted" style={{ marginTop: 2 }}>
          {m15.direction === "neutral" ? "Neutral M15: watch zones active, waiting for structure break." :
           m15.direction === "bearish" ? "Bearish M15: eligible for SELL setups on M5 rejection." :
           "Bullish M15: eligible for BUY setups on M5 rejection."}
        </p>
      </details>

      {/* 2. Zone Rationale - up to 3 SELL + 3 BUY high-confidence zones */}
      <details className="insight-details" open>
        <summary>Zone Rationale ({analysis.zones.filter(z => z.direction === "SELL").length} SELL · {analysis.zones.filter(z => z.direction === "BUY").length} BUY)</summary>
        <div style={{ display: "grid", gap: 6, marginTop: 6 }}>
          {analysis.zones.length > 0 ? (
            analysis.zones.map(z => {
              const isSell = z.direction === "SELL";
              return (
                <div key={z.id} className={`compact-zone-item ${isSell ? "sell" : "buy"}`}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>
                      <strong className={isSell ? "warn" : "good"}>
                        {isSell ? "🔴 M15 Supply" : "🟢 M15 Demand"}:
                      </strong>{" "}
                      {price(z.bottom)} – {price(z.top)}
                      <small style={{ marginLeft: 6, opacity: 0.85, fontSize: "0.75rem" }}>
                        ({z.mitigated ? "Tested" : "Fresh"} · Power {z.power ?? 8}/10)
                      </small>
                    </span>
                    <span className="small muted">{distanceToEdge(z)}</span>
                  </div>
                </div>
              );
            })
          ) : (
            <p className="small muted">No active high-confidence liquidity zones near price.</p>
          )}
        </div>
      </details>

      {/* 3. Action & Validation - Compact */}
      <details className="insight-details" open>
        <summary>Action & Validation</summary>
        <div style={{ marginTop: 6 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
            <span className="small"><strong>Status:</strong></span>
            {stepBadge(nextStep)}
          </div>
          {reason && <p className="small muted" style={{ marginTop: 4, lineHeight: 1.35 }}>{reason}</p>}

          {candidate && (
            <div className="compact-candidate-card" style={{ marginTop: 6, padding: "6px 8px", background: "rgba(34, 197, 94, 0.08)", border: "1px solid rgba(34, 197, 94, 0.25)", borderRadius: 6 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span className={`badge small grade-${(candidate.grade ?? "A").toLowerCase().replace("+", "-plus")}`}>
                  GRADE {candidate.grade ?? "A"}
                </span>
                <span className="small muted">
                  {candidate.grade === "A+" ? "⭐️⭐️⭐️⭐️ Highest" : candidate.grade === "A" ? "⭐️⭐️⭐️ High" : candidate.grade === "B+" ? "⭐️⭐️ Good" : "⭐️ Standard"}
                </span>
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontWeight: 700, fontSize: "0.8125rem" }}>
                <span>ENTRY BAND:</span>
                <span className="good">{price(candidate.entry[0])} – {price(candidate.entry[1])}</span>
              </div>
              <div className="small muted" style={{ display: "flex", justifyContent: "space-between", marginTop: 2 }}>
                <span>SL: <strong className="warn">{price(candidate.stop)}</strong></span>
                <span>TP1: <strong className="good">{price(candidate.targets[0])}</strong></span>
              </div>
            </div>
          )}
        </div>
      </details>

      {/* 4. Shinra Quantitative Intelligence & 1,000-Pattern Match */}
      {analysis.pattern_research && (
        <details className="insight-details" open>
          <summary>Shinra Pattern Intelligence (1,000 Candles)</summary>
          <div style={{ marginTop: 6, display: "grid", gap: 6 }}>
            <div className="compact-zone-item" style={{ background: "rgba(168, 85, 247, 0.1)", borderLeft: "3px solid #a855f7" }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span><strong>Shinra Edge:</strong> {analysis.pattern_research.shinra.edge_score}% Win Expectancy</span>
                <span className="badge small badge-accent">{analysis.pattern_research.kai.matches} Matches</span>
              </div>
              <p className="small muted" style={{ marginTop: 3, marginBottom: 0 }}>
                {analysis.pattern_research.taka.pattern} · {analysis.pattern_research.ren.status}
              </p>
            </div>
          </div>
        </details>
      )}
    </div>
  );
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
    const interval = setInterval(refresh, 3000);
    return () => {
      window.removeEventListener("focus", refresh);
      clearInterval(interval);
    };
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
      const registration = await navigator.serviceWorker.register(serviceWorkerUrl, { updateViaCache: "none" });
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

function MarketTicker({ data, error }: { data: Dashboard | null; error: string }) {
  const last = data?.candles.at(-1);
  const previous = data?.candles.at(-2);
  const change = last && previous ? last.close - previous.close : null;
  const percent = change != null && previous ? (change / previous.close) * 100 : null;
  const rising = (change ?? 0) >= 0;
  const live = !error && ["LIVE", "DEMO"].includes(data?.status ?? "");
  const state = error ? "STALE" : data?.status ?? "CONNECTING";
  return (
    <div className="market-ticker" role="status" aria-label="Live market quote">
      <div className="ticker-symbol"><strong>{data?.symbol ?? "XAUUSD"}</strong><small>Gold · Spot</small></div>
      <div className="ticker-price">{price(last?.close ?? data?.quote?.bid)}</div>
      <span className={`ticker-change ${rising ? "up" : "down"}`}>
        {change == null ? "–" : `${rising ? "▲" : "▼"} ${Math.abs(change).toFixed(2)}${percent == null ? "" : ` (${Math.abs(percent).toFixed(2)}%)`}`}
      </span>
      <span className="ticker-spacer" />
      <div className="ticker-quote">
        <span>Bid <b>{price(data?.quote?.bid)}</b></span>
        <span>Ask <b>{price(data?.quote?.ask)}</b></span>
      </div>
      <span className={`ticker-live ${error || data?.status === "STALE" ? "warn" : ""}`}>
        <span className="status-dot" aria-hidden="true" />{live ? state.toUpperCase() : state}
      </span>
    </div>
  );
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
      if (!abort.signal.aborted) timer = window.setTimeout(poll, 3000);
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
  const b_analysis = data?.b_analysis;
  const candidateReady = b_analysis?.next_step === "ENTRY READY" && b_analysis.candidate ? b_analysis.candidate : null;
  const signal: Signal | null = data?.active ?? (candidateReady ? { ...candidateReady, status: "ENTRY READY" } : null);
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
      <MarketTicker data={data} error={error} />
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
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                <span className="small muted">{signal.strategy ?? "M15 baseline"}</span>
                {signal.grade && (
                  <span className={`badge small grade-${signal.grade.toLowerCase().replace("+", "-plus")}`}>
                    CONFIDENCE {signal.grade}
                  </span>
                )}
              </div>
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
          <Chart
            key={frame}
            frame={frame}
            candles={data?.frame === frame ? data.candles : []}
            signal={signal ?? null}
            quote={!error && ["LIVE", "DEMO"].includes(data?.status ?? "") ? data?.quote ?? null : null}
            b_analysis={data?.b_analysis ?? null}
          />
          <div className="chart-footer">
            <span><i className="key entry" /> Entry zone</span>
            <span><i className="key stop" /> Stop</span>
            <span><i className="key target" /> Targets</span>
            {data?.b_analysis?.nearest_sell && (
              <span><i className="key" style={{ background: "var(--sell)" }} /> M15 Sell zone ({price(data.b_analysis.nearest_sell.bottom)}–{price(data.b_analysis.nearest_sell.top)})</span>
            )}
            {data?.b_analysis?.nearest_buy && (
              <span><i className="key" style={{ background: "var(--buy)" }} /> M15 Buy zone ({price(data.b_analysis.nearest_buy.bottom)}–{price(data.b_analysis.nearest_buy.top)})</span>
            )}
          </div>
        </section>
          <section className="panel side-card insight" id="insight" aria-labelledby="insight-title">
            <div className="panel-heading"><h2 id="insight-title">Analysis</h2>
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
            {data?.b_analysis && <BAnalysisPanel analysis={data.b_analysis} displayTime={displayTime} price={price} />}
          </section>
      </div>
      </div>
      <div className="dashboard-view" hidden={view !== "performance"}>
        {data ? <Performance revision={data.history.map(item => `${item.id}:${item.status}`).join(",")} /> : <p role="status">Loading performance…</p>}
      </div>
      <div className="dashboard-view" hidden={view !== "lot"}>
        <LotSize />
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
                <Badge tone={item.status === "STOPPED" ? "negative" : (item.status === "COMPLETED" || item.status.includes("SECURED") || item.status.includes("TP")) ? "positive" : "neutral"}>
                  {item.status.replace("_", " ")}
                </Badge>
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

    {/* Mobile Trading App Bottom Navigation Bar */}
    <nav className="mobile-trading-bar" aria-label="Mobile Navigation">
      <button
        type="button"
        className={`mobile-tab-btn ${view === "signal" ? "active" : ""}`}
        onClick={event => { select(event as any, null); setView("signal"); }}
      >
        <ChartCandlestick size={19} />
        <span>Trade</span>
      </button>
      <button
        type="button"
        className={`mobile-tab-btn ${view === "lot" ? "active" : ""}`}
        onClick={() => setView("lot")}
      >
        <Calculator size={19} />
        <span>Lot/PnL</span>
      </button>
      <button
        type="button"
        className={`mobile-tab-btn ${view === "performance" ? "active" : ""}`}
        onClick={() => setView("performance")}
      >
        <ChartNoAxesCombined size={19} />
        <span>Stats</span>
      </button>
      <button
        type="button"
        className={`mobile-tab-btn ${view === "history" ? "active" : ""}`}
        onClick={() => setView("history")}
      >
        <History size={19} />
        <span>Signals</span>
      </button>
      <button
        type="button"
        className={`mobile-tab-btn ${view === "alerts" ? "active" : ""}`}
        onClick={() => setView("alerts")}
      >
        <Bell size={19} />
        <span>Alerts</span>
      </button>
      {hasAdmin && (
        <button
          type="button"
          className={`mobile-tab-btn ${view.startsWith("admin-") ? "active" : ""}`}
          onClick={() => setView("admin-workers")}
        >
          <Activity size={19} />
          <span>Admin</span>
        </button>
      )}
    </nav>

    <footer><a href="https://www.tradingview.com/">TradingView Lightweight Charts™</a> · <a href="/NOTICE">Attribution notice</a> · <a href="https://shadcndashboard.dev/">Shadcn Dashboard</a></footer>
  </div>;
}

if ("serviceWorker" in navigator) {
  void navigator.serviceWorker.register(serviceWorkerUrl, { updateViaCache: "none" }).catch(() => {});
}

applyTheme(readTheme());
createRoot(document.getElementById("root")!).render(<Access
  dashboard={(role, signOut, expired) => <App role={role} signOut={signOut} expired={expired} />} />);
