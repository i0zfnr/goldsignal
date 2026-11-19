import type { CandlestickData, UTCTimestamp } from "lightweight-charts";

export type Candle = CandlestickData<UTCTimestamp>;
export type EntryCheck = { valid: boolean; reason: string; price: number | null; side: "Bid" | "Ask";
  ratios: number[] | null; checked_at: number };
export type Frame = "M1" | "M5" | "M15" | "M30" | "H1" | "H4";
type Pattern = { rsi8: number | null; history: number; matches: number; next4_bps: number | null };
type Evidence = { reason: string; grade: string; pattern?: Pattern };
export type Signal = {
  id: string; direction: "BUY" | "SELL"; created: number; expiry: number;
  strategy?: string;
  entry: [number, number]; initial_stop: number; stop: number; reference: number;
  targets: number[]; fill: number | null; status: string; hits: number;
  max_spread?: number; hold_seconds?: number;
  filled_at?: number; exits?: { time: number; price: number; kind: string }[];
  evidence: Evidence;
  review?: { provider: string; reason: string };
};
type News = { title: string; time: number; source: string; url: string | null; first_seen?: number; impact?: "high" | "medium";
  actual?: string; forecast?: string; previous?: string };
export type BZone = {
  id: string; direction: string; top: number; bottom: number;
  created: number; invalidated?: number | null; expired: number;
  swing?: { price: number; time: number; confirmed?: number } | null;
};

export type BAnalysis = {
  version: string; now: number; price: number;
  h1: { direction: string; high_at?: number | null; low_at?: number | null; highs: number[]; lows: number[] };
  m15: { direction: string; high_at?: number | null; low_at?: number | null; highs: number[]; lows: number[] };
  zones: BZone[];
  nearest_sell?: BZone | null;
  nearest_buy?: BZone | null;
  next_step: string; reason?: string | null;
  candidate?: Signal | null;
  rejection?: { time: number; high: number; low: number; close: number } | null;
  trigger?: { time: number; close: number; bar: { time: number; open: number; high: number; low: number; close: number } } | null;
  zone?: BZone | null;
};

export type Dashboard = {
  symbol: string; mode: string; status: string; clock: number; heartbeat: number | null;
  quote: { bid: number; ask: number; time: number } | null;
  session: { open: boolean; opening: number; cutoff: number; next_myt: string | null; active: string[]; next: string[] };
  revision: number; candles: Candle[]; active: Signal | null; history: Signal[];
  frame: Frame;
  events: { id: string; kind: string; time: number; stop: number; note: string | null }[];
  candidate: { decision: string; reason: string; evidence: Evidence; evaluated?: number } | null;
  entry_check?: EntryCheck | null;
  scan?: { reason: string; closed_at?: number } | null;
  scalp_scan?: string | null;
  b_analysis?: BAnalysis | null;
  calendar: { restriction: string | null; events: News[]; headlines: News[];
    sources: Record<string, number>; errors: Record<string, string> };
  alerts: { id: string; title: string; body: string; time: number; url: string; delivery: string }[];
  push_key: string | null; push_enabled: boolean;
  metrics: Record<"with_news" | "without_news", { entries: number; fills: number; tp1: number; result: number | null }>;
};
