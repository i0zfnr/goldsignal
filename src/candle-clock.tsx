import { useEffect, useState } from "react";
import type { Frame } from "./types";

const duration: Record<Frame, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400 };

function formatCountdown(seconds: number) {
  const hours = Math.floor(seconds / 3600);
  const minutes = String(Math.floor(seconds / 60) % 60).padStart(2, "0");
  const remainder = String(seconds % 60).padStart(2, "0");
  return hours ? `${hours}:${minutes}:${remainder}` : `${minutes}:${remainder}`;
}

export function CandleClock({ frame, open, clock, receivedAt, status }: {
  frame: Frame; open?: number; clock?: number; receivedAt: number; status?: string;
}) {
  const [sample, setSample] = useState(() => performance.now());
  useEffect(() => {
    if (status !== "LIVE" || open === undefined) return;
    const timer = window.setInterval(() => setSample(performance.now()), 250);
    return () => window.clearInterval(timer);
  }, [status, open]);

  let text = status === "MARKET CLOSED" ? "Market closed" : "–";
  if ((status === "LIVE" || status === "DEMO") && open !== undefined && Number.isFinite(clock)) {
    const elapsed = status === "LIVE" ? Math.max(0, sample - receivedAt) / 1000 : 0;
    const now = clock! + elapsed;
    const remaining = Math.ceil(open + duration[frame] - now);
    text = now < open || remaining <= 0 ? "Waiting for candle" : formatCountdown(remaining);
  }
  return <div className="candle-clock">
    <span>{frame} closes in</span>
    <strong role="timer" aria-label={`${frame} candle close countdown`}>{text}</strong>
  </div>;
}
