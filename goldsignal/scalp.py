from .config import MAX_SPREAD, SYMBOL, session
from .strategy import compare_pattern

SETUP_BARS = 6
SETUP_WINDOW = 300
ENTRY_WINDOW = 120
HOLD_SECONDS = 1800


def closed_bars(bars, seconds, now):
    return [bar for bar in bars if bar["time"] + seconds <= now]


def contiguous(bars, seconds, count):
    return len(bars) == count and all(b["time"] - a["time"] == seconds for a, b in zip(bars, bars[1:]))


def scalp_candidate(snapshot, m5, m1):
    now = snapshot["now"]
    window = session(now)
    if snapshot["closed"] or not window["open"]:
        return None, "Outside the entry session."
    m5 = closed_bars(m5, 300, now)[-(SETUP_BARS + 1):]
    m15 = closed_bars(snapshot["bars"], 900, now)[-4:]
    if not contiguous(m5, 300, SETUP_BARS + 1) or not contiguous(m15, 900, 4):
        return None, "Waiting for consecutive closed M5 and M15 bars."
    signal = m5[-1]
    close = signal["time"] + 300
    if not window["opening"] <= close <= now < close + SETUP_WINDOW or now - (m15[-1]["time"] + 900) >= 900:
        return None, "Waiting for a fresh in-session M5 setup."
    high, low = max(bar["high"] for bar in m5[:-1]), min(bar["low"] for bar in m5[:-1])
    trend = m15[-1]["close"] - m15[0]["close"]
    if signal["close"] > max(signal["open"], high) and trend > 0:
        side, sign, boundary = "BUY", 1, high
    elif signal["close"] < min(signal["open"], low) and trend < 0:
        side, sign, boundary = "SELL", -1, low
    else:
        return None, "No M5 breakout aligned with the M15 trend."

    average_range = sum(bar["high"] - bar["low"] for bar in m5[:-1]) / SETUP_BARS
    checks = [bar for bar in closed_bars(m1, 60, now) if bar["time"] >= close]
    for minute, trigger in enumerate(checks):
        if trigger["time"] != close + minute * 60:
            return None, "Waiting for complete M1 retest candles."
        opening, reference = trigger["open"], trigger["close"]
        extreme = trigger["low" if sign == 1 else "high"]
        if abs(extreme - boundary) > average_range * 0.20:
            continue
        if sign * (reference - opening) <= 0 or sign * (reference - boundary) <= 0:
            continue
        stop = round(extreme - sign * max(0.10, average_range * 0.10), 2)
        risk = sign * (reference - stop)
        if risk < 0.10:
            continue
        expiry = min(trigger["time"] + 60 + ENTRY_WINDOW, close + SETUP_WINDOW, window["cutoff"])
        if now >= expiry:
            return None, "M1 entry window expired."
        edges = [round(reference - sign * risk * 0.25, 2), reference]
        return dict(
            id=f"s{close}{side[0]}", symbol=SYMBOL, strategy="M5 setup / M1 entry",
            direction=side, reference=reference, entry=sorted(edges), initial_stop=stop, stop=stop,
            targets=[round(reference + sign * risk * multiple, 2) for multiple in (1, 1.5, 2)],
            max_spread=min(MAX_SPREAD, risk * 0.20), hold_seconds=HOLD_SECONDS,
            created=now, expiry=expiry, hits=0, exits=[], status="PENDING", fill=None,
            result_per_lot=0 if snapshot["spec"] else None, costs=snapshot["spec"],
            evidence={"candle": signal, "trigger": trigger, "swing": {"low": boundary, "high": boundary},
                      "trend_closes": {"15": [bar["close"] for bar in m15]},
                      "pattern": compare_pattern(closed_bars(snapshot["bars"], 900, now), sign),
                      "grade": "M5/M1 scalp",
                      "reason": f"Closed M5 {side.lower()} breakout with M15 trend and closed M1 retest."},
        ), f"{side} M1 retest confirmed."
    return None, f"M5 {side} setup found. Waiting for a closed M1 retest."
