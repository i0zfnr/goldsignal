"""Offline broker-tick experiments. No orders, Web Push, or Gemini calls."""

import argparse
import bisect
import csv
import gzip
import json
import math
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean

from .config import BROKER_HOURS, MAX_SPREAD, NY, STALE_SECONDS, SYMBOL, UTC, session, utc_now
from .lifecycle import advance
from .market import MT5, bar
from .replay_report import allocate, normalized_ticks
from .scalp import scalp_candidate
from .store import transaction
from .strategy import account_fit, executable, gate

DELAYS = (5, 15, 30, 60)
FRAMES = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
SOURCES = {
    "ticks": "https://www.mql5.com/en/docs/python_metatrader5/mt5copyticksrange_py",
    "specs": "https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py",
    "broker": "https://valetax.com/trading-instruments/metals/",
    "BLS": "https://www.bls.gov/schedule/news_release/bls.ics",
    "BEA": "https://www.bea.gov/news/schedule/full",
    "Fed": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
}


def ny_window(stamp):
    return session(stamp, broker_hours=BROKER_HOURS, selected={"new_york"})


def write_json(path, value):
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, indent=2, allow_nan=False)


def tick_file(folder, day):
    return folder / f"{day}.ticks.csv.gz"


def load_ticks(path):
    ticks = []
    invalid = duplicates = 0
    previous = None
    with gzip.open(path, "rt", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            stamp, bid, ask = (float(row[key]) for key in ("time", "bid", "ask"))
            if not all(math.isfinite(value) for value in (stamp, bid, ask)) or not 0 < bid <= ask:
                invalid += 1
                continue
            if previous is not None and stamp < previous[0]:
                raise ValueError("Tick file must preserve ascending broker timestamps")
            current = stamp, bid, ask
            duplicates += current == previous
            ticks.append(dict(time=stamp, bid=bid, ask=ask, available=True))
            previous = current
    gaps = [b["time"] - a["time"] for a, b in zip(ticks, ticks[1:])]
    return ticks, dict(count=len(ticks), invalid=invalid, exact_duplicates=duplicates,
                       first=ticks[0]["time"] if ticks else None, last=ticks[-1]["time"] if ticks else None,
                       max_gap_seconds=round(max(gaps, default=0), 3),
                       gaps_over_20s=sum(gap > STALE_SECONDS for gap in gaps))


def export(options):
    start, until = (datetime.fromisoformat(value).replace(tzinfo=NY) for value in (options.start, options.until))
    if not start < until or until.timestamp() > utc_now():
        raise ValueError("Export completed New York dates with start before until")
    folder = options.archive
    folder.mkdir(parents=True, exist_ok=False)
    source = MT5()
    mt5 = source.mt5
    if not mt5.initialize(*([source.path] if source.path else []), timeout=8000):
        raise RuntimeError(f"MT5 unavailable: {mt5.last_error()}")
    try:
        info, account, quote = mt5.symbol_info(SYMBOL), mt5.account_info(), mt5.symbol_info_tick(SYMBOL)
        if not info or not account or not quote or account.currency != "USD" or info.currency_profit != "USD":
            raise ValueError("Research currently supports a USD account and USD profit symbol")
        if abs(utc_now() - (quote.time_msc / 1000 - source.offset)) > 20:
            raise ValueError("Cannot verify current broker clock offset")
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, info.volume_min, quote.ask)
        if margin is None or margin <= 0:
            raise ValueError("Cannot estimate current margin")
        frames = {}
        for frame in FRAMES:
            rows = mt5.copy_rates_range(SYMBOL, getattr(mt5, "TIMEFRAME_" + frame),
                                       datetime.fromtimestamp(start.timestamp() - 7 * 86400 + source.offset, UTC),
                                       datetime.fromtimestamp(until.timestamp() + source.offset, UTC))
            if rows is None or not len(rows):
                raise ValueError(f"No {frame} candle history")
            frames[frame] = [bar(int(row["time"]) - source.offset, row["open"], row["high"],
                                 row["low"], row["close"]) for row in rows]
        write_json(folder / "candles.json", frames)
        with transaction() as store:
            calendar = store.get("state", "market", {}).get("calendar", {})
            signals = store.all("signal")
            opens = store.all("entry_open")
        costs = dict(symbol=SYMBOL, account_currency="USD", units_per_currency=1, conversion=1,
                     minimum=info.volume_min, step=info.volume_step, maximum=info.volume_max,
                     contract=info.trade_contract_size, commission=options.commission, slippage=options.slippage,
                     margin_rate=margin / (quote.ask * info.volume_min * info.trade_contract_size),
                     max_age=1, demo=False)
        sessions = []
        day = start
        while day < until:
            window = ny_window(day.replace(hour=8).timestamp())
            if window["open"]:
                lower, upper = window["opening"], min(window["cutoff"] + 3600, until.timestamp())
                ticks = normalized_ticks(mt5, lower, upper, source.offset)
                destination = tick_file(folder, day.date())
                with gzip.open(destination, "wt", newline="", encoding="utf-8") as file:
                    writer = csv.DictWriter(file, fieldnames=("time", "bid", "ask"))
                    writer.writeheader()
                    writer.writerows({key: row[key] for key in writer.fieldnames} for row in ticks)
                _, coverage = load_ticks(destination)
                sessions.append(dict(day=day.date().isoformat(), opening=lower, cutoff=window["cutoff"],
                                     requested_until=upper, **coverage))
                print(f"Archived {day.date()}: {len(ticks)} ticks", flush=True)
            day += timedelta(days=1)
        # Keep only research fields. Account identifiers, credentials and subscriptions are excluded.
        saved = []
        for signal in signals:
            saved.append({key: signal[key] for key in (
                "id", "direction", "created", "expiry", "entry", "initial_stop", "stop", "targets",
                "reference", "strategy", "max_spread", "hold_seconds", "evidence", "review",
                "filled_at", "fill", "hits", "status", "exits") if key in signal})
        write_json(folder / "manifest.json", dict(
            start=options.start, until=options.until, archived_at=utc_now(), symbol=SYMBOL,
            broker=account.company, account_currency=account.currency,
            account_mode="demo" if account.trade_mode == 0 else "real_or_contest",
            offset_seconds=source.offset, broker_hours=BROKER_HOURS, costs=costs, sessions=sessions,
            calendar=calendar, saved_signals=saved,
            notification_opens=[{key: row.get(key) for key in ("signal", "checked_at", "price", "valid")} for row in opens],
            sources=SOURCES,
            limitations=["Current symbol and margin snapshot, not historical specifications",
                         "Commission and slippage are explicit assumptions",
                         "Calendar is a current cache, not a point-in-time historical archive",
                         "No geopolitical filter, retrospective manual pause, or Gemini replay",
                         "Millisecond order within a timestamp follows the returned broker rows",
                         "Configured fixed broker offset is verified now, not across historical DST changes"],
        ))
    finally:
        mt5.shutdown()


