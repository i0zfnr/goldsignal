from collections import defaultdict
from decimal import Decimal, ROUND_FLOOR
from statistics import median

from .config import MAX_SPREAD, STALE_SECONDS, SWING, TREND, ZONE_WIDTH, SYMBOL, session

PATTERN_HISTORY = 1000


def compare_pattern(closed, sign):
    bars = closed[-(PATTERN_HISTORY + 9):]
    if len(bars) < 9:
        return {"history": max(0, len(bars) - 1), "rsi8": None, "matches": 0, "next4_bps": None}
    gains = losses = 0.0
    features = {}
    for i, (previous, bar) in enumerate(zip(bars, bars[1:]), 1):
        change = bar["close"] - previous["close"]
        gain, loss = max(change, 0), max(-change, 0)
        if i <= 8:
            gains += gain / 8
            losses += loss / 8
        else:
            gains = (7 * gains + gain) / 8
            losses = (7 * losses + loss) / 8
        if i >= 8:
            rsi = 100 * gains / (gains + losses) if gains + losses else 50
            change4 = 10000 * (bar["close"] / bars[i - 4]["close"] - 1)
            spread = bar["high"] - bar["low"]
            body = (bar["close"] - bar["open"]) / spread if spread > 0 else 0
            features[i] = (rsi, change4, body)
    newest = len(bars) - 1
    current = features[newest]
    comparisons = []
    for i in range(max(8, newest - PATTERN_HISTORY), newest - 4):
        if bars[i + 4]["time"] - bars[i - 4]["time"] != 8 * 900:
            continue
        distance = sum(abs(a - b) / scale for a, b, scale in zip(current, features[i], (20, 20, 0.5)))
        move = 10000 * sign * (bars[i + 4]["close"] / bars[i]["close"] - 1)
        comparisons.append((distance, move))
    matches = sorted(comparisons)[:5]
    return {"history": min(PATTERN_HISTORY, newest), "rsi8": round(current[0], 1),
            "matches": len(matches), "next4_bps": round(median(move for _, move in matches), 2) if matches else None}


