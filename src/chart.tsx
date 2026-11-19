import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Frame, Signal, BAnalysis, BZone } from "./types";

type ChartState = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; lines: IPriceLine[];
  data: Map<number, Candle>; last?: UTCTimestamp;
};

function chartColor(token: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

const frameSeconds: Record<Frame, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400 };

export function Chart({
  candles, signal, frame, quote, b_analysis,
}: {
  candles: Candle[];
  signal: Signal | null;
  frame: Frame;
  quote: { bid: number; ask: number } | null;
  b_analysis?: BAnalysis | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const zonesOverlayRef = useRef<HTMLDivElement>(null);
  const rewardBox = useRef<HTMLDivElement>(null);
  const riskBox = useRef<HTMLDivElement>(null);
  const state = useRef<ChartState | null>(null);
  const closed = useRef<{ start: number; end: number; fill: number; stop: number; target: number } | null>(null);
  const scaleRange = useRef<number[]>([]);
  const liveLines = useRef<IPriceLine[]>([]);
  const [palette, setPalette] = useState(0);

  // Render ONLY the primary active key zones: 1 Sell Supply + 1 Buy Demand
  // Eliminates confusing stacks of 4-5 overlapping boxes!
  const zonesToRender = [b_analysis?.nearest_sell, b_analysis?.nearest_buy].filter(Boolean) as BZone[];
  const candidate = b_analysis?.candidate;

  useEffect(() => {
    if (!host.current) return;
    const chart = createChart(host.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: chartColor("--panel") },
        textColor: chartColor("--muted"),
        attributionLogo: false,
        fontFamily: "Geist, Segoe UI, sans-serif",
        fontSize: 12,
      },
      grid: {
        vertLines: { color: chartColor("--grid") },
        horzLines: { color: chartColor("--grid") },
      },
      rightPriceScale: { borderColor: chartColor("--line") },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        borderColor: chartColor("--line"),
        rightOffset: 6,
      },
      handleScroll: { vertTouchDrag: false },
    });

    const series = chart.addSeries(CandlestickSeries, {
      upColor: chartColor("--buy"),
      downColor: chartColor("--sell"),
      borderVisible: false,
      wickUpColor: chartColor("--buy"),
      wickDownColor: chartColor("--sell"),
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

    function updateTheme() {
      const borderColor = chartColor("--line");
      const grid = chartColor("--grid");
      const upColor = chartColor("--buy");
      const downColor = chartColor("--sell");
      chart.applyOptions({
        layout: { background: { type: ColorType.Solid, color: chartColor("--panel") }, textColor: chartColor("--muted") },
        grid: { vertLines: { color: grid }, horzLines: { color: grid } },
        rightPriceScale: { borderColor }, timeScale: { borderColor },
      });
      series.applyOptions({ upColor, downColor, wickUpColor: upColor, wickDownColor: downColor });
      setPalette(v => v + 1);
    }
    window.addEventListener("goldsignal-theme", updateTheme);

    let animation = 0;
    function positionElements() {
      if (!state.current || !host.current) {
        animation = requestAnimationFrame(positionElements);
        return;
      }
      try {
        const { chart: c, series: s } = state.current;
        const hostEl = host.current;
        const height = hostEl.clientHeight || 400;
        const plotWidth = c.timeScale().width();
        const inset = Math.max(50, hostEl.clientWidth - plotWidth);

        // Position zone boxes inside the chart (matching Image 2 & Image 3)
        if (zonesOverlayRef.current) {
          const zoneEls = zonesOverlayRef.current.querySelectorAll<HTMLDivElement>(".zone-band");
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
            el.style.display = "flex";
            const start = Math.max(0, Math.min(topY, botY));
            const end = Math.min(height, Math.max(topY, botY));
            const size = Math.max(14, end - start);
            el.style.top = `${start}px`;
            el.style.height = `${size}px`;
            el.style.right = `${inset}px`;
            el.style.left = "0px";
          });

          // Position candidate entry band
          const bandEl = zonesOverlayRef.current.querySelector<HTMLDivElement>(".entry-band-box");
          if (bandEl) {
            const topVal = Number(bandEl.dataset.top);
            const botVal = Number(bandEl.dataset.bottom);
            const topY = topVal ? s.priceToCoordinate(topVal) : null;
            const botY = botVal ? s.priceToCoordinate(botVal) : null;
            if (topY == null || botY == null) {
              bandEl.style.display = "none";
            } else {
              bandEl.style.display = "flex";
              const start = Math.max(0, Math.min(topY, botY));
              const end = Math.min(height, Math.max(topY, botY));
              const size = Math.max(10, end - start);
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
      } catch (err) {
        console.error("positionElements error:", err);
      }
      animation = requestAnimationFrame(positionElements);
    }

    animation = requestAnimationFrame(positionElements);
    return () => {
      window.removeEventListener("goldsignal-theme", updateTheme);
      cancelAnimationFrame(animation);
      chart.remove();
      state.current = null;
      liveLines.current = [];
    };
  }, [frame]);

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
    current.lines = [];

    closed.current = fill != null && filledAt !== undefined && closedAt !== undefined &&
      initialStop !== undefined && finalTarget !== undefined
      ? { start: filledAt, end: closedAt, fill, stop: initialStop, target: finalTarget } : null;

    // Only active signal entry/stop/target lines are drawn on series
    const levels: [string, number | undefined, string][] = [
      ["Entry high", entryHigh, chartColor("--gold")], ["Entry low", entryLow, chartColor("--gold")],
      ["SL", stop, chartColor("--sell")],
      ["TP1", stop === target1 ? undefined : target1, chartColor("--buy")],
      ["TP2", target2, chartColor("--buy")], ["TP3", target3, chartColor("--buy")],
    ];
    scaleRange.current = levels.flatMap(([, p]) => p === undefined ? [] : [p]);
    for (const [title, p, color] of levels) {
      if (p !== undefined) {
        current.lines.push(current.series.createPriceLine({
          price: p, color, title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,
          axisLabelTextColor: chartColor("--chart-label"),
        }));
      }
    }

    // Push nearest zone prices to autoscale range so chart keeps active zones in view,
    // but DO NOT add any price lines to the series (no confusing lines across candles!)
    const keyZones = [b_analysis?.nearest_sell, b_analysis?.nearest_buy].filter(Boolean) as BZone[];
    for (const z of keyZones) {
      scaleRange.current.push(z.top, z.bottom);
    }
    if (candidate?.entry) {
      scaleRange.current.push(...candidate.entry);
    }
  }, [entryLow, entryHigh, stop, target1, target2, target3, closedAt, fill, filledAt, initialStop, finalTarget, b_analysis, palette]);

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
      liveLines.current[0].applyOptions({ price: bid, color: chartColor("--buy"), axisLabelTextColor: chartColor("--chart-label") });
      liveLines.current[1].applyOptions({ price: ask, color: chartColor("--ask"), axisLabelTextColor: chartColor("--chart-label") });
      return;
    }
    liveLines.current = [
      series.createPriceLine({ price: bid, title: "Bid", color: chartColor("--buy"), lineWidth: 1, axisLabelVisible: true, axisLabelTextColor: chartColor("--chart-label") }),
      series.createPriceLine({ price: ask, title: "Ask", color: chartColor("--ask"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelVisible: true, axisLabelTextColor: chartColor("--chart-label") }),
    ];
  }, [bid, ask, palette]);

  return (
    <div className="chart-shell">
      <div
        ref={host}
        className="chart"
        role="img"
        aria-label={`XAUUSD ${frame} candlestick chart. Exact signal levels are listed below.`}
      />

      {/* Red SELL and Green BUY boxes inside chart canvas (matching Image 2 & 3, NO confusing lines) */}
      <div ref={zonesOverlayRef} className="zones-overlay" aria-hidden="true">
        {zonesToRender.map((z: BZone) => {
          const isSell = z.direction === "SELL";
          return (
            <div
              key={z.id}
              className={`zone-band ${isSell ? "sell-band" : "buy-band"}`}
              data-top={z.top}
              data-bottom={z.bottom}
            >
              <div className={`zone-box-card ${isSell ? "sell-box" : "buy-box"}`}>
                <span className="zone-box-type">{isSell ? "SELL SIDE LIQ." : "BUY SIDE LIQ."}</span>
                <span className="zone-box-sep">|</span>
                <span className="zone-box-range">{z.bottom.toFixed(2)} – {z.top.toFixed(2)}</span>
                <span className="zone-box-sep">|</span>
                <span className="zone-box-tag">{z.mitigated ? "TESTED" : "FRESH"}</span>
              </div>
            </div>
          );
        })}

        {candidate?.entry && (
          <div
            className="entry-band-box"
            data-top={candidate.entry[1]}
            data-bottom={candidate.entry[0]}
          >
            <div className="entry-band-card">
              <span>⚡ ENTRY BAND | {candidate.entry[0].toFixed(2)} – {candidate.entry[1].toFixed(2)}</span>
            </div>
          </div>
        )}
      </div>

      <div ref={rewardBox} className="trade-box trade-reward" hidden aria-hidden="true"><span>{outcome}</span></div>
      <div ref={riskBox} className="trade-box trade-risk" hidden aria-hidden="true" />
    </div>
  );
}
