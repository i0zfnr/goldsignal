"""Strategy B v2: H1 bias, M15 liquidity zones, M5 rejection, M1 confirmation.

Deterministic Katana-inspired scalping rules. No AI, no look-ahead.
Frozen parameters below are the versioned configuration.
"""

from .config import MAX_SPREAD, SYMBOL
from .strategy import compare_pattern

PARAMS = dict(
    version="katana_v1",
    swing=2,
    displacement=1.5,
    median_window=20,
    zone_source_window=6,
    max_zone_height=6.0,
    stop_buffer=0.10,
    band=0.25,
    targets=(1.0, 1.5),
    hold_seconds=1800,
    entry_window=300,
    zone_ttl=48 * 900,
    max_spread=0.5,
)


def closed(bars, period, now):
    return [bar for bar in bars if bar["time"] + period <= now]


def _body(bar):
    return abs(bar["close"] - bar["open"])


def swings(bars, size=PARAMS["swing"], period=900):
    result = []
    for index in range(size, len(bars) - size):
        bar = bars[index]
        left = bars[index - size:index]
        right = bars[index + 1:index + size + 1]
        others = left + right
        confirmed = right[-1]["time"] + period
        if bar["high"] > max(row["high"] for row in others):
            result.append(dict(index=index, kind="high", price=bar["high"], time=bar["time"],
                               confirmed=confirmed))
        if bar["low"] < min(row["low"] for row in others):
            result.append(dict(index=index, kind="low", price=bar["low"], time=bar["time"],
                               confirmed=confirmed))
    return result


def bias(bars, period=900):
    rows = swings(bars, period=period)
    highs = [row for row in rows if row["kind"] == "high"][-2:]
    lows = [row for row in rows if row["kind"] == "low"][-2:]
    reading = dict(direction="neutral", high_at=None, low_at=None,
                   highs=[row["price"] for row in highs], lows=[row["price"] for row in lows])
    if len(highs) < 2 or len(lows) < 2:
        return reading
    reading["high_at"] = highs[-1]["confirmed"]
    reading["low_at"] = lows[-1]["confirmed"]
    if highs[0]["price"] < highs[1]["price"] and lows[0]["price"] < lows[1]["price"]:
        reading["direction"] = "bullish"
    elif highs[0]["price"] > highs[1]["price"] and lows[0]["price"] > lows[1]["price"]:
        reading["direction"] = "bearish"
    return reading


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def zones(bars, now):
    result = []
    pending = swings(bars, period=900)
    for index, bar in enumerate(bars):
        prior = bars[max(0, index - PARAMS["median_window"]):index]
        if len(prior) < PARAMS["median_window"]:
            continue
        threshold = PARAMS["displacement"] * _median(_body(row) for row in prior)
        if _body(bar) < threshold:
            continue
        created = bar["time"] + 900
        if created > now:
            continue
        med_body = _median(_body(row) for row in prior)
        disp_body = _body(bar)
        disp_ratio = disp_body / med_body if med_body > 0 else 1.5
        base_power = 7 + int((disp_ratio - 1.5) * 2)
        power = min(10, max(7, base_power))
        if bar["close"] < bar["open"]:
            broken = [row for row in pending if row["kind"] == "low"
                      and row["confirmed"] <= bar["time"] and bar["close"] < row["price"] and row["index"] < index]
            if not broken:
                continue
            source = next((row for row in reversed(bars[max(0, index - PARAMS["zone_source_window"]):index])
                           if row["close"] > row["open"]), None)
            if source is None:
                continue
            direction = "SELL"
            raw_top = source["high"]
            raw_bot = source["low"]
            if raw_top - raw_bot > PARAMS["max_zone_height"]:
                body_bot = min(source["open"], source["close"])
                raw_bot = body_bot if (raw_top - body_bot <= PARAMS["max_zone_height"]) else round(raw_top - PARAMS["max_zone_height"], 2)
            top, bottom = raw_top, raw_bot
            swing = broken[-1]
        elif bar["close"] > bar["open"]:
            broken = [row for row in pending if row["kind"] == "high"
                      and row["confirmed"] <= bar["time"] and bar["close"] > row["price"] and row["index"] < index]
            if not broken:
                continue
            source = next((row for row in reversed(bars[max(0, index - PARAMS["zone_source_window"]):index])
                           if row["close"] < row["open"]), None)
            if source is None:
                continue
            direction = "BUY"
            raw_top = source["high"]
            raw_bot = source["low"]
            if raw_top - raw_bot > PARAMS["max_zone_height"]:
                body_top = max(source["open"], source["close"])
                raw_top = body_top if (body_top - raw_bot <= PARAMS["max_zone_height"]) else round(raw_bot + PARAMS["max_zone_height"], 2)
            top, bottom = raw_top, raw_bot
            swing = broken[-1]
        else:
            continue
        invalidated = None
        mitigated = None
        for later in bars[index + 1:]:
            later_close_time = later["time"] + 900
            if later_close_time > now:
                break
            if direction == "SELL":
                if later["close"] > top:
                    invalidated = later_close_time
                    break
                if later["high"] >= bottom and mitigated is None:
                    mitigated = later_close_time
            elif direction == "BUY":
                if later["close"] < bottom:
                    invalidated = later_close_time
                    break
                if later["low"] <= top and mitigated is None:
                    mitigated = later_close_time
        final_power = max(5, power - 2) if mitigated else power
        confidence = "HIGH" if final_power >= 7 else "MEDIUM"
        result.append(dict(
            id=f"z_{direction}_{bar['time']}", direction=direction, top=top, bottom=bottom,
            candle=bar["time"], created=created,
            power=final_power, confidence=confidence,
            source=dict(time=source["time"], open=source["open"], high=source["high"],
                        low=source["low"], close=source["close"]),
            swing=dict(price=swing["price"], time=swing["time"], confirmed=swing["confirmed"]),
            broken_at=bar["close"], invalidated=invalidated, mitigated=mitigated,
            expired=created + PARAMS["zone_ttl"],
        ))
    return result


