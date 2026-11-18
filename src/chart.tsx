import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, createChart, LineStyle,
  type AutoscaleInfo, type IChartApi, type IPriceLine, type ISeriesApi, type UTCTimestamp,
} from "lightweight-charts";
import type { Candle, Signal } from "./types";

type ChartState = {
  chart: IChartApi; series: ISeriesApi<"Candlestick">; lines: IPriceLine[];
  data: Map<number, Candle>; last?: UTCTimestamp;
};

export function Chart({ candles, signal }: { candles: Candle[]; signal: Signal | null }) {
  const host = useRef<HTMLDivElement>(null);
  const shade = useRef<HTMLDivElement>(null);
  const state = useRef<ChartState | null>(null);
  const zone = useRef<[number, number] | null>(null);
  const scaleRange = useRef<number[]>([]);
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
      animation = requestAnimationFrame(positionBand);
    }
    animation = requestAnimationFrame(positionBand);
    return () => { cancelAnimationFrame(animation); chart.remove(); state.current = null; };
  }, []);

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

  const entryLow = signal?.entry[0], entryHigh = signal?.entry[1], stop = signal?.stop;
  const target1 = signal?.targets[0], target2 = signal?.targets[1], target3 = signal?.targets[2];
  useEffect(() => {
    const current = state.current;
    if (!current) return;
    current.lines.forEach((line) => current.series.removePriceLine(line));
    current.lines = [];
    zone.current = entryLow !== undefined && entryHigh !== undefined ? [entryLow, entryHigh] : null;
    const levels: [string, number | undefined, string][] = [
      ["Entry high", entryHigh, "#e7c778"], ["Entry low", entryLow, "#e7c778"],
      [stop === target1 ? "SL / TP1" : "SL", stop, "#ed8b7e"],
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
  }, [entryLow, entryHigh, stop, target1, target2, target3]);
  return <div className="chart-shell">
    <div ref={host} className="chart" role="img" aria-label="XAUUSD M15 candlestick chart. Exact signal levels are listed below." />
    <div ref={shade} className="entry-shade" hidden aria-hidden="true" />
  </div>;
}