def closed_slice(frames, closes, name, now, count):
    index = bisect.bisect_right(closes[name], now)
    return frames[name][max(0, index - count):index]


def pullback(frames, closes, now):
    """Frozen research hypothesis: M5 pullback, M1 resumption, M15/H1 directional agreement."""
    recent = {name: closed_slice(frames, closes, name, now, 4 if name in ("H1", "M15") else 3)
              for name in FRAMES}
    if any(len(rows) < (4 if name in ("H1", "M15") else 3) for name, rows in recent.items()):
        return None
    if any(any(b["time"] - a["time"] != FRAMES[name] for a, b in zip(rows, rows[1:]))
           for name, rows in recent.items()):
        return None
    m5, trigger = recent["M5"][-1], recent["M1"][-1]
    if not m5["time"] + 300 <= trigger["time"] < m5["time"] + 600:
        return None
    for side, sign in (("BUY", 1), ("SELL", -1)):
        if not all(sign * (recent[frame][-1]["close"] - recent[frame][0]["close"]) > 0
                   for frame in ("M15", "H1")):
            continue
        if sign * (m5["close"] - m5["open"]) >= 0:
            continue
        previous = recent["M1"][-2]
        if sign * (trigger["close"] - trigger["open"]) <= 0 or sign * (
                trigger["close"] - previous["high" if sign == 1 else "low"]) <= 0:
            continue
        extreme = min(m5["low"], trigger["low"]) if sign == 1 else max(m5["high"], trigger["high"])
        stop = round(extreme - sign * max(.10, (m5["high"] - m5["low"]) * .10), 2)
        reference = trigger["close"]
        risk = sign * (reference - stop)
        if risk < .10:
            continue
        window = ny_window(now)
        return dict(id=f"p{m5['time']}{side[0]}", direction=side, strategy="research M5 pullback / M1 resumption",
                    reference=reference, entry=sorted([round(reference - sign * risk * .25, 2), reference]),
                    initial_stop=stop, stop=stop,
                    targets=[round(reference + sign * risk * r, 2) for r in (1, 1.5, 2)],
                    max_spread=min(MAX_SPREAD, risk * .20), hold_seconds=1800, close_time=now,
                    expiry=min(now + 120, window["cutoff"]), created=now)
    return None