def deduplicate_zones(zones_):
    result = []
    for z in zones_:
        overlap = False
        for chosen in result:
            if chosen["direction"] == z["direction"]:
                overlap_height = min(chosen["top"], z["top"]) - max(chosen["bottom"], z["bottom"])
                if overlap_height > 0:
                    min_height = min(chosen["top"] - chosen["bottom"], z["top"] - z["bottom"])
                    if min_height > 0 and overlap_height / min_height >= 0.4:
                        overlap = True
                        break
        if not overlap:
            result.append(z)
    return result


def active(zones_, now, price):
    # Only active (un-invalidated, unexpired)
    rows = [row for row in zones_ if (row["invalidated"] is None or row["invalidated"] > now) and row["expired"] > now]
    rows = deduplicate_zones(rows)

    def rank_key(r):
        # Prioritize: 1. Unmitigated fresh (0 vs 1), 2. Higher power (-power), 3. Distance to price
        return (
            1 if r.get("mitigated") else 0,
            -r.get("power", 7),
            abs(price - (r["top"] + r["bottom"]) / 2)
        )

    sells = [r for r in rows if r["direction"] == "SELL"]
    buys = [r for r in rows if r["direction"] == "BUY"]
    sells.sort(key=rank_key)
    buys.sort(key=rank_key)

    # Return at most 2 or 3 high confidence zones (e.g. 1 Sell + 1 Buy + 1 best alternate)
    selected = []
    if sells and buys:
        selected.append(sells[0])
        selected.append(buys[0])
        rem = sells[1:] + buys[1:]
        if rem:
            rem.sort(key=rank_key)
            selected.append(rem[0])
    elif sells:
        selected = sells[:3]
    elif buys:
        selected = buys[:3]

    selected.sort(key=lambda r: abs(price - (r["top"] + r["bottom"]) / 2))
    return selected


def _find_rejections(m5, zone, now):
    rejections = []
    for bar in m5:
        close_time = bar["time"] + 300
        if close_time <= zone["created"]:
            continue
        if close_time > now:
            break
        overlap = bar["high"] >= zone["bottom"] and bar["low"] <= zone["top"]
        if not overlap:
            continue
        if zone["direction"] == "SELL" and bar["close"] < zone["bottom"]:
            rejections.append(dict(time=close_time, bar_time=bar["time"], high=bar["high"],
                                   low=bar["low"], close=bar["close"]))
        elif zone["direction"] == "BUY" and bar["close"] > zone["top"]:
            rejections.append(dict(time=close_time, bar_time=bar["time"], high=bar["high"],
                                   low=bar["low"], close=bar["close"]))
    return rejections


def _confirmation(m1, rejection, now, direction):
    limit = rejection["time"] + PARAMS["entry_window"]
    for index, bar in enumerate(m1):
        close_time = bar["time"] + 60
        if close_time <= rejection["time"] or index < 3:
            continue
        if close_time > min(limit, now):
            break
        prior = m1[index - 3:index]
        if direction == "SELL" and bar["close"] < min(row["low"] for row in prior):
            return dict(time=close_time, close=bar["close"], bar=bar)
        if direction == "BUY" and bar["close"] > max(row["high"] for row in prior):
            return dict(time=close_time, close=bar["close"], bar=bar)
    return None


