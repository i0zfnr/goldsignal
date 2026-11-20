"""Sora: session volatility regime analyst for London and New York."""

from statistics import median

from .sessions import label

AGGRESSIVE_SESSIONS = {"London", "New York"}
EXPANSION_RATIO = 1.3
COMPRESSION_RATIO = 0.7


def _true_range(bar, previous_close):
    return max(bar["high"] - bar["low"],
               abs(bar["high"] - previous_close),
               abs(bar["low"] - previous_close))


def analyze(bars, now, direction="SELL"):
    closed = [bar for bar in bars if bar["time"] + 900 <= now][-300:]
    session = label(now)
    base = {"session": session, "regime": "NORMAL", "volatility_ratio": None,
            "aligned": False, "aggressive": session in AGGRESSIVE_SESSIONS,
            "summary": "Building session volatility baseline"}
    if len(closed) < 40:
        return base

    ranges = []
    for index in range(1, len(closed)):
        ranges.append(_true_range(closed[index], closed[index - 1]["close"]))
    baseline = median(ranges[:-14])
    current = median(ranges[-14:])
    ratio = float(round(current / baseline, 2)) if baseline else 1.0
    regime = "EXPANSION" if ratio >= EXPANSION_RATIO else (
        "COMPRESSION" if ratio <= COMPRESSION_RATIO else "NORMAL")

    closes = [bar["close"] for bar in closed[-8:]]
    midpoint = median(closes)
    aligned = bool(closes[-1] < midpoint) if direction == "SELL" else bool(closes[-1] > midpoint)
    aggressive = bool(session in AGGRESSIVE_SESSIONS or regime == "EXPANSION")
    return {
        "session": session, "regime": regime, "volatility_ratio": ratio,
        "aligned": aligned, "aggressive": aggressive,
        "summary": f"{session or 'Off-session'} · {regime} ({ratio}x baseline) · "
                   f"{'with' if aligned else 'against'} {direction} flow",
    }