def detect(frames, opening, cutoff):
    closes = {name: [row["time"] + FRAMES[name] for row in rows] for name, rows in frames.items()}
    found = {}
    diagnostics = Counter()
    for trigger in frames["M1"]:
        now = trigger["time"] + 60
        if not opening <= now < cutoff:
            continue
        snapshot = dict(now=now, closed=False, spec=None,
                        bars=closed_slice(frames, closes, "M15", now, 1010))
        scalp, reason = scalp_candidate(snapshot, closed_slice(frames, closes, "M5", now, 12),
                                        closed_slice(frames, closes, "M1", now, 12))
        diagnostics[reason] += 1
        for item in (scalp, pullback(frames, closes, now)):
            if item and item["id"] not in found:
                item = {**item, "close_time": now, "created": now, "expiry": min(item["expiry"], cutoff)}
                item.pop("evidence", None)
                item.pop("costs", None)
                found[item["id"]] = item
    return sorted(found.values(), key=lambda row: (row["close_time"], row["id"])), dict(diagnostics)


def news_pause(events, now):
    from .config import NEWS_AFTER, NEWS_BEFORE
    return next((f"Calendar pause: {row['title']}" for row in events if row.get("impact", "high") == "high"
                 and row.get("observed_from", -float("inf")) <= now < row.get("observed_until", float("inf"))
                 and row["time"] - NEWS_BEFORE <= now <= row["time"] + NEWS_AFTER), None)