def calculate_grade(zone, rejection, trigger, snapshot, risk, mtf_aligned=True):
    score = 0
    if mtf_aligned:
        score += 1
    if not zone.get("mitigated") and zone.get("power", 0) >= 8:
        score += 1
    if rejection:
        rng = rejection["high"] - rejection["low"]
        if rng > 0:
            wick = (rejection["high"] - rejection["close"]) if zone["direction"] == "SELL" else (rejection["close"] - rejection["low"])
            if wick / rng >= 0.35:
                score += 1
    quote = snapshot.get("quote") or {}
    spread = round(quote.get("ask", 0) - quote.get("bid", 0), 2) if quote.get("ask") else 0.30
    if risk <= 2.00 and spread <= 0.40:
        score += 1
    return {4: "A+", 3: "A", 2: "B+", 1: "B", 0: "B"}.get(score, "B")


def _candidate(zone, rejection, trigger, snapshot, m15_closed, mtf_aligned=True):
    ref = trigger["close"]
    if zone["direction"] == "SELL":
        stop = round(rejection["high"] + PARAMS["stop_buffer"], 2)
        risk = round(stop - ref, 2)
        better_price = round(ref + risk * PARAMS["band"], 2)
        band = sorted([ref, better_price])
        sign = -1
    else:
        stop = round(rejection["low"] - PARAMS["stop_buffer"], 2)
        risk = round(ref - stop, 2)
        better_price = round(ref - risk * PARAMS["band"], 2)
        band = sorted([better_price, ref])
        sign = 1
    if risk <= 0:
        return None
    target = [round(ref + sign * risk * multiple, 2) for multiple in PARAMS["targets"]]
    symbol = snapshot.get("symbol", SYMBOL)
    trend_closes = {"15": [row["close"] for row in m15_closed[-4:]]}
    pattern = compare_pattern(m15_closed, sign)
    swing_price = (zone.get("swing") or {}).get("price", zone["top"] if zone["direction"] == "SELL" else zone["bottom"])
    grade = calculate_grade(zone, rejection, trigger, snapshot, risk, mtf_aligned=mtf_aligned)
    return dict(
        id=f"b2_{zone['id']}_{rejection['time']}_{zone['direction']}", symbol=symbol,
        strategy="B · liquidity scalp", strategy_version=PARAMS["version"], direction=zone["direction"],
        grade=grade,
        reference=ref, entry=band, initial_stop=stop, stop=stop, targets=target,
        max_spread=min(PARAMS["max_spread"], risk * 0.2), hold_seconds=PARAMS["hold_seconds"],
        created=trigger["time"], expiry=min(trigger["time"] + PARAMS["entry_window"], zone["expired"]),
        hits=0, exits=[], status="PENDING", fill=None,
        result_per_lot=0 if snapshot.get("spec") else None, costs=snapshot.get("spec"),
        evidence=dict(
            grade=f"{grade} · Liquidity scalp",
            entry_grade=grade,
            reason=(f"[{grade} SETUP] M15 {'supply' if zone['direction'] == 'SELL' else 'demand'} zone "
                    f"{zone['bottom']:.2f}–{zone['top']:.2f} with M5 rejection and M1 confirmation."),
            zone=zone, watch_zone=[zone["bottom"], zone["top"]], rejection=rejection,
            trigger=trigger["bar"], candle=trigger["bar"],
            swing={"low": swing_price, "high": swing_price},
            trend_closes=trend_closes, pattern=pattern,
        ),
    )


