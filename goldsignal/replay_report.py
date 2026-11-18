import argparse
import json
import os
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .config import ENTRY_TTL, HOLD_TTL, NEWS_AFTER, NEWS_BEFORE, NY, STALE_SECONDS, SYMBOL, UTC, session, utc_now
from .lifecycle import advance
from .market import bar
from .store import transaction
from .strategy import PATTERN_HISTORY, account_fit, executable, gate, levels, setup


def ny_window(ts):
    return session(ts, selected={"new_york"})


def candidates(bars, start, end):
    scanned = 0
    found = []
    for index, candle in enumerate(bars):
        closed = candle["time"] + 900
        if not start <= closed < end:
            continue
        window = ny_window(closed)
        if not window["open"]:
            continue
        scanned += 1
        evidence = setup(bars[max(0, index - PATTERN_HISTORY - 10):index + 1], closed)
        if evidence:
            found.append({
                "id": f"{candle['time']}:{evidence['direction']}", "direction": evidence["direction"],
                **levels(evidence["direction"], candle["close"]),
                "close_time": closed, "expiry": min(closed + ENTRY_TTL, window["cutoff"]),
            })
    return scanned, found


def allocate(lot, minimum, step):
    total, base, increment = (Decimal(str(value)) for value in (lot, minimum, step))
    extras = (total - 3 * base) / increment
    if extras < 0 or extras != extras.to_integral_value():
        raise ValueError("Volume cannot be split across three broker-valid exits")
    count = int(extras)
    return [float(base + increment * (count // 3 + (i < count % 3))) for i in range(3)]


def replay(candidate, ticks, delay, events, profile, costs, history_end):
    def pause(ts):
        return next((row["title"] for row in events
                     if row["time"] - NEWS_BEFORE <= ts <= row["time"] + NEWS_AFTER), None)

    open_time = candidate["close_time"]
    sizing = account_fit(candidate, {**profile, "updated": open_time}, {**costs, "time": open_time}, open_time)

    def disposition(outcome, reason, **details):
        return {**candidate, "outcome": outcome, "reason": reason, "sizing": sizing, **details}

    window = ny_window(open_time)
    entry_ticks = [tick for tick in ticks if open_time <= tick["time"] < candidate["expiry"]]
    if not entry_ticks:
        return disposition("blocked", "No broker ticks cover the entry window")
    reasons = Counter()
    for quote in entry_ticks:
        decision, reason = gate(candidate, quote, quote["time"], pause(quote["time"]), window=window)
        if decision == "CONFIRM":
            break
        reasons[reason] += 1
    else:
        expired = set(reasons) == {"Executable quote is outside the entry zone"}
        return disposition("expired" if expired else "blocked",
                           "Entry zone never reached" if expired else "No tick passed all entry checks",
                           gate_failures=dict(reasons))

    alert_time = quote["time"]
    ready = alert_time + delay
    if ready >= candidate["expiry"]:
        return disposition("expired", "Entry expired before the viewer could react", alert_time=alert_time)
    opened = next((tick for tick in entry_ticks if tick["time"] >= ready), None)
    if opened is None:
        return disposition("expired", "No broker quote after the reaction delay and before expiry", alert_time=alert_time)
    price = executable(candidate, opened)
    context = dict(alert_time=alert_time, viewer_quote=opened, executable_price=price)
    if opened["time"] - ready > STALE_SECONDS:
        return disposition("missed_after_delay", "Quote gap after the viewer reaction delay", **context)
    decision, reason = gate(candidate, opened, opened["time"], pause(opened["time"]), window=window)
    if decision != "CONFIRM":
        return disposition("missed_after_delay", reason, **context)

    trade = {**candidate, "status": "PENDING", "fill": None, "hits": 0, "exits": [], "result_per_lot": 0}
    if sizing["decision"] == "FIT":
        portions = allocate(sizing["lot"], costs["minimum"], costs["step"])
        trade["exit_fractions"] = [lot / sizing["lot"] for lot in portions]
        sizing["exit_lots"] = portions
    advance(trade, opened, opened["time"], True, costs)
    # Preserve broker row order when multiple quotes have the same millisecond timestamp.
    filled_index = next(index for index, tick in enumerate(ticks) if tick is opened)
    for tick in ticks[filled_index + 1:]:
        if tick["time"] >= history_end:
            break
        advance(trade, tick, tick["time"], False, costs)
        if trade["status"] != "FILLED":
            break
    finished = trade["status"] != "FILLED"
    return disposition("filled" if finished else "filled_incomplete", trade["status"], **context,
                       exits=trade["exits"],
                       net_per_lot=trade["result_per_lot"] if finished else None,
                       net_account=round(trade["result_per_lot"] * sizing["lot"], 2)
                       if finished and sizing["decision"] == "FIT" else None)


def normalized_ticks(mt5, start, end, offset):
    result = []
    for lower in range(int(start), int(end) + 1, 1800):
        upper = min(lower + 1800, end)
        rows = mt5.copy_ticks_range(SYMBOL, int(lower + offset), int(upper + offset), mt5.COPY_TICKS_INFO)
        if rows is None:
            raise RuntimeError(f"MT5 tick history unavailable: {mt5.last_error()}")
        for row in rows:
            ts = float(row["time_msc"]) / 1000 - offset
            if lower <= ts < upper and ts >= start and 0 < row["bid"] <= row["ask"]:
                result.append({"time": ts, "bid": float(row["bid"]), "ask": float(row["ask"]), "available": True})
    return result


def run(options):
    import MetaTrader5 as mt5

    start, end = (datetime.fromisoformat(value).replace(tzinfo=NY).timestamp()
                  for value in (options.start, options.until))
    if not start < end <= utc_now():
        raise ValueError("Use a completed interval with start before until")
    path = os.getenv("MT5_TERMINAL_PATH")
    offset = int(os.getenv("MT5_SERVER_OFFSET_MINUTES", "0")) * 60
    if not mt5.initialize(*([path] if path else []), timeout=8000):
        raise RuntimeError(f"MT5 connection failed: {mt5.last_error()}")
    try:
        info, account, quote = mt5.symbol_info(SYMBOL), mt5.account_info(), mt5.symbol_info_tick(SYMBOL)
        if not info or not account or not quote or account.currency != "USD" or info.currency_profit != "USD":
            raise ValueError("This baseline report expects a connected USD account and USD profit symbol")
        if abs(utc_now() - (quote.time_msc / 1000 - offset)) > 20:
            raise ValueError("Cannot validate the configured broker clock offset against the current quote")
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_SELL, SYMBOL, info.volume_min, quote.bid)
        gross = mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, SYMBOL, info.volume_min, quote.bid, quote.bid + 6)
        if not margin or gross is None or abs(gross + 6 * info.volume_min * info.trade_contract_size) > 0.01:
            raise ValueError("Broker margin or linear USD profit assumptions could not be verified")
        rows = mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15,
                                    datetime.fromtimestamp(start - 21 * 86400 + offset, UTC),
                                    datetime.fromtimestamp(end + offset, UTC))
        if rows is None or not len(rows):
            raise RuntimeError(f"MT5 M15 history unavailable: {mt5.last_error()}")
        bars = [bar(int(row["time"]) - offset, row["open"], row["high"], row["low"], row["close"]) for row in rows]
        scanned, found = candidates(bars, start, end)
        costs = dict(symbol=SYMBOL, account_currency="USD", units_per_currency=1, conversion=1,
                     minimum=info.volume_min, step=info.volume_step, maximum=info.volume_max,
                     contract=info.trade_contract_size, commission=options.commission, slippage=options.slippage,
                     margin_rate=margin / (quote.bid * info.volume_min * info.trade_contract_size), max_age=1, demo=False)
        profile = dict(symbol=SYMBOL, currency="USD", units_per_currency=1, equity=options.equity,
                       free_margin=options.free_margin, risk_pct=options.risk_pct, daily_loss_pct=100,
                       exit_policy="split", max_age=1)
        with transaction() as data:
            calendar = data.get("state", "market", {}).get("calendar", {})
        events = calendar.get("events", [])
        results = []
        for item in found:
            ticks = normalized_ticks(mt5, item["close_time"], min(end, item["expiry"] + HOLD_TTL + 3600), offset)
            result = replay(item, ticks, options.delay, events, profile, costs, end)
            results.append({**result, "tick_count": len(ticks),
                            "first_tick": ticks[0]["time"] if ticks else None,
                            "last_tick": ticks[-1]["time"] if ticks else None,
                            "max_tick_gap_seconds": round(max((b["time"] - a["time"]
                                                           for a, b in zip(ticks, ticks[1:])), default=0), 3)})
        filled = [row for row in results if row["outcome"] in ("filled", "filled_incomplete")]
        complete = [row for row in filled if row["net_per_lot"] is not None]
        return dict(
            source="Valetax MT5", symbol=SYMBOL, session="New York only", start=options.start, until=options.until,
            utc_offset_seconds=offset, delay_seconds=options.delay, bars_scanned=scanned,
            first_bar=bars[0]["time"], last_bar=bars[-1]["time"],
            calendar_sources=sorted(calendar.get("sources", {})),
            calendar_events_in_interval=[row for row in events if start <= row["time"] < end],
            costs=costs, profile=profile, outcomes=dict(Counter(row["outcome"] for row in results)),
            setups_with_valid_three_part_size=sum(row["sizing"]["decision"] == "FIT" for row in results),
            sizing_denominator=len(results),
            net_per_lot=round(sum(row["net_per_lot"] for row in complete), 2) if complete else None,
            net_account=round(sum(row["net_account"] for row in complete if row["net_account"] is not None), 2),
            candidates=results,
        )
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay the existing M15 rules on Valetax bid/ask ticks, without AI.")
    parser.add_argument("--start", required=True, help="First date, inclusive, in New York")
    parser.add_argument("--until", required=True, help="End date, exclusive, in New York")
    parser.add_argument("--delay", type=float, required=True, help="Combined delivery and manual reaction seconds")
    parser.add_argument("--commission", type=float, required=True, help="Estimated USD round-trip commission per lot")
    parser.add_argument("--slippage", type=float, required=True, help="Adverse round-trip slippage in price units")
    parser.add_argument("--equity", type=float, default=100)
    parser.add_argument("--free-margin", type=float, default=100)
    parser.add_argument("--risk-pct", type=float, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if min(args.delay, args.commission, args.slippage, args.free_margin) < 0 or args.equity <= 0 or not 0 < args.risk_pct <= 100:
        parser.error("Invalid sizing or cost assumptions")
    report = run(args)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, allow_nan=False)
    print(f"Scanned {report['bars_scanned']} New York closes. Outcomes: {report['outcomes']}.")