def execute_legacy(item, ticks, times, delay, events, costs, profile=None):
    start = item["close_time"]
    window = ny_window(start)
    events = [row for row in events if start - 3600 <= row["time"] <= item["expiry"] + 3600]
    first = bisect.bisect_left(times, start)
    end = bisect.bisect_left(times, item["expiry"])
    eligible = [index for index in range(first, end)
                if gate(item, ticks[index], times[index], news_pause(events, times[index]),
                        window=window)[0] == "CONFIRM"]
    if not eligible:
        reasons = Counter(gate(item, ticks[index], times[index], news_pause(events, times[index]),
                              window=window)[1] for index in range(first, end))
        return dict(outcome="blocked", reason=reasons.most_common(1)[0][0] if reasons else "No broker ticks",
                    gate_failures=dict(reasons), alert_time=None)
    index = bisect.bisect_left(times, max(start + delay, times[eligible[0]]))
    base = dict(alert_time=times[eligible[0]], first_executable=times[eligible[0]],
                last_executable=times[eligible[-1]], actionable=times[index] if index < len(times) else None)
    if index >= end:
        return dict(base, outcome="expired", reason="No actionable quote before expiry")
    quote = ticks[index]
    if times[index] - max(start + delay, times[eligible[0]]) > STALE_SECONDS:
        return dict(base, outcome="missed", reason="Quote gap after actionable time")
    decision, reason = gate(item, quote, quote["time"], news_pause(events, quote["time"]),
                            window=window)
    if decision != "CONFIRM":
        return dict(base, outcome="missed", reason=reason)
    trade = {**item, "status": "PENDING", "fill": None, "hits": 0, "exits": [], "result_per_lot": 0}
    lot = 1
    if profile:
        sizing = account_fit(item, {**profile, "updated": times[index]},
                             {**costs, "time": times[index]}, times[index])
        if sizing["decision"] != "FIT":
            return dict(base, outcome="risk_blocked", reason=sizing["reason"])
        lot = sizing["lot"]
        trade["exit_fractions"] = [part / lot for part in allocate(lot, costs["minimum"], costs["step"])]
    advance(trade, quote, quote["time"], True, costs)
    for tick in ticks[index + 1:]:
        advance(trade, tick, tick["time"], False, costs)
        if trade["status"] != "FILLED":
            break
    if trade["status"] == "FILLED":
        return dict(base, outcome="incomplete", reason="Tick archive ends before exit", fill=trade["fill"])
    return dict(base, outcome="filled", reason=trade["status"], fill=trade["fill"],
                exit_time=trade["exits"][-1]["time"], hits=trade["hits"],
                net=round(trade["result_per_lot"] * lot, 2), lot=lot)


def quote_risk(item, quote, costs, profile, now, fixed_lot=None, exit_policy="split"):
    price = executable(item, quote)
    sign = 1 if item["direction"] == "BUY" else -1
    distance = sign * (price - item["initial_stop"])
    budget = profile["equity"] / profile["units_per_currency"] * profile["risk_pct"] / 100
    loss_per_lot = (distance + costs["slippage"]) * costs["contract"] * costs["conversion"] + costs["commission"]
    values = dict(budget=budget, entry=price, minimum_lot=costs["minimum"],
                  minimum_lot_loss=costs["minimum"] * loss_per_lot,
                  three_exit_minimum_lots=3 * costs["minimum"],
                  three_exit_minimum_loss=3 * costs["minimum"] * loss_per_lot,
                  three_exit_risk_fits=3 * costs["minimum"] * loss_per_lot <= budget)
    if distance <= 0:
        return dict(decision="SKIP", reason="Natural stop is invalid at executable price"), values
    if fixed_lot is None:
        result = account_fit({**item, "entry": [price, price]}, {**profile, "updated": now},
                             {**costs, "time": now}, now)
        return result, values
    loss = fixed_lot * loss_per_lot
    margin = quote["ask"] * costs["contract"] * costs["conversion"] * costs["margin_rate"] * fixed_lot
    if loss > budget + 1e-9:
        reason = "Minimum lot exceeds your risk limit"
    elif margin > profile["free_margin"] / profile["units_per_currency"]:
        reason = "Insufficient margin"
    elif fixed_lot < costs["minimum"] or abs(round(fixed_lot / costs["step"]) * costs["step"] - fixed_lot) > 1e-9:
        reason = "Invalid broker entry volume"
    elif exit_policy == "split" and fixed_lot + 1e-9 < 3 * costs["minimum"]:
        reason = "Invalid exit volume: three broker-valid partials require at least 0.03 lot"
    else:
        return dict(decision="FIT", lot=fixed_lot, loss=loss, margin=margin), values
    return dict(decision="SKIP", reason=reason, loss=loss, margin=margin), values


