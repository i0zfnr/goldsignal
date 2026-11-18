import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Frame, Signal } from "./types";

type ChartState = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; lines: IPriceLine[];
  data: Map<number, Candle>; last?: UTCTimestamp;
};
const frameSeconds: Record<Frame, number> = { M1: 60, M5: 300, M15: 900, M30: 1800, H1: 3600, H4: 14400 };

export function Chart({ candles, signal, frame, quote }: {
  candles: Candle[]; signal: Signal | null; frame: Frame; quote: { bid: number; ask: number } | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const shade = useRef<HTMLDivElement>(null);
  const rewardBox = useRef<HTMLDivElement>(null);
  const riskBox = useRef<HTMLDivElement>(null);
  const state = useRef<ChartState | null>(null);
  const zone = useRef<[number, number] | null>(null);
  const closed = useRef<{ start: number; end: number; fill: number; stop: number; target: number } | null>(null);
  const scaleRange = useRef<number[]>([]);
  const liveLines = useRef<IPriceLine[]>([]);
  useEffect(() => {
    const chart = createChart(host.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#171a17" }, textColor: "#bdc4b9",
        attributionLogo: true, fontFamily: "Segoe UI, sans-serif", fontSize: 12 },
      grid: { vertLines: { color: "#282d27" }, horzLines: { color: "#282d27" } },
      rightPriceScale: { borderColor: "#3a4238" },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#3a4238", rightOffset: 5 },
      handleScroll: { vertTouchDrag: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#6abca4", downColor: "#ed8b7e", borderVisible: false,
      wickUpColor: "#6abca4", wickDownColor: "#ed8b7e", lastValueVisible: false, priceLineVisible: false,
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
    let animation = 0;
    let lastBand = "";
    function positionBand() {
      const element = shade.current;
      const range = zone.current;
      if (element) {
        const top = range && series.priceToCoordinate(range[1]);
        const bottom = range && series.priceToCoordinate(range[0]);
        element.hidden = top == null || bottom == null;
        if (top != null && bottom != null) {
          const height = chart.panes()[0].getHeight();
          const start = Math.max(0, top);
          const size = Math.max(0, Math.min(height, bottom) - start);
          const inset = chart.priceScale("right").width();
          const band = `${start}:${size}:${inset}`;
          if (band !== lastBand) {
            element.style.top = `${start}px`;
            element.style.height = `${size}px`;
            element.style.right = `${inset}px`;
            lastBand = band;
          }
        }
      }
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
    return () => { cancelAnimationFrame(animation); chart.remove(); state.current = null; liveLines.current = []; };
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
    current.lines = [];
    closed.current = fill != null && filledAt !== undefined && closedAt !== undefined &&
      initialStop !== undefined && finalTarget !== undefined
      ? { start: filledAt, end: closedAt, fill, stop: initialStop, target: finalTarget } : null;
    zone.current = entryLow !== undefined && entryHigh !== undefined ? [entryLow, entryHigh] : null;
    const levels: [string, number | undefined, string][] = [
      ["Entry high", entryHigh, "#e7c778"], ["Entry low", entryLow, "#e7c778"],
      ["SL", stop, "#ed8b7e"],
      ["TP1", stop === target1 ? undefined : target1, "#6abca4"],
      ["TP2", target2, "#6abca4"], ["TP3", target3, "#6abca4"],
    ];
    scaleRange.current = levels.flatMap(([, price]) => price === undefined ? [] : [price]);
    for (const [title, price, color] of levels) {
      if (price !== undefined) current.lines.push(current.series.createPriceLine({
        price, color, title, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true,
        axisLabelTextColor: "#121412",
      }));
    }
  }, [entryLow, entryHigh, stop, target1, target2, target3, closedAt, fill, filledAt, initialStop, finalTarget]);
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
      liveLines.current[0].applyOptions({ price: bid });
      liveLines.current[1].applyOptions({ price: ask });
      return;
    }
    liveLines.current = [
      series.createPriceLine({ price: bid, title: "Bid", color: "#83d5ba", lineWidth: 1, axisLabelTextColor: "#121412" }),
      series.createPriceLine({ price: ask, title: "Ask", color: "#a8bdf3", lineWidth: 1, lineStyle: LineStyle.Dotted, axisLabelTextColor: "#121412" }),
    ];
  }, [bid, ask]);
  return <div className="chart-shell">
    <div ref={host} className="chart" role="img" aria-label={`XAUUSD ${frame} candlestick chart. Exact signal levels are listed below.`} />
    <div ref={shade} className="entry-shade" hidden aria-hidden="true" />
    <div ref={rewardBox} className="trade-box trade-reward" hidden aria-hidden="true"><span>{outcome}</span></div>
    <div ref={riskBox} className="trade-box trade-risk" hidden aria-hidden="true" />
  </div>;
}
