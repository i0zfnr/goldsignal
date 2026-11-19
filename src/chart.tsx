import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Frame, Signal, BAnalysis } from "./types";

type ChartState = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; lines: IPriceLine[];
  data: Map<number, Candle>; last?: UTCTimestamp;
};
type Zone = { id: string; direction: string; top: number; bottom: number; created: number; invalidated?: number; expired: number };
function chartColor(token: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(token).trim();
}

const frameSeconds: Record<Frame, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400 };

export function Chart({ candles, signal, frame, quote, b_analysis }: {
  candles: Candle[]; signal: Signal | null; frame: Frame; quote: { bid: number; ask: number } | null;
  b_analysis?: BAnalysis | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const shade = useRef<HTMLDivElement>(null);
  const sellZoneRef = useRef<HTMLDivElement>(null);
  const buyZoneRef = useRef<HTMLDivElement>(null);
  const entryBandRef = useRef<HTMLDivElement>(null);
  const rewardBox = useRef<HTMLDivElement>(null);
  const riskBox = useRef<HTMLDivElement>(null);
  const state = useRef<ChartState | null>(null);
  const zone = useRef<[number, number] | null>(null);
  const sellZoneRange = useRef<[number, number] | null>(null);
  const buyZoneRange = useRef<[number, number] | null>(null);
  const entryBandRange = useRef<[number, number] | null>(null);
  const closed = useRef<{ start: number; end: number; fill: number; stop: number; target: number } | null>(null);
  const scaleRange = useRef<number[]>([]);
  const liveLines = useRef<IPriceLine[]>([]);
  const zoneLines = useRef<IPriceLine[]>([]);
  const entryBandLines = useRef<IPriceLine[]>([]);
  const [palette, setPalette] = useState(0);
  useEffect(() => {
    const chart = createChart(host.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: chartColor("--panel") }, textColor: chartColor("--muted"),
        attributionLogo: true, fontFamily: "Geist, Segoe UI, sans-serif", fontSize: 12 },
      grid: { vertLines: { color: chartColor("--grid") }, horzLines: { color: chartColor("--grid") } },
      rightPriceScale: { borderColor: chartColor("--line") },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: chartColor("--line"), rightOffset: 5 },
      handleScroll: { vertTouchDrag: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: chartColor("--buy"), downColor: chartColor("--sell"), borderVisible: false,
      wickUpColor: chartColor("--buy"), wickDownColor: chartColor("--sell"), lastValueVisible: false, priceLineVisible: false,
      autoscaleInfoProvider: (original: () => AutoscaleInfo | null) => {
        const info = original();
        if (!info || !info.priceRange || !scaleRange.current.length) return info;
        return { ...info, priceRange: {
          minValue: Math.min(info.priceRange.minValue, ...scaleRange.current),
          maxValue: Math.max(info.priceRange.maxValue, ...scaleRange.current),
        } };
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
      setPalette(value => value + 1);
    }
    window.addEventListener("goldsignal-theme", updateTheme);
    let animation = 0;
    function drawShade(element: HTMLDivElement | null, range: [number, number] | null) {
      if (!element) return;
      const top = range && series.priceToCoordinate(range[1]);
      const bottom = range && series.priceToCoordinate(range[0]);
      element.hidden = top == null || bottom == null;
      if (top != null && bottom != null) {
        const height = chart.panes()[0].getHeight();
        const start = Math.max(0, top);
        const size = Math.max(0, Math.min(height, bottom) - start);
        const inset = chart.priceScale("right").width();
        element.style.top = `${start}px`;
        element.style.height = `${size}px`;
        element.style.right = `${inset}px`;
      }
    }
    function positionBand() {
      drawShade(shade.current, zone.current);
      drawShade(sellZoneRef.current, sellZoneRange.current);
      drawShade(buyZoneRef.current, buyZoneRange.current);
      drawShade(entryBandRef.current, entryBandRange.current);
      const trade = closed.current;
      if (!trade) {
        if (rewardBox.current) rewardBox.current.hidden = true;
        if (riskBox.current) riskBox.current.hidden = true;
        animation = requestAnimationFrame(positionBand);
        return;
      }
      const last = state.current?.last;
      const scale = chart.timeScale();
      const seconds = frameSeconds[frame];
      const candleTime = (stamp: number) =>
        (last! + Math.floor((stamp - last!) / seconds) * seconds) as UTCTimestamp;
      const left = last !== undefined ? scale.timeToCoordinate(candleTime(trade.start)) : null;
      const right = last !== undefined ? scale.timeToCoordinate(candleTime(trade.end)) : null;
      const width = scale.width();
      const height = chart.panes()[0].getHeight();
      const halfBar = scale.options().barSpacing / 2;
      const fill = series.priceToCoordinate(trade.fill);
      function draw(box: HTMLDivElement | null, level: number | undefined) {
        if (!box) return;
        const y = level === undefined ? null : series.priceToCoordinate(level);
        box.hidden = left == null || right == null || fill == null || y == null;
        if (left == null || right == null || fill == null || y == null) return;
        const start = Math.max(0, left - halfBar);
        const top = Math.max(0, Math.min(fill, y));
        box.style.left = `${start}px`;
        box.style.top = `${top}px`;
        box.style.width = `${Math.max(0, Math.min(width, right + halfBar) - start)}px`;
        box.style.height = `${Math.max(0, Math.min(height, Math.max(fill, y)) - top)}px`;
      }
      draw(rewardBox.current, trade.target);
      draw(riskBox.current, trade.stop);
      animation = requestAnimationFrame(positionBand);
    }
    animation = requestAnimationFrame(positionBand);
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
      candles.forEach((candle) => data.set(candle.time, candle));
      series.setData(candles);
      current.last = candles.at(-1)!.time;
      const end = candles.length - 1;
      chart.timeScale().setVisibleLogicalRange({ from: end - (host.current!.clientWidth < 500 ? 44 : 84), to: end + 6 });
      return;
    }
    const last = current.last;
    const backfill = candles.some((candle) => candle.time < last && !data.has(candle.time));
    if (backfill) {
      const range = chart.timeScale().getVisibleRange();
      candles.forEach((candle) => data.set(candle.time, candle));
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
  const entryLow = active ? signal.entry[0] : undefined, entryHigh = active ? signal.entry[1] : undefined;
  const stop = active ? signal.stop : undefined;
  const target1 = active && signal.hits < 1 ? signal.targets[0] : undefined;
  const target2 = active && signal.hits < 2 ? signal.targets[1] : undefined;
  const target3 = active && signal.hits < 3 ? signal.targets[2] : undefined;
  const closedAt = signal?.status === "STOPPED" || signal?.status === "COMPLETED" ? signal.exits?.at(-1)?.time : undefined;
  const fill = signal?.fill, filledAt = signal?.filled_at, initialStop = signal?.initial_stop;
  const finalTarget = signal?.targets.at(-1);
  const outcome = closedAt === undefined ? undefined : signal?.status === "STOPPED"
    ? (signal.hits ? `Stopped after TP${signal.hits}` : "Stopped") : "All targets hit";
  useEffect(() => {
    const current = state.current;
    if (!current) return;
    current.lines.forEach((line) => current.series.removePriceLine(line));
    zoneLines.current.forEach((line) => current.series.removePriceLine(line));
    entryBandLines.current.forEach((line) => current.series.removePriceLine(line));
    current.lines = [];
    zoneLines.current = [];
    entryBandLines.current = [];
    closed.current = fill != null && filledAt !== undefined && closedAt !== undefined &&
      initialStop !== undefined && finalTarget !== undefined
      ? { start: filledAt, end: closedAt, fill, stop: initialStop, target: finalTarget } : null;
    zone.current = entryLow !== undefined && entryHigh !== undefined ? [entryLow, entryHigh] : null;
    const levels: [string, number | undefined, string][] = [
      ["Entry high", entryHigh, chartColor("--gold")], ["Entry low", entryLow, chartColor("--gold")],
      ["SL", stop, chartColor("--sell")],
      ["TP1", stop === target1 ? undefined : target1, chartColor("--buy")],
      ["TP2", target2, chartColor("--buy")], ["TP3", target3, chartColor("--buy")],
    ];
    scaleRange.current = levels.flatMap(([, price]) => price === undefined ? [] : [price]);
    for (const [title, price, color] of levels) {
      if (price !== undefined) current.lines.push(current.series.createPriceLine({
        price, color, title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,
        axisLabelTextColor: chartColor("--chart-label"),
      }));
    }
    sellZoneRange.current = b_analysis?.nearest_sell ? [b_analysis.nearest_sell.bottom, b_analysis.nearest_sell.top] : null;
    buyZoneRange.current = b_analysis?.nearest_buy ? [b_analysis.nearest_buy.bottom, b_analysis.nearest_buy.top] : null;
    entryBandRange.current = b_analysis?.candidate?.entry ? [b_analysis.candidate.entry[0], b_analysis.candidate.entry[1]] : null;
    if (b_analysis?.nearest_sell) {
      scaleRange.current.push(b_analysis.nearest_sell.bottom, b_analysis.nearest_sell.top);
    }
    if (b_analysis?.nearest_buy) {
      scaleRange.current.push(b_analysis.nearest_buy.bottom, b_analysis.nearest_buy.top);
    }
    if (b_analysis?.zones) {
      for (const z of b_analysis.zones.slice(0, 3)) {
        const color = z.direction === "SELL" ? "#ef4444" : "#3b82f6";
        zoneLines.current.push(current.series.createPriceLine({
          price: z.top, color, title: `${z.direction} zone top`, lineWidth: 1, lineStyle: LineStyle.Dotted,
          axisLabelVisible: true, axisLabelTextColor: color,
        }));
        zoneLines.current.push(current.series.createPriceLine({
          price: z.bottom, color, title: `${z.direction} zone bottom`, lineWidth: 1, lineStyle: LineStyle.Dotted,
          axisLabelVisible: true, axisLabelTextColor: color,
        }));
      }
    }
    if (b_analysis?.candidate?.entry) {
      const entry = b_analysis.candidate.entry;
      const color = b_analysis.candidate.direction === "SELL" ? "#ef4444" : "#3b82f6";
      entryBandLines.current.push(current.series.createPriceLine({
        price: entry[0], color, title: "Entry band low", lineWidth: 2, lineStyle: LineStyle.Solid,
        axisLabelVisible: true, axisLabelTextColor: color,
      }));
      entryBandLines.current.push(current.series.createPriceLine({
        price: entry[1], color, title: "Entry band high", lineWidth: 2, lineStyle: LineStyle.Solid,
        axisLabelVisible: true, axisLabelTextColor: color,
      }));
      scaleRange.current.push(...entry);
    }
  }, [entryLow, entryHigh, stop, target1, target2, target3, closedAt, fill, filledAt, initialStop, finalTarget, palette, b_analysis]);
  const bid = quote?.bid, ask = quote?.ask;
  useEffect(() => {
    const series = state.current?.series;
    if (!series) return;
    if (bid === undefined || ask === undefined) {
      liveLines.current.forEach(line => series.removePriceLine(line));
      liveLines.current = [];
      return;
    }
    if (liveLines.current.length) {
      liveLines.current[0].applyOptions({ price: bid, color: chartColor("--buy"), axisLabelTextColor: chartColor("--chart-label") });
      liveLines.current[1].applyOptions({ price: ask, color: chartColor("--ask"), axisLabelTextColor: chartColor("--chart-label") });
      return;
    }
    liveLines.current = [
      series.createPriceLine({ price: bid, title: "Bid", color: chartColor("--buy"), lineWidth: 1, axisLabelTextColor: chartColor("--chart-label") }),
      series.createPriceLine({ price: ask, title: "Ask", color: chartColor("--ask"), lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelTextColor: chartColor("--chart-label") }),
    ];
  }, [bid, ask, palette]);
  return <div className="chart-shell">
    <div ref={host} className="chart" role="img" aria-label={`XAUUSD ${frame} candlestick chart. Exact signal levels are listed below.`} />
    <div ref={shade} className="entry-shade" hidden aria-hidden="true" />
    <div ref={sellZoneRef} className="zone-shade sell-zone-shade" hidden aria-hidden="true" />
    <div ref={buyZoneRef} className="zone-shade buy-zone-shade" hidden aria-hidden="true" />
    <div ref={entryBandRef} className="zone-shade entry-band-shade" hidden aria-hidden="true" />
    <div ref={rewardBox} className="trade-box trade-reward" hidden aria-hidden="true"><span>{outcome}</span></div>
    <div ref={riskBox} className="trade-box trade-risk" hidden aria-hidden="true" />
  </div>;
}