def execute(item, ticks, times, delay, events, costs, profile=None, *, processing=0, review=0,
            fixed_lot=None, exit_policy="split", eligible_indices=None, trace_only=False, detection=0):
    """ENTRY READY: review, eligible quote, local processing, submission, then phone delay.

    Review runs once from confirmation. Local processing restarts after a failed submission
    recheck. The first valid submission is final; action never waits for a later re-entry.
    """
    start = item["close_time"]
    window = ny_window(start)
    events = [row for row in events if start - 3600 <= row["time"] <= item["expiry"] + 3600]
    first, end = bisect.bisect_left(times, start), bisect.bisect_left(times, item["expiry"])

    def check(index):
        quote = ticks[index]
        return gate(item, quote, quote["time"], news_pause(events, quote["time"]), window=window)

    eligible = (eligible_indices if eligible_indices is not None else
                [index for index in range(first, end) if check(index)[0] == "CONFIRM"])
    trace = dict(confirmation=start, detected_at=start + detection, review_start=start + detection,
                 review_finished=start + detection + review,
                 first_eligible=times[eligible[0]] if eligible else None,
                 processing_seconds=processing, post_submission_seconds=delay,
                 submission_attempts=[], submission=None, action_scheduled=None, action_quote=None)
    base = dict(alert_time=None, timing=trace)
    if not eligible:
        failures = Counter(check(index)[1] for index in range(first, end))
        return dict(base, outcome="blocked", reason=failures.most_common(1)[0][0] if failures else "No broker ticks")
    cursor = start + detection + review
    minimum_index = first
    while True:
        position = bisect.bisect_left(eligible, max(minimum_index, bisect.bisect_left(times, cursor)))
        if position == len(eligible):
            return dict(base, outcome="blocked", reason="No valid submission before expiry")
        processing_start = times[eligible[position]]
        ready = processing_start + processing
        index = bisect.bisect_left(times, ready)
        if index >= len(times) or times[index] - ready > STALE_SECONDS:
            return dict(base, outcome="blocked", reason="No fresh submission quote")
        decision, reason = check(index)
        trace["submission_attempts"].append(dict(processing_start=processing_start,
                                                  ready=ready, checked=times[index], result=decision, reason=reason))
        if decision == "CONFIRM":
            break
        cursor = times[index]
        # A different broker row is required before starting another attempt.
        next_position = bisect.bisect_right(eligible, index)
        if next_position == len(eligible):
            return dict(base, outcome="blocked", reason="No valid submission before expiry")
        cursor = times[eligible[next_position]]
        minimum_index = index + 1
    submission = times[index]
    trace["earliest_valid_submission"] = submission
    trace["submission_quote"] = ticks[index]
    submission_risk = None
    if profile:
        submission_risk, volume = quote_risk(item, ticks[index], costs, profile, submission, fixed_lot, exit_policy)
        base["submission_risk"] = submission_risk
        base["volume_audit"] = volume
    action_time = submission + delay
    trace["action_scheduled"] = action_time
    action = bisect.bisect_left(times, action_time)
    if action >= len(times) or times[action] - action_time > STALE_SECONDS:
        action_decision, action_reason = "WAIT", "No fresh action quote"
    else:
        trace["action_quote"] = ticks[action]
        action_decision, action_reason = check(action)
    base["action_gate"] = dict(decision=action_decision, reason=action_reason)
    action_risk = None
    if profile and action_decision == "CONFIRM":
        action_risk, action_volume = quote_risk(item, ticks[action], costs, profile, times[action], fixed_lot, exit_policy)
        base["action_risk"] = action_risk
        base["action_volume_audit"] = action_volume
    if submission_risk and submission_risk["decision"] != "FIT":
        return dict(base, outcome="risk_blocked", reason=submission_risk["reason"], blocked_stage="before_submission")
    trace["submission"] = submission
    base["alert_time"] = submission
    if action_decision != "CONFIRM":
        return dict(base, outcome="missed", reason=action_reason, blocked_stage="action")
    if action_risk and action_risk["decision"] != "FIT":
        return dict(base, outcome="risk_blocked", reason=action_risk["reason"], blocked_stage="action")
    if trace_only:
        return dict(base, outcome="ready", reason="Action quote passed")
    lot = action_risk["lot"] if action_risk else 1
    if exit_policy == "single":
        sign = 1 if item["direction"] == "BUY" else -1
        fill = executable(item, ticks[action])
        target = item["targets"][0]
        for tick in ticks[action + 1:]:
            price = executable(item, tick, exit_side=True)
            stopped = sign * (price - item["initial_stop"]) <= 0
            hit = sign * (price - target) >= 0
            timed_out = tick["time"] >= times[action] + item.get("hold_seconds", 1800)
            if stopped or hit or timed_out:
                net = ((sign * (price - fill) - costs["slippage"]) * costs["contract"] * costs["conversion"]
                       - costs["commission"]) * lot
                return dict(base, outcome="filled", reason="STOPPED" if stopped else "COMPLETED" if hit else "TIMED_OUT",
                            fill=fill, exit_time=tick["time"], hits=int(hit and not stopped), net=round(net, 2), lot=lot)
        return dict(base, outcome="incomplete", reason="Tick archive ends before exit", fill=fill)
    trade = {**item, "status": "PENDING", "fill": None, "hits": 0, "exits": [], "result_per_lot": 0}
    if profile:
        trade["exit_fractions"] = [part / lot for part in allocate(lot, costs["minimum"], costs["step"])]
    advance(trade, ticks[action], times[action], True, costs)
    for tick in ticks[action + 1:]:
        advance(trade, tick, tick["time"], False, costs)
        if trade["status"] != "FILLED":
            break
    if trade["status"] == "FILLED":
        return dict(base, outcome="incomplete", reason="Tick archive ends before exit", fill=trade["fill"])
    return dict(base, outcome="filled", reason=trade["status"], fill=trade["fill"],
                exit_time=trade["exits"][-1]["time"], hits=trade["hits"],
                net=round(trade["result_per_lot"] * lot, 2), lot=lot)


