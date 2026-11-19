import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import { ExternalLink, Eye, RotateCw } from "lucide-react";
import type { Candle, Frame, Signal, BAnalysis, BZone } from "./types";

type ChartState = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; lines: IPriceLine[];
  data: Map<number, Candle>; last?: UTCTimestamp;
};

const frameSeconds: Record<Frame, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400 };
const numberFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const mytFmt = new Intl.DateTimeFormat("en-MY", {
  timeZone: "Asia/Kuala_Lumpur", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

export function Chart({
  candles, signal, frame, quote, b_analysis, onFrameChange, session, onRefresh,
}: {
  candles: Candle[];
  signal: Signal | null;
  frame: Frame;
  quote: { bid: number; ask: number; time?: number } | null;
  b_analysis?: BAnalysis | null;
  onFrameChange?: (f: Frame) => void;
  session?: { open: boolean; active?: string[]; next?: string[] } | null;
  onRefresh?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const zonesOverlayRef = useRef<HTMLDivElement>(null);
  const rewardBox = useRef<HTMLDivElement>(null);
  const riskBox = useRef<HTMLDivElement>(null);
  const state = useRef<ChartState | null>(null);
  const closed = useRef<{ start: number; end: number; fill: number; stop: number; target: number } | null>(null);
  const scaleRange = useRef<number[]>([]);
  const liveLines = useRef<IPriceLine[]>([]);
  const zoneLines = useRef<IPriceLine[]>([]);
  const entryBandLines = useRef<IPriceLine[]>([]);
  const [showZones, setShowZones] = useState(true);

  const zonesToRender = (b_analysis?.zones ?? []).slice(0, 5);
  const price = quote ? (quote.bid + quote.ask) / 2 : (candles.at(-1)?.close ?? 0);
  const nearestSell = b_analysis?.nearest_sell;
  const nearestBuy = b_analysis?.nearest_buy;
  const sellPips = nearestSell && price ? Math.max(0, Math.round(Math.abs(price - nearestSell.bottom) / 0.10 * 10) / 10) : null;
  const buyPips = nearestBuy && price ? Math.max(0, Math.round(Math.abs(price - nearestBuy.top) / 0.10 * 10) / 10) : null;
  const nowTs = quote?.time ?? Math.floor(Date.now() / 1000);
  const updateTimeStr = mytFmt.format(nowTs * 1000);

  // Direction badge next to price
  const candidate = b_analysis?.candidate;
  const direction = candidate?.direction ?? (b_analysis?.h1.direction === "bearish" ? "SELL" : b_analysis?.h1.direction === "bullish" ? "BUY" : null);

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#0c0d14" },
        textColor: "#94a3b8",
        attributionLogo: false,
        fontFamily: "Geist, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.03)" },
        horzLines: { color: "rgba(255, 255, 255, 0.03)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255, 255, 255, 0.08)",
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: "rgba(255, 255, 255, 0.08)",
        rightOffset: 6,
      },
      handleScroll: { vertTouchDrag: false },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
      lastValueVisible: false,
      priceLineVisible: false,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original();
        if (!info || !info.priceRange || !scaleRange.current.length) return info;
        return {
          ...info,
          priceRange: {
            minValue: Math.min(info.priceRange.minValue, ...scaleRange.current),
            maxValue: Math.max(info.priceRange.maxValue, ...scaleRange.current),
          },
        };
      },
    });

    state.current = { chart, series, lines: [], data: new Map() };

    let animation = 0;
    function positionElements() {
      if (!state.current) return;
      const { chart: c, series: s } = state.current;
      const height = c.panes()[0].getHeight();
      const inset = c.priceScale("right").width();

      // Position zone overlays
      if (zonesOverlayRef.current) {
        const zoneEls = zonesOverlayRef.current.querySelectorAll<HTMLDivElement>(".katana-zone-box");
        zoneEls.forEach(el => {
          const topVal = Number(el.dataset.top);
          const botVal = Number(el.dataset.bottom);
          if (!topVal || !botVal) return;
          const topY = s.priceToCoordinate(topVal);
          const botY = s.priceToCoordinate(botVal);
          if (topY == null || botY == null) {
            el.style.display = "none";
            return;
          }
          el.style.display = showZones ? "block" : "none";
          const start = Math.max(0, topY);
          const size = Math.max(2, Math.min(height, botY) - start);
          el.style.top = `${start}px`;
          el.style.height = `${size}px`;
          el.style.right = `${inset}px`;
          el.style.left = "0px";
        });

        // Position candidate entry band
        const bandEl = zonesOverlayRef.current.querySelector<HTMLDivElement>(".katana-entry-band-box");
        if (bandEl) {
          const topVal = Number(bandEl.dataset.top);
          const botVal = Number(bandEl.dataset.bottom);
          const topY = topVal ? s.priceToCoordinate(topVal) : null;
          const botY = botVal ? s.priceToCoordinate(botVal) : null;
          if (topY == null || botY == null) {
            bandEl.style.display = "none";
          } else {
            bandEl.style.display = showZones ? "block" : "none";
            const start = Math.max(0, topY);
            const size = Math.max(2, Math.min(height, botY) - start);
            bandEl.style.top = `${start}px`;
            bandEl.style.height = `${size}px`;
            bandEl.style.right = `${inset}px`;
            bandEl.style.left = "0px";
          }
        }
      }

      // Position trade box if closed trade
      const trade = closed.current;
      if (trade && state.current.last !== undefined) {
        const scale = c.timeScale();
        const seconds = frameSeconds[frame];
        const candleTime = (stamp: number) =>
          (state.current!.last! + Math.floor((stamp - state.current!.last!) / seconds) * seconds) as UTCTimestamp;
        const left = scale.timeToCoordinate(candleTime(trade.start));
        const right = scale.timeToCoordinate(candleTime(trade.end));
        const width = scale.width();
        const halfBar = scale.options().barSpacing / 2;
        const fill = s.priceToCoordinate(trade.fill);
        function drawTrade(box: HTMLDivElement | null, level: number | undefined) {
          if (!box) return;
          const y = level === undefined ? null : s.priceToCoordinate(level);
          box.hidden = left == null || right == null || fill == null || y == null;
          if (left == null || right == null || fill == null || y == null) return;
          const start = Math.max(0, left - halfBar);
          const top = Math.max(0, Math.min(fill, y));
          box.style.left = `${start}px`;
          box.style.top = `${top}px`;
          box.style.width = `${Math.max(0, Math.min(width, right + halfBar) - start)}px`;
          box.style.height = `${Math.max(0, Math.min(height, Math.max(fill, y)) - top)}px`;
        }
        drawTrade(rewardBox.current, trade.target);
        drawTrade(riskBox.current, trade.stop);
      } else {
        if (rewardBox.current) rewardBox.current.hidden = true;
        if (riskBox.current) riskBox.current.hidden = true;
      }
      animation = requestAnimationFrame(positionElements);
    }

    animation = requestAnimationFrame(positionElements);
    return () => {
      cancelAnimationFrame(animation);
      chart.remove();
      state.current = null;
      liveLines.current = [];
    };
  }, [frame, showZones]);

  useEffect(() => {
    const current = state.current;
    if (!current || !candles.length) return;
    const { series, chart, data } = current;
    if (current.last === undefined) {
      candles.forEach(candle => data.set(candle.time, candle));
      series.setData(candles);
      current.last = candles.at(-1)!.time;
      const end = candles.length - 1;
      chart.timeScale().setVisibleLogicalRange({
        from: end - (host.current!.clientWidth < 500 ? 36 : 72),
        to: end + 4,
      });
      return;
    }
    const last = current.last;
    const backfill = candles.some(c => c.time < last && !data.has(c.time));
    if (backfill) {
      const range = chart.timeScale().getVisibleRange();
      candles.forEach(candle => data.set(candle.time, candle));
      series.setData([...data.values()].sort((a, b) => a.time - b.time));
      if (range) chart.timeScale().setVisibleRange(range);
      current.last = candles.at(-1)!.time > last ? candles.at(-1)!.time : last;
    } else {
      for (const candle of candles) {
        data.set(candle.time, candle);
        series.update(candle, candle.time < current.last);
        if (candle.time > current.last) current.last = candle.time;
      }
    }
  }, [candles]);

  const active = signal?.status === "PENDING" || signal?.status === "FILLED";
  const entryLow = active ? signal.entry[0] : undefined;
  const entryHigh = active ? signal.entry[1] : undefined;
  const stop = active ? signal.stop : undefined;
  const target1 = active && signal.hits < 1 ? signal.targets[0] : undefined;
  const target2 = active && signal.hits < 2 ? signal.targets[1] : undefined;
  const target3 = active && signal.hits < 3 ? signal.targets[2] : undefined;
  const closedAt = signal?.status === "STOPPED" || signal?.status === "COMPLETED" ? signal.exits?.at(-1)?.time : undefined;
  const fill = signal?.fill;
  const filledAt = signal?.filled_at;
  const initialStop = signal?.initial_stop;
  const finalTarget = signal?.targets.at(-1);
  const outcome = closedAt === undefined ? undefined : signal?.status === "STOPPED"
    ? (signal.hits ? `Stopped after TP${signal.hits}` : "Stopped") : "All targets hit";

  useEffect(() => {
    const current = state.current;
    if (!current) return;
    current.lines.forEach(line => current.series.removePriceLine(line));
    zoneLines.current.forEach(line => current.series.removePriceLine(line));
    entryBandLines.current.forEach(line => current.series.removePriceLine(line));
    current.lines = [];
    zoneLines.current = [];
    entryBandLines.current = [];

    closed.current = fill != null && filledAt !== undefined && closedAt !== undefined &&
      initialStop !== undefined && finalTarget !== undefined
      ? { start: filledAt, end: closedAt, fill, stop: initialStop, target: finalTarget } : null;

    const levels: [string, number | undefined, string][] = [
      ["Entry high", entryHigh, "#eab308"], ["Entry low", entryLow, "#eab308"],
      ["SL", stop, "#ef4444"],
      ["TP1", stop === target1 ? undefined : target1, "#10b981"],
      ["TP2", target2, "#10b981"], ["TP3", target3, "#10b981"],
    ];
    scaleRange.current = levels.flatMap(([, p]) => p === undefined ? [] : [p]);
    for (const [title, p, color] of levels) {
      if (p !== undefined) {
        current.lines.push(current.series.createPriceLine({
          price: p, color, title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,
          axisLabelTextColor: "#ffffff",
        }));
      }
    }

    if (showZones && b_analysis?.zones) {
      for (const z of b_analysis.zones.slice(0, 4)) {
        const isSell = z.direction === "SELL";
        const color = isSell ? "#ef4444" : "#3b82f6";
        scaleRange.current.push(z.top, z.bottom);
        // Clean price lines without canvas titles so axis displays clean badges without artifacts
        zoneLines.current.push(current.series.createPriceLine({
          price: z.top, color, title: "", lineWidth: 1, lineStyle: LineStyle.Solid,
          axisLabelVisible: true, axisLabelTextColor: "#ffffff",
          axisLabelColor: isSell ? "#b91c1c" : "#1d4ed8",
        }));
        zoneLines.current.push(current.series.createPriceLine({
          price: z.bottom, color, title: "", lineWidth: 1, lineStyle: LineStyle.Solid,
          axisLabelVisible: true, axisLabelTextColor: "#ffffff",
          axisLabelColor: isSell ? "#b91c1c" : "#1d4ed8",
        }));
      }
    }

    if (showZones && b_analysis?.candidate?.entry) {
      const entry = b_analysis.candidate.entry;
      entryBandLines.current.push(current.series.createPriceLine({
        price: entry[0], color: "#eab308", title: "", lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, axisLabelTextColor: "#000000", axisLabelColor: "#eab308",
      }));
      entryBandLines.current.push(current.series.createPriceLine({
        price: entry[1], color: "#eab308", title: "", lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, axisLabelTextColor: "#000000", axisLabelColor: "#eab308",
      }));
      scaleRange.current.push(...entry);
    }
  }, [entryLow, entryHigh, stop, target1, target2, target3, closedAt, fill, filledAt, initialStop, finalTarget, b_analysis, showZones]);

  const bid = quote?.bid;
  const ask = quote?.ask;
  useEffect(() => {
    const series = state.current?.series;
    if (!series) return;
    if (bid === undefined || ask === undefined) {
      liveLines.current.forEach(line => series.removePriceLine(line));
      liveLines.current = [];
      return;
    }
    if (liveLines.current.length >= 2) {
      liveLines.current[0].applyOptions({ price: bid });
      liveLines.current[1].applyOptions({ price: ask });
      return;
    }
    liveLines.current = [
      series.createPriceLine({ price: bid, title: "Bid", color: "#10b981", lineWidth: 1, axisLabelVisible: true, axisLabelTextColor: "#ffffff", axisLabelColor: "#059669" }),
      series.createPriceLine({ price: ask, title: "Ask", color: "#f59e0b", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, axisLabelTextColor: "#ffffff", axisLabelColor: "#d97706" }),
    ];
  }, [bid, ask]);

  const activeSessionName = session?.open && session.active?.length ? session.active[0] : (session?.next?.length ? session.next[0] : "NEW YORK");
  const tfList: Frame[] = ["M5", "M15", "M30", "H1"];
  const biasTfList = ["M5", "M15", "M30", "H1"] as const;

  return (
    <div className="katana-chart-wrapper">
      {/* 1. Katana Chart Header */}
      <div className="katana-chart-header">
        <div className="katana-header-left">
          <div className="katana-live-badge">
            <span className="katana-live-dot" />
            <span className="katana-live-title">LIVE CHART · XAUUSD</span>
          </div>
          <div className="katana-tf-group" role="group" aria-label="Timeframe">
            {tfList.map(tf => (
              <button
                key={tf}
                type="button"
                className={`katana-tf-btn ${frame === tf ? "active" : ""}`}
                onClick={() => onFrameChange?.(tf)}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        <div className="katana-header-center">
          <span className="katana-price-val">${numberFmt.format(price)}</span>
          {direction && (
            <span className={`katana-action-pill ${direction === "SELL" ? "sell" : "buy"}`}>
              {direction === "SELL" ? "▼ SELL" : "▲ BUY"}
              <span className="katana-action-conf"> (88%)</span>
            </span>
          )}
        </div>

        <div className="katana-header-right">
          <div className="katana-session-badge">
            <span className={`session-indicator ${session?.open ? "open" : "closed"}`} />
            <span>{activeSessionName.toUpperCase()}</span>
          </div>
          <button
            type="button"
            className={`katana-action-btn ${showZones ? "active" : ""}`}
            onClick={() => setShowZones(!showZones)}
            title="Toggle Katana AI SMC Zones"
          >
            <Eye size={14} />
            <span className="btn-text">Katana AI Zones</span>
          </button>
          <a
            className="katana-action-btn tv-link"
            href="https://www.tradingview.com/chart/?symbol=OANDA%3AXAUUSD"
            target="_blank"
            rel="noopener noreferrer"
            title="Open in TradingView"
          >
            <ExternalLink size={14} />
            <span className="btn-text">TradingView</span>
          </a>
          <button
            type="button"
            className="katana-action-btn refresh-btn"
            onClick={() => onRefresh?.()}
            title="Refresh AI Analysis"
          >
            <RotateCw size={14} />
            <span className="btn-text">Refresh AI</span>
          </button>
        </div>
      </div>

      {/* 2. Katana Multi-Timeframe Bias Strip */}
      <div className="katana-bias-strip" role="region" aria-label="Multi-Timeframe Structure Bias">
        {biasTfList.map(tf => {
          const b = b_analysis?.tf_bias?.[tf] ?? "neutral";
          const isBull = b === "bullish";
          const isBear = b === "bearish";
          return (
            <div key={tf} className={`katana-bias-chip ${b}`}>
              <span className="katana-bias-tf">{tf}</span>
              <span className={`katana-bias-val ${b}`}>
                {isBull ? "BULL" : isBear ? "BEAR" : "NEUT"}
              </span>
              <span className={`katana-bias-dot ${b}`} />
            </div>
          );
        })}
      </div>

      {/* 3. Interactive Lightweight Chart Canvas & Overlays */}
      <div className="chart-shell katana-chart-canvas">
        <div
          ref={host}
          className="chart"
          role="img"
          aria-label={`XAUUSD ${frame} candlestick chart with Katana liquidity zones`}
        />

        {/* Zones & Entry Band HTML Overlays */}
        <div ref={zonesOverlayRef} className="katana-zones-overlay" aria-hidden="true">
          {zonesToRender.map((z: BZone) => {
            const isSell = z.direction === "SELL";
            return (
              <div
                key={z.id}
                className={`katana-zone-box ${isSell ? "sell-zone" : "buy-zone"}`}
                data-top={z.top}
                data-bottom={z.bottom}
              >
                <div className="katana-zone-tag">
                  <span className="katana-tag-pin">📍</span>
                  <span className="katana-tag-label">
                    {isSell ? "SELL ZONE: " : "BUY ZONE: "}
                    {z.bottom.toFixed(2)} – {z.top.toFixed(2)}
                  </span>
                  <span className="katana-tag-sub">
                    ({isSell ? "Secondary Liquidity Zone" : "Institutional Demand Order Block"})
                  </span>
                </div>
                <div className="katana-zone-edge-labels">
                  <span className={`katana-edge-pill top ${isSell ? "sell" : "buy"}`}>
                    {isSell ? "SELL TOP: " : "BUY TOP: "}{z.top.toFixed(2)}
                  </span>
                  <span className={`katana-edge-pill bot ${isSell ? "sell" : "buy"}`}>
                    BOT: {z.bottom.toFixed(2)}
                  </span>
                </div>
              </div>
            );
          })}

          {candidate?.entry && (
            <div
              className="katana-entry-band-box"
              data-top={candidate.entry[1]}
              data-bottom={candidate.entry[0]}
            >
              <div className="katana-entry-band-tag">
                <span>⚡ ACTIONABLE ENTRY BAND: {candidate.entry[0].toFixed(2)} – {candidate.entry[1].toFixed(2)}</span>
              </div>
            </div>
          )}
        </div>

        {/* Trade execution boxes */}
        <div ref={rewardBox} className="trade-box trade-reward" hidden aria-hidden="true"><span>{outcome}</span></div>
        <div ref={riskBox} className="trade-box trade-risk" hidden aria-hidden="true" />
      </div>

      {/* 4. Katana Chart Footer */}
      <div className="katana-chart-footer">
        <div className="katana-footer-zones">
          {nearestSell && (
            <span className="katana-footer-item sell">
              <span className="footer-dot sell" />
              Zon SELL: {nearestSell.bottom.toFixed(2)} – {nearestSell.top.toFixed(2)}
              {sellPips !== null && <span className="pips-badge"> ({sellPips} pips)</span>}
            </span>
          )}
          {nearestBuy && (
            <span className="katana-footer-item buy">
              <span className="footer-dot buy" />
              Zon BUY: {nearestBuy.bottom.toFixed(2)} – {nearestBuy.top.toFixed(2)}
              {buyPips !== null && <span className="pips-badge"> ({buyPips} pips)</span>}
            </span>
          )}
        </div>
        <div className="katana-footer-engine">
          <span className="katana-engine-text">⚡ Katana AI SMC Engine · Dikemaskini {updateTimeStr} (MYT)</span>
        </div>
      </div>
    </div>
  );
}
