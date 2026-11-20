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
    targets=(1.0, 1.5, 2.0),
    hold_seconds=1800,
    entry_window=1800,
    zone_ttl=48 * 900,
    max_spread=0.5,
    max_zones_per_side=3,
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

    # Also extract institutional Demand & Supply bases at confirmed structural swings
    for row in pending:
        if row["confirmed"] > now:
            continue
        idx = row["index"]
        b = bars[idx]
        if row["kind"] == "low":
            bot = round(row["price"], 2)
            top = round(min(bot + PARAMS["max_zone_height"], max(b["open"], b["close"])), 2)
            if top - bot < 1.0:
                top = round(bot + 3.0, 2)
            inv = None
            mit = None
            for later in bars[idx + 1:]:
                lt = later["time"] + 900
                if lt > now:
                    break
                if later["close"] < bot:
                    inv = lt
                    break
                if later["low"] <= top and mit is None:
                    mit = lt
            result.append(dict(
                id=f"z_BUY_sw_{b['time']}", direction="BUY", top=top, bottom=bot,
                candle=b["time"], created=row["confirmed"],
                power=7 if mit else 8, confidence="HIGH",
                source=dict(time=b["time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"]),
                swing=dict(price=row["price"], time=row["time"], confirmed=row["confirmed"]),
                broken_at=bot, invalidated=inv, mitigated=mit,
                expired=row["confirmed"] + PARAMS["zone_ttl"],
            ))
        elif row["kind"] == "high":
            top = round(row["price"], 2)
            bot = round(max(top - PARAMS["max_zone_height"], min(b["open"], b["close"])), 2)
            if top - bot < 1.0:
                bot = round(top - 3.0, 2)
            inv = None
            mit = None
            for later in bars[idx + 1:]:
                lt = later["time"] + 900
                if lt > now:
                    break
                if later["close"] > top:
                    inv = lt
                    break
                if later["high"] >= bot and mit is None:
                    mit = lt
            result.append(dict(
                id=f"z_SELL_sw_{b['time']}", direction="SELL", top=top, bottom=bot,
                candle=b["time"], created=row["confirmed"],
                power=7 if mit else 8, confidence="HIGH",
                source=dict(time=b["time"], open=b["open"], high=b["high"], low=b["low"], close=b["close"]),
                swing=dict(price=row["price"], time=row["time"], confirmed=row["confirmed"]),
                broken_at=top, invalidated=inv, mitigated=mit,
                expired=row["confirmed"] + PARAMS["zone_ttl"],
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

    # Return up to N best zones per side (default 3 SELL + 3 BUY).
    per_side = PARAMS["max_zones_per_side"]
    selected = sells[:per_side] + buys[:per_side]

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
        overlap = bar["high"] >= zone["bottom"] - 1.0 and bar["low"] <= zone["top"] + 1.0
        if not overlap:
            continue
        rng = bar["high"] - bar["low"]
        if zone["direction"] == "SELL":
            wick = bar["high"] - max(bar["open"], bar["close"])
            if bar["close"] < zone["bottom"] or (rng > 0 and wick / rng >= 0.20 and bar["close"] <= bar["open"] + 0.5):
                rejections.append(dict(time=close_time, bar_time=bar["time"], high=bar["high"],
                                       low=bar["low"], close=bar["close"]))
        elif zone["direction"] == "BUY":
            wick = min(bar["open"], bar["close"]) - bar["low"]
            if bar["close"] > zone["top"] or (rng > 0 and wick / rng >= 0.20 and bar["close"] >= bar["open"] - 0.5):
                rejections.append(dict(time=close_time, bar_time=bar["time"], high=bar["high"],
                                       low=bar["low"], close=bar["close"]))
    return rejections


def _confirmation(m1, rejection, now, direction):
    limit = rejection["time"] + PARAMS["entry_window"]
    for index, bar in enumerate(m1):
        close_time = bar["time"] + 60
        if close_time <= rejection["time"] or index < 1:
            continue
        if close_time > min(limit, now):
            break
        prior = m1[max(0, index - 3):index]
        if direction == "SELL":
            if prior and (bar["close"] < min(row["low"] for row in prior) or (bar["close"] < prior[-1]["low"] and bar["close"] < bar["open"])):
                return dict(time=close_time, close=bar["close"], bar=bar)
        elif direction == "BUY":
            if prior and (bar["close"] > max(row["high"] for row in prior) or (bar["close"] > prior[-1]["high"] and bar["close"] > bar["open"])):
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
    if risk <= 2.50 and spread <= 0.40:
        score += 1
    return {4: "A+", 3: "A", 2: "B+", 1: "B", 0: "B"}.get(score, "B")


def _candidate(zone, rejection, trigger, snapshot, m15_closed, mtf_aligned=True):
    ref = trigger["close"]
    if zone["direction"] == "SELL":
        natural_high = max(rejection["high"], zone["top"])
        stop = round(natural_high + PARAMS["stop_buffer"], 2)
        risk = round(stop - ref, 2)
        if risk <= 0.50:
            risk = 2.0
            stop = round(ref + risk, 2)
        band_high = round(min(stop - 0.20, max(ref + 0.80, ref + risk * 0.25)), 2)
        band_low = round(ref - max(1.20, risk * 0.25), 2)
        band = sorted([band_low, band_high])
        sign = -1
    else:
        natural_low = min(rejection["low"], zone["bottom"])
        stop = round(natural_low - PARAMS["stop_buffer"], 2)
        risk = round(ref - stop, 2)
        if risk <= 0.50:
            risk = 2.0
            stop = round(ref - risk, 2)
        band_low = round(max(stop + 0.20, min(ref - 0.80, ref - risk * 0.25)), 2)
        band_high = round(ref + max(1.20, risk * 0.25), 2)
        band = sorted([band_low, band_high])
        sign = 1
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
        max_spread=min(PARAMS["max_spread"], max(0.40, risk * 0.2)), hold_seconds=PARAMS["hold_seconds"],
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


def _continuation_grade(direction, biases, pullback, bars, risk, quote):
    import_index = next((i for i, row in enumerate(bars) if row["time"] == pullback["time"]), -1)
    prior = bars[max(0, import_index - 4):import_index] if import_index >= 0 else []
    median_body = _median(_body(row) for row in prior) if prior else 0
    aligned = sum(row.get("direction") == direction for row in biases)
    score = 0
    if aligned >= 2:
        score += 1
    if _body(pullback) <= median_body * 0.75 and median_body > 0:
        score += 1
    spread = round(quote.get("ask", 0) - quote.get("bid", 0), 2) if quote.get("ask") else 0.30
    if risk <= 2.50 and spread <= 0.40:
        score += 1
    return {4: "A+", 3: "A"}.get(score + 1, "B+")


def _continuation_candidate(snapshot, m15, m5, m1, biases, now, price):
    sides = {"bullish": "BUY", "bearish": "SELL"}
    normalized = [{"direction": sides.get(row.get("direction"))} for row in biases]
    direction = normalized[-1].get("direction")
    if direction not in sides.values() or len(m5) < 8 or len(m1) < 5:
        return None
    sign = 1 if direction == "BUY" else -1
    pullback = None
    for index in range(len(m5) - 1, max(2, len(m5) - 13), -1):
        bar = m5[index]
        if bar["time"] + 300 > now:
            continue
        counter = bar["close"] < bar["open"] if direction == "BUY" else bar["close"] > bar["open"]
        prior = m5[max(0, index - 3):index]
        impulse = any(sign * (row["close"] - row["open"]) > 0 for row in prior)
        if counter and impulse:
            pullback = bar
            break
    if pullback is None:
        return None
    trigger = _confirmation(m1, {"time": pullback["time"] + 300,
                                 "high": pullback["high"], "low": pullback["low"]}, now, direction)
    if not trigger:
        return None
    ref = trigger["close"]
    buffer = PARAMS["stop_buffer"]
    if direction == "SELL":
        stop = round(max(pullback["high"], trigger["bar"]["high"]) + buffer, 2)
        risk = round(stop - ref, 2)
        if risk <= 0.50:
            risk = 2.0
            stop = round(ref + risk, 2)
        band_high = round(min(stop - 0.20, max(ref + 0.80, ref + risk * 0.25)), 2)
        band_low = round(ref - 0.60, 2)
    else:
        stop = round(min(pullback["low"], trigger["bar"]["low"]) - buffer, 2)
        risk = round(ref - stop, 2)
        if risk <= 0.50:
            risk = 2.0
            stop = round(ref - risk, 2)
        band_low = round(max(stop + 0.20, min(ref - 0.80, ref - risk * 0.25)), 2)
        band_high = round(ref + 0.60, 2)
    entry = sorted([band_low, band_high])
    if entry[1] - entry[0] > 4.0 or entry[0] <= stop < entry[1]:
        return None
    targets = [round(ref + sign * risk * multiple, 2) for multiple in PARAMS["targets"]]
    quote = snapshot.get("quote") or {}
    grade = _continuation_grade(direction, normalized, pullback, m5, risk, quote)
    expiry = min(trigger["time"] + PARAMS["entry_window"], now + PARAMS["entry_window"])
    zone = dict(id=f"trend_{direction}_{trigger['time']}", direction=direction,
                top=pullback["high"], bottom=pullback["low"], created=pullback["time"] + 300,
                power=9 if grade == "A+" else 8, confidence="HIGH", source=pullback,
                swing=dict(price=pullback["low"] if direction == "BUY" else pullback["high"],
                           time=pullback["time"], confirmed=pullback["time"] + 300),
                broken_at=trigger["close"], invalidated=None, mitigated=None, expired=expiry)
    rejection = dict(time=pullback["time"] + 300, bar_time=pullback["time"], high=pullback["high"],
                     low=pullback["low"], close=pullback["close"])
    return dict(
        id=f"b2_cont_{direction}_{trigger['time']}", symbol=snapshot.get("symbol", SYMBOL),
        strategy="B · trend continuation", strategy_version=PARAMS["version"], direction=direction,
        grade=grade, reference=ref, entry=entry, initial_stop=stop, stop=stop, targets=targets,
        max_spread=min(PARAMS["max_spread"], max(0.40, risk * 0.2)), hold_seconds=PARAMS["hold_seconds"],
        created=trigger["time"], expiry=expiry, hits=0, exits=[], status="PENDING", fill=None,
        result_per_lot=0 if snapshot.get("spec") else None, costs=snapshot.get("spec"),
        evidence=dict(grade=f"{grade} · Trend continuation", entry_grade=grade,
                      reason=f"[{grade} SETUP] {'Bullish' if direction == 'BUY' else 'Bearish'} continuation: "
                             f"M5 pullback at {pullback['low']:.2f}–{pullback['high']:.2f} with renewed M1 momentum.",
                      zone=zone, watch_zone=[zone["bottom"], zone["top"]], rejection=rejection,
                      trigger=trigger["bar"], candle=trigger["bar"],
                      swing={"low": zone["swing"]["price"], "high": zone["swing"]["price"]},
                      trend_closes={"15": [row["close"] for row in m15[-4:]]},
                      pattern=compare_pattern(m15, sign)),
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
    wanted = {"bearish": "SELL", "bullish": "BUY"}.get(primary_bias.get("direction"))

    all_zones = zones(m15, now)
    live_zones = active(all_zones, now, price)
    fresh_sells = [row for row in live_zones if row["direction"] == "SELL" and not row.get("mitigated")]
    fresh_buys = [row for row in live_zones if row["direction"] == "BUY" and not row.get("mitigated")]
    nearest_sell = fresh_sells[0] if fresh_sells else next((row for row in live_zones if row["direction"] == "SELL"), None)
    nearest_buy = fresh_buys[0] if fresh_buys else next((row for row in live_zones if row["direction"] == "BUY"), None)

    # Detect if live price is inside any active zone
    inside_zone = next((z for z in live_zones if z["bottom"] <= price <= z["top"]), None)

    report = dict(
        version=PARAMS["version"], mtf=mtf, now=now, price=price,
        h1=h1_bias, m30=m30_bias, m15=m15_bias, m5=m5_bias,
        primary_bias=primary_bias, context_bias=context_bias,
        tf_bias=dict(M5=m5_bias.get("direction", "neutral"),
                     M15=m15_bias.get("direction", "neutral"),
                     M30=m30_bias.get("direction", "neutral"),
                     H1=h1_bias.get("direction", "neutral")),
        zones=live_zones, nearest_sell=nearest_sell, nearest_buy=nearest_buy,
        inside_zone=inside_zone,
        next_step=f"WAITING FOR {mtf} DIRECTION", reason=None,
        candidate=None, rejection=None, trigger=None, zone=None,
    )
    if not live_zones:
        continuation = _continuation_candidate(snapshot, m15, m5, m1,
                                               [h1_bias, m30_bias, primary_bias], now, price)
        if continuation:
            report["candidate"] = continuation
            report["zone"] = continuation["evidence"]["zone"]
            report["rejection"] = continuation["evidence"]["rejection"]
            report["trigger"] = continuation["evidence"]["trigger"]
            report["next_step"] = "ENTRY READY"
            report["reason"] = continuation["evidence"]["reason"]
            return report
        report["next_step"] = "WATCH BUY" if primary_bias.get("direction") == "bullish" else (
            "WATCH SELL" if primary_bias.get("direction") == "bearish" else f"WAITING FOR {mtf} DIRECTION"
        )
        report["reason"] = "No active M15 liquidity zone."
        return report

    candidate_found = None
    latest_rejection = None
    target_zone = None

    # Check ALL active live_zones (both BUY demand and SELL supply)
    for zone in live_zones:
        rejections = _find_rejections(m5, zone, now)
        if rejections:
            latest_rejection = rejections[-1]
            for rej in reversed(rejections):
                trig = _confirmation(m1, rej, now, zone["direction"])
                if trig:
                    cand = _candidate(zone, rej, trig, snapshot, m15, mtf_aligned=(wanted == zone["direction"]))
                    if cand:
                        candidate_found = cand
                        target_zone = zone
                        report["rejection"] = rej
                        report["trigger"] = trig
                        break
        if candidate_found:
            break

    if not candidate_found:
        continuation = _continuation_candidate(snapshot, m15, m5, m1,
                                               [h1_bias, m30_bias, primary_bias], now, price)
        if continuation:
            candidate_found = continuation
            target_zone = continuation["evidence"]["zone"]
            report["rejection"] = continuation["evidence"]["rejection"]
            report["trigger"] = continuation["evidence"]["trigger"]

    if candidate_found:
        report["zone"] = target_zone
        if now > candidate_found["expiry"]:
            report["candidate"] = None
            report["next_step"] = "EXPIRED"
            report["reason"] = "M1 confirmation window expired. Waiting for fresh rejection."
            return report
        report["candidate"] = candidate_found
        report["next_step"] = "ENTRY READY"
        report["reason"] = candidate_found["evidence"]["reason"]
        return report

    if inside_zone:
        report["zone"] = inside_zone
        report["next_step"] = f"PRICE IN {inside_zone['direction']} ZONE"
        report["reason"] = f"Price is testing M15 {inside_zone['direction']} zone ({inside_zone['bottom']:.2f}–{inside_zone['top']:.2f}). Research watch only — entry requires high-edge confirmation."
        return report

    if latest_rejection and now <= latest_rejection["time"] + PARAMS["entry_window"]:
        report["zone"] = target_zone or live_zones[0]
        report["next_step"] = "WAITING FOR M1 CONFIRMATION"
        report["reason"] = "M5 rejection confirmed. Waiting for M1 confirmation candle."
        return report

    nearest = live_zones[0]
    report["zone"] = nearest
    report["next_step"] = f"WATCHING {nearest['direction']} ZONE"
    report["reason"] = f"Nearest {nearest['direction']} zone at {nearest['bottom']:.2f}–{nearest['top']:.2f}. Waiting for touch."
    return report