def publication_check(signal, ticks, delay):
    ready = signal["created"] + delay
    quote = next((tick for tick in ticks if tick["time"] >= ready), None)
    if quote is None or quote["time"] - ready > STALE_SECONDS:
        return dict(inside=False, reason="No fresh quote at recorded publication plus delay")
    decision, reason = gate(signal, quote, quote["time"])
    return dict(inside=decision == "CONFIRM", reason=reason, quote=quote,
                scheduled_at=ready, checked_at=quote["time"])


def summary(rows, sessions):
    closed = sorted((row for row in rows if row["outcome"] == "filled"), key=lambda row: row["exit_time"])
    n = len(closed)
    wins = sum(row["net"] > 0 for row in closed)
    interval = None
    if n:
        p, z = wins / n, 1.96
        center = (p + z*z/(2*n)) / (1 + z*z/n)
        half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
        interval = [round(100*(center-half), 2), round(100*(center+half), 2)]
    equity = peak = drawdown = 0
    for row in closed:
        equity += row["net"]
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    alerts = sum(row.get("alert_time") is not None and
                 (row["outcome"] != "risk_blocked" or row.get("blocked_stage") == "action") for row in rows)
    fills = sum(row["outcome"] in ("filled", "incomplete") for row in rows)
    return dict(candidates=len(rows), alerts=alerts, completed=n, wins=wins,
                executable_entries=fills, executable_per_session=round(fills / sessions, 3) if sessions else None,
                executable_percent=round(100*fills/alerts, 2) if alerts else None,
                win_rate=round(100*wins/n, 2) if n else None, win_rate_95pct_wilson=interval,
                mean_net=round(mean(row["net"] for row in closed), 2) if n else None,
                total_net=round(equity, 2), closed_trade_drawdown=round(drawdown, 2),
                outcomes=dict(Counter(row["outcome"] for row in rows)),
                reasons=dict(Counter(row["reason"] for row in rows)),
                confidence="Insufficient evidence for an 80% probability claim")


