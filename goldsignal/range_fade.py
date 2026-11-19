"""Strategy C: Asian Range Liquidity Sweep & Fade.

Active during Sydney/Tokyo sessions (06:00 - 15:00 MYT).
Identifies Asian session balance range (06:00 - 10:00 MYT).
Fades false breakouts / liquidity sweeps back toward the session mean.
"""

from datetime import datetime
from zoneinfo import ZoneInfo
from .config import SYMBOL

MY = ZoneInfo("Asia/Kuala_Lumpur")


def asian_range_candidate(snapshot, m5_bars, m15_bars):
    now = snapshot["now"]
    dt = datetime.fromtimestamp(now, MY)
    hour = dt.hour + dt.minute / 60.0

    # Active window for sweep trades: 09:30 to 15:00 MYT
    if not (9.5 <= hour < 15.5):
        return None, "Outside Asian sweep trading window (09:30–15:30 MYT)."

    if len(m5_bars) < 20:
        return None, "Waiting for Asian M5 candle history."

    # Bars since 06:00 MYT today
    start_today = int(dt.replace(hour=6, minute=0, second=0, microsecond=0).timestamp())
    session_bars = [b for b in m5_bars if b["time"] >= start_today and b["time"] + 300 <= now]
    if len(session_bars) < 12:
        return None, "Building Asian session balance range (min 12 candles)."

    # Define the range high and low from the first 2-3 hours (06:00 - 09:00 MYT)
    base_bars = [b for b in session_bars if b["time"] < start_today + 3 * 3600]
    if len(base_bars) < 8:
        base_bars = session_bars[:12]

    range_high = max(b["high"] for b in base_bars)
    range_low = min(b["low"] for b in base_bars)
    range_height = range_high - range_low

    if not (2.0 <= range_height <= 10.0):
        return None, f"Asian range height ({range_height:.2f}) outside scalp limits (2.0–10.0)."

    mid = round((range_high + range_low) / 2, 2)
    latest = session_bars[-1]
    prev = session_bars[-2]

    # SELL Sweep: Candle wicked above range_high and closed back inside range
    if latest["high"] > range_high and latest["close"] < range_high and latest["close"] < latest["open"]:
        stop = round(latest["high"] + 0.15, 2)
        ref = latest["close"]
        risk = round(stop - ref, 2)
        if 0.5 <= risk <= 2.5:
            band = sorted([ref, round(ref + risk * 0.25, 2)])
            targets = [mid, round(range_low + 0.5, 2)]
            return dict(
                id=f"c_asian_{latest['time']}_SELL", symbol=snapshot.get("symbol", SYMBOL),
                strategy="C · Asian range fade", strategy_version="asian_fade_v1", direction="SELL",
                reference=ref, entry=band, initial_stop=stop, stop=stop, targets=targets,
                max_spread=min(0.40, risk * 0.2), hold_seconds=2700,
                created=latest["time"] + 300, expiry=latest["time"] + 900,
                hits=0, exits=[], status="PENDING", fill=None,
                result_per_lot=0 if snapshot.get("spec") else None, costs=snapshot.get("spec"),
                evidence=dict(
                    grade="C · Asian range fade",
                    reason=f"Asian high ({range_high:.2f}) swept at {latest['high']:.2f}. Fading back toward mid ({mid:.2f}).",
                    range_high=range_high, range_low=range_low, mid=mid, sweep_bar=latest,
                ),
            ), f"SELL sweep confirmed at {range_high:.2f}."

    # BUY Sweep: Candle wicked below range_low and closed back inside range
    if latest["low"] < range_low and latest["close"] > range_low and latest["close"] > latest["open"]:
        stop = round(latest["low"] - 0.15, 2)
        ref = latest["close"]
        risk = round(ref - stop, 2)
        if 0.5 <= risk <= 2.5:
            band = sorted([round(ref - risk * 0.25, 2), ref])
            targets = [mid, round(range_high - 0.5, 2)]
            return dict(
                id=f"c_asian_{latest['time']}_BUY", symbol=snapshot.get("symbol", SYMBOL),
                strategy="C · Asian range fade", strategy_version="asian_fade_v1", direction="BUY",
                reference=ref, entry=band, initial_stop=stop, stop=stop, targets=targets,
                max_spread=min(0.40, risk * 0.2), hold_seconds=2700,
                created=latest["time"] + 300, expiry=latest["time"] + 900,
                hits=0, exits=[], status="PENDING", fill=None,
                result_per_lot=0 if snapshot.get("spec") else None, costs=snapshot.get("spec"),
                evidence=dict(
                    grade="C · Asian range fade",
                    reason=f"Asian low ({range_low:.2f}) swept at {latest['low']:.2f}. Fading back toward mid ({mid:.2f}).",
                    range_high=range_high, range_low=range_low, mid=mid, sweep_bar=latest,
                ),
            ), f"BUY sweep confirmed at {range_low:.2f}."

    return None, f"Watching Asian range ({range_low:.2f} – {range_high:.2f}, mid {mid:.2f}). No sweep."
