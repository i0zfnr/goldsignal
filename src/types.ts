import type { CandlestickData, UTCTimestamp } from "lightweight-charts";

export type Candle = CandlestickData<UTCTimestamp>;
export type Frame = "M1" | "M5" | "M15" | "M30" | "H1" | "H4";
type Pattern = { rsi8: number | null; history: number; matches: number; next4_bps: number | null };
type Evidence = { reason: string; grade: string; pattern?: Pattern };
export type Signal = {
  id: string; direction: "BUY" | "SELL"; created: number; expiry: number;
  entry: [number, number]; initial_stop: number; stop: number; reference: number;
  targets: number[]; fill: number | null; status: string; hits: number;
  evidence: Evidence;
  review?: { provider: string; reason: string };
};
export type Profile = {
  equity: number; free_margin: number; currency: string; units_per_currency: 1 | 100;
  risk_pct: number; daily_loss_pct: number; symbol: string; exit_policy: "split" | "single";
};
export type Fit = {
  decision: "FIT" | "SKIP"; reason: string; currency?: string; budget?: number;
  lot?: number; minimum?: number; minimum_before_cost?: number; loss?: number; margin?: number; loss_pct?: number;
};
type News = { title: string; time: number; source: string; url: string | null; first_seen?: number;
  actual?: string; forecast?: string; previous?: string };
export type Dashboard = {
  symbol: string; mode: string; status: string; clock: number; heartbeat: number | null;
  quote: { bid: number; ask: number; time: number } | null;
  session: { open: boolean; opening: number; cutoff: number; next_myt: string | null; active: string[]; next: string[] };
  revision: number; candles: Candle[]; active: Signal | null; history: Signal[];
  frame: Frame;
  events: { id: string; kind: string; time: number; stop: number; note: string | null }[];
  candidate: { decision: string; reason: string; evidence: Evidence } | null; profile: Profile | null; fit: Fit | null;
  daily: number; calendar: { restriction: string | null; events: News[]; headlines: News[];
    sources: Record<string, number>; errors: Record<string, string> };
  alerts: { id: string; title: string; body: string; time: number; url: string; delivery: string }[];
  push_key: string | null; push_enabled: boolean;
  metrics: Record<"with_news" | "without_news", { entries: number; fills: number; tp1: number; result: number | null }>;
};