def analyze(snapshot, mtf="M15"):
    now = snapshot["now"]
    quote = snapshot.get("quote") or {}
    price = quote.get("bid") or quote.get("ask") or 0.0
    m15 = closed(snapshot.get("bars", []), 900, now)
    frames = snapshot.get("frames", {})
    h1 = closed(frames.get("H1", []), 3600, now)
    m30 = closed(frames.get("M30", []), 1800, now)
    m5 = closed(frames.get("M5", []), 300, now)
    m1 = closed(frames.get("M1", []), 60, now)

    def safe_bias(series, period):
        if len(series) >= 2 * PARAMS["swing"] + 2:
            return bias(series, period=period)
        if len(series) >= 2:
            delta = series[-1]["close"] - series[0]["close"]
            d = "bullish" if delta > 0.05 else "bearish" if delta < -0.05 else "neutral"
            return dict(direction=d, high_at=series[-1]["time"], low_at=series[-1]["time"], highs=[], lows=[])
        return dict(direction="neutral", high_at=None, low_at=None, highs=[], lows=[])

    h1_bias = safe_bias(h1, 3600)
    m30_bias = safe_bias(m30, 1800)
    m15_bias = safe_bias(m15, 900)
    m5_bias = safe_bias(m5, 300)

    primary_bias = m15_bias if mtf == "M15" else h1_bias
    context_bias = m5_bias if mtf == "M15" else m15_bias

    all_zones = zones(m15, now)
    live_zones = active(all_zones, now, price)
    fresh_sells = [row for row in live_zones if row["direction"] == "SELL" and not row.get("mitigated")]
    fresh_buys = [row for row in live_zones if row["direction"] == "BUY" and not row.get("mitigated")]
    nearest_sell = fresh_sells[0] if fresh_sells else next((row for row in live_zones if row["direction"] == "SELL"), None)
    nearest_buy = fresh_buys[0] if fresh_buys else next((row for row in live_zones if row["direction"] == "BUY"), None)

    report = dict(
        version=PARAMS["version"], mtf=mtf, now=now, price=price,
        h1=h1_bias, m30=m30_bias, m15=m15_bias, m5=m5_bias,
        primary_bias=primary_bias, context_bias=context_bias,
        tf_bias=dict(M5=m5_bias.get("direction", "neutral"),
                     M15=m15_bias.get("direction", "neutral"),
                     M30=m30_bias.get("direction", "neutral"),
                     H1=h1_bias.get("direction", "neutral")),
        zones=live_zones[:3], nearest_sell=nearest_sell, nearest_buy=nearest_buy,
        next_step=f"WAITING FOR {mtf} DIRECTION", reason=None,
        candidate=None, rejection=None, trigger=None, zone=None,
    )
    if not live_zones:
        report["next_step"] = "WATCH BUY" if primary_bias.get("direction") == "bullish" else (
            "WATCH SELL" if primary_bias.get("direction") == "bearish" else f"WAITING FOR {mtf} DIRECTION"
        )
        report["reason"] = "No active M15 liquidity zone."
        return report

    wanted = {"bearish": "SELL", "bullish": "BUY"}.get(primary_bias.get("direction"))
    chosen_zone = next((row for row in live_zones if row["direction"] == wanted), live_zones[0])
    report["zone"] = chosen_zone

    candidate_found = None
    latest_rejection = None
    for zone in ([chosen_zone] if wanted else live_zones[:2]):
        rejections = _find_rejections(m5, zone, now)
        if rejections:
            latest_rejection = rejections[-1]
            report["rejection"] = latest_rejection
            for rej in reversed(rejections):
                trig = _confirmation(m1, rej, now, zone["direction"])
                if trig:
                    cand = _candidate(zone, rej, trig, snapshot, m15, mtf_aligned=(wanted == zone["direction"]))
                    if cand:
                        candidate_found = cand
                        report["rejection"] = rej
                        report["trigger"] = trig
                        break
        if candidate_found:
            break

    if candidate_found and wanted == candidate_found["direction"]:
        if now > candidate_found["expiry"]:
            report["candidate"] = None
            report["next_step"] = "EXPIRED"
            report["reason"] = f"M1 confirmation window expired. Waiting for fresh M5 rejection."
            return report
        report["candidate"] = candidate_found
        report["next_step"] = "ENTRY READY"
        report["reason"] = candidate_found["evidence"]["reason"]
        return report

    if candidate_found and wanted != candidate_found["direction"]:
        report["reason"] = f"M1 confirmation exists but {mtf} direction disagrees."
        report["next_step"] = "WATCH BUY" if wanted == "BUY" else "WATCH SELL" if wanted == "SELL" else f"WAITING FOR {mtf} DIRECTION"
        return report

    if primary_bias.get("direction") == "neutral":
        report["next_step"] = "WATCH BUY" if chosen_zone["direction"] == "BUY" else "WATCH SELL"
        report["reason"] = f"{mtf} structure is neutral; watch zone only, no entry."
    elif latest_rejection and now <= latest_rejection["time"] + PARAMS["entry_window"]:
        report["next_step"] = "WAITING FOR M1 CONFIRMATION"
        report["reason"] = "M5 rejection found; waiting for a closed M1 break."
    else:
        report["next_step"] = "WAITING FOR M5 REJECTION"
        report["reason"] = "Zone active; waiting for a completed M5 rejection."
    return report