def aggregate(bars, period):
    groups = defaultdict(list)
    for bar in bars:
        groups[bar["time"] // period * period].append(bar)
    return [
        (start, group[-1]["close"]) for start, group in groups.items()
        if [bar["time"] for bar in group] == list(range(start, start + period, 900))
    ]


def setup(bars, now):
    closed = [bar for bar in bars if bar["time"] + 900 <= now]
    if len(closed) < max(4 * TREND, 2 * SWING + 2):
        return None
    candle = closed[-1]
    trends = {}
    for period in (900, 1800, 3600):
        series = aggregate(closed, period)[-TREND:]
        if len(series) != TREND or series[-1][0] + period != (candle["time"] + 900) // period * period:
            return None
        if any(b[0] - a[0] != period for a, b in zip(series, series[1:])):
            return None
        trends[str(period // 60)] = [price for _, price in series]
    for direction, field, sign in (("BUY", "low", 1), ("SELL", "high", -1)):
        if not all(sign * (prices[-1] - prices[0]) > 0 and
                   sign * (prices[-1] - sum(prices) / len(prices)) > 0 for prices in trends.values()):
            continue
        wick = min(candle["open"], candle["close"]) - candle["low"] if sign == 1 else (
            candle["high"] - max(candle["open"], candle["close"])
        )
        if sign * (candle["close"] - candle["open"]) <= 0 or wick < abs(candle["close"] - candle["open"]):
            continue
        for i in range(len(closed) - SWING - 2, max(SWING - 1, len(closed) - 49), -1):
            level = closed[i][field]
            neighbors = closed[i - SWING:i] + closed[i + 1:i + SWING + 1]
            if not all(sign * (b[field] - level) > 0 for b in neighbors):
                continue
            if abs(candle[field] - level) <= ZONE_WIDTH and sign * (candle["close"] - level) > ZONE_WIDTH:
                return {
                    "direction": direction, "candle": candle, "swing": closed[i],
                    "swing_confirmed": closed[i + SWING]["time"] + 900, "trend_closes": trends,
                    "pattern": compare_pattern(closed, sign),
                    "grade": "Aligned",
                    "reason": f"Rejected M15 {'support' if sign == 1 else 'resistance'} with M15, M30 and H1 trend agreement.",
                }
    return None


def levels(direction, reference):
    e = Decimal(str(reference))
    sign = 1 if direction == "BUY" else -1
    other = e - 3 * sign
    stop = e - 6 * sign
    return {
        "reference": float(e), "entry": [float(min(e, other)), float(max(e, other))],
        "initial_stop": float(stop), "stop": float(stop),
        "targets": [float(e + sign * n) for n in (3, 6, 10)],
    }


def executable(signal, quote, exit_side=False):
    return quote["ask" if (signal["direction"] == "BUY") != exit_side else "bid"]


def gate(signal, quote, now, news_reason=None):
    if now >= signal["expiry"] or not session(now)["open"]:
        return "REJECT", "Entry session or candidate expired"
    if not quote or not quote["available"] or not -2 <= now - quote["time"] <= STALE_SECONDS:
        return "WAIT", "Broker quote unavailable or stale"
    if quote.get("permission") not in (None, "BOTH", signal["direction"]):
        return "REJECT", "Broker symbol does not allow this direction"
    if quote["ask"] - quote["bid"] > MAX_SPREAD:
        return "WAIT", "Spread exceeds configured limit"
    if not signal["entry"][0] <= executable(signal, quote) <= signal["entry"][1]:
        return "WAIT", "Executable quote is outside the entry zone"
    if news_reason:
        return "WAIT", news_reason
    return "CONFIRM", "Executable quote, spread, session and calendar passed"


def account_fit(signal, profile, spec, now, realized=0, profile_now=None):
    def skip(reason, **values):
        return {"decision": "SKIP", "reason": reason, **values}

    if not profile or not spec or spec["symbol"] != profile["symbol"] or profile["symbol"] != SYMBOL:
        return skip("Matching broker specifications required")
    if now - spec["time"] > spec["max_age"]:
        return skip("Broker specifications are stale")
    if (now if profile_now is None else profile_now) - profile["updated"] > profile["max_age"]:
        return skip("Refresh equity and free margin")
    if profile["currency"] != spec["account_currency"]:
        return skip("Account currency does not match the broker estimate")
    d = lambda value: Decimal(str(value))
    unit = d(profile["units_per_currency"])
    if unit != d(spec["units_per_currency"]):
        return skip("Account units do not match the broker estimate")
    equity = d(profile["equity"]) / unit
    budget = equity * d(profile["risk_pct"]) / 100
    entry = d(signal["entry"][1 if signal["direction"] == "BUY" else 0])
    distance = abs(entry - d(signal["initial_stop"]))
    minimum, step = d(spec["minimum"]), d(spec["step"])
    contract, conversion = d(spec["contract"]), d(spec["conversion"])
    base_per_lot = distance * contract * conversion
    loss_per_lot = base_per_lot + d(spec["slippage"]) * contract * conversion + d(spec["commission"])
    margin_per_lot = d(signal["entry"][1]) * contract * conversion * d(spec["margin_rate"])
    margin_cap = d(profile["free_margin"]) / unit
    minimum_loss = minimum * loss_per_lot
    values = {
        "currency": profile["currency"], "budget": float(budget), "minimum": float(minimum),
        "minimum_before_cost": float(minimum * base_per_lot), "loss": float(minimum_loss),
        "loss_pct": float(minimum_loss / equity * 100), "margin": float(minimum * margin_per_lot),
    }
    if d(realized) <= -(equity * d(profile["daily_loss_pct"]) / 100):
        return skip("Tracked daily loss limit reached", **values)
    if minimum_loss > budget:
        return skip("Minimum lot exceeds risk budget", **values)
    if minimum * margin_per_lot > margin_cap:
        return skip("Free margin is below minimum-lot estimate", **values)
    cap = min(budget / loss_per_lot, margin_cap / margin_per_lot, d(spec["maximum"]))
    lot = minimum + ((cap - minimum) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    split_min = minimum * 3
    if lot < split_min or (lot - split_min) % step:
        if profile["exit_policy"] != "single":
            return skip("Size cannot split across three broker-valid exits. Select the separate TP1-only demo policy.", **values)
    if profile["exit_policy"] == "single" and not spec["demo"]:
        return skip("TP1-only policy is available in demo", **values)
    return {
        **values, "decision": "FIT", "reason": "Estimated stop loss and margin fit profile limits",
        "lot": float(lot), "loss": float(lot * loss_per_lot),
        "loss_pct": float(lot * loss_per_lot / equity * 100), "margin": float(lot * margin_per_lot),
    }