def run_legacy(options):
    manifest = json.loads((options.archive / "manifest.json").read_text(encoding="utf-8"))
    frames = json.loads((options.archive / "candles.json").read_text(encoding="utf-8"))
    if manifest["symbol"] != SYMBOL or manifest["broker_hours"] != BROKER_HOURS:
        raise ValueError("Run with the archived symbol and broker hours configuration")
    if not manifest["start"] < options.split < manifest["until"]:
        raise ValueError("Split must fall inside the archived date interval")
    costs = {**manifest["costs"], "slippage": manifest["costs"]["slippage"] * options.cost_multiplier,
             "commission": manifest["costs"]["commission"] * options.cost_multiplier}
    records, audits, diagnostics = {}, {}, {}
    counts = Counter()
    for covered in manifest["sessions"]:
        day = covered["day"]
        period = "development" if day < options.split else "evaluation"
        ticks, audit = load_ticks(tick_file(options.archive, day))
        audits[day] = audit
        if not ticks:
            continue
        counts[period] += 1
        times = [row["time"] for row in ticks]
        candidates, diagnostics[day] = detect(frames, covered["opening"], covered["cutoff"])
        events = manifest["calendar"].get("events", [])
        executions = {}
        for variant, families in (("A", False), ("B", False), ("C", True)):
            for delay in DELAYS:
                for account in (None, 100, 1000):
                    key = f"{period}/{variant}/{delay}s/" + ("strategy_per_lot" if account is None else f"USD{account}_1pct")
                    rows = records.setdefault(key, [])
                    published = []
                    exposure_until = 0
                    realized = 0
                    profile = dict(symbol=SYMBOL, currency="USD", units_per_currency=1, equity=account,
                                   free_margin=account, risk_pct=1, daily_loss_pct=3, exit_policy="split", max_age=1)
                    eligible_candidates = []
                    for item in candidates:
                        if item["id"].startswith("p") and not families:
                            continue
                        cache_key = item["id"], delay, account
                        if cache_key not in executions:
                            executions[cache_key] = execute_legacy(item, ticks, times, delay, events, costs,
                                                            profile if account is not None else None)
                        eligible_candidates.append((item, executions[cache_key].copy()))
                    eligible_candidates.sort(key=lambda pair: (
                        pair[1].get("alert_time") if pair[1].get("alert_time") is not None else float("inf"),
                        pair[0]["id"]))
                    for item, result in eligible_candidates:
                        alert = result.get("alert_time")
                        if alert is not None:
                            published = [stamp for stamp in published if stamp > alert - 3600]
                            if account is not None and realized <= -account * .03:
                                result = dict(outcome="risk_blocked", reason="Tracked daily loss limit reached",
                                              alert_time=alert)
                            elif len(published) >= 2 or alert < exposure_until:
                                result = dict(outcome="suppressed", reason="Two per hour cap or existing exposure",
                                              alert_time=None)
                            elif result["outcome"] != "risk_blocked":
                                published.append(alert)
                                exposure_until = result.get("exit_time", item["expiry"] + 1800
                                                            if result["outcome"] == "incomplete" else item["expiry"])
                                if result["outcome"] == "filled":
                                    realized += result["net"]
                        rows.append(dict(id=item["id"], day=day, strategy=item["strategy"], **result))
        print(f"Replayed {day}: {len(candidates)} candidates", flush=True)
    reproduction = []
    for signal in manifest.get("saved_signals", []):
        day = datetime.fromtimestamp(signal["created"], NY).date().isoformat()
        path = tick_file(options.archive, day)
        if not path.exists():
            reproduction.append(dict(id=signal["id"], missing="Session tick file unavailable"))
            continue
        ticks, _ = load_ticks(path)
        times = [tick["time"] for tick in ticks]
        item = {**signal, "close_time": signal["created"]}
        result = execute_legacy(item, ticks, times, 30, [], manifest["costs"])
        evidence = signal.get("evidence", {})
        trigger = evidence.get("trigger")
        detection = trigger["time"] + 60 if trigger else signal["created"]
        indices = [index for index in range(bisect.bisect_left(times, detection),
                                           bisect.bisect_left(times, signal["expiry"]))
                   if gate(signal, ticks[index], times[index])[0] == "CONFIRM"]
        first_ceased = None
        if indices:
            first_ceased = next((times[index] for index in range(indices[0] + 1,
                                bisect.bisect_left(times, signal["expiry"]))
                                 if gate(signal, ticks[index], times[index])[0] != "CONFIRM"), None)
        reproduction.append(dict(id=signal["id"], published=signal["created"], confirmed=detection,
                                  detection_to_publication_seconds=round(signal["created"] - detection, 3),
                                  first_executable_from_confirmation=times[indices[0]] if indices else None,
                                  first_executable_interval_ceased=first_ceased,
                                  last_executable_before_expiry=times[indices[-1]] if indices else None,
                                  publication_plus_30=publication_check(signal, ticks, 30), **result))
    report = dict(
        archived=manifest, split=options.split, covered_sessions=dict(counts), coverage=audits,
        decisions="A at 30s, B at 5s, C at 5s are the assumed main comparison. All delay sweeps are paired.",
        latency="Total candidate-confirmation to action is a scenario. Actual opens and stage timing remain unmeasured.",
        dedup="One active/pending opportunity, all directions, with two alerts per rolling hour per session.",
        risk="Fixed USD100 and USD1000 profiles at 1%, broker-valid thirds. Strategy-per-lot is diagnostic only.",
        effective_costs=costs,
        summaries={key: summary(rows, counts[key.split('/')[0]]) for key, rows in records.items()},
        original_four_30s=reproduction, setup_diagnostics=diagnostics, records=records,
        paid_api_calls=0,
    )
    write_json(options.output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("export")
    collect.add_argument("--start", required=True)
    collect.add_argument("--until", required=True)
    collect.add_argument("--commission", type=float, required=True)
    collect.add_argument("--slippage", type=float, required=True)
    collect.add_argument("--archive", type=Path, required=True)
    experiment = commands.add_parser("run")
    experiment.add_argument("--archive", type=Path, required=True)
    experiment.add_argument("--split", required=True)
    experiment.add_argument("--output", type=Path, required=True)
    experiment.add_argument("--cost-multiplier", type=float, default=1)
    experiment.add_argument("--processing", type=float, nargs="+", default=[0, 2, 5, 15, 30])
    experiment.add_argument("--review", type=float, default=0)
    experiment.add_argument("--post-delays", type=float, nargs="+", default=[5, 15, 30, 60])
    experiment.add_argument("--commissions", type=float, nargs="+", default=[0, 7, 14])
    experiment.add_argument("--previous", type=Path, default=Path(".research/scalp-20261119-final.json"))
    options = parser.parse_args()
    if options.command == "export":
        if any(not math.isfinite(value) or value < 0 for value in (options.commission, options.slippage)):
            parser.error("Costs must be finite and nonnegative")
        export(options)
    else:
        if not math.isfinite(options.cost_multiplier) or options.cost_multiplier < 1:
            parser.error("Cost multiplier must be finite and at least 1")
        if any(not math.isfinite(value) or value < 0 for value in
               [options.review, *options.processing, *options.post_delays, *options.commissions]):
            parser.error("Timing and commission scenarios must be finite and nonnegative")
        from .scalp_timing_replay import run
        run(options)


if __name__ == "__main__":
    main()
