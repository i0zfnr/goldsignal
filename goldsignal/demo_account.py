"""Opt-in paper account. Never places an MT5 order or changes shared signal policy."""

import hashlib
import os
from pathlib import Path
from threading import Lock

from .config import DB, MODE, REVIEW, SYMBOL, STALE_SECONDS, utc_now
from .news import manual_pause, restriction
from .strategy import executable, gate

terminal_lock = Lock()


def enabled():
    return os.getenv("GOLDSIGNAL_DEMO_ACCOUNT") == "1"


def assert_isolated():
    if not enabled():
        return
    if MODE != "mt5" or REVIEW != "rules" or not DB.startswith("sqlite:///"):
        raise RuntimeError("Demo account requires MT5, rules-only review and isolated SQLite")
    path = Path(DB.removeprefix("sqlite:///")).resolve()
    allowed = (Path(__file__).resolve().parent.parent / ".research" / "demo-phone").resolve()
    if allowed not in path.parents:
        raise RuntimeError("Demo account database must stay under .research/demo-phone")


def key(owner, signal):
    return hashlib.sha256(f"{owner}:{signal}".encode()).hexdigest()


def terminal_snapshot():
    from .market import MT5
    assert_isolated()
    source = MT5()
    mt5 = source.mt5
    with terminal_lock:
        if not mt5.initialize(*([source.path] if source.path else []), timeout=8000):
            return None, None, "MT5 is unavailable"
        try:
            account, info, tick = mt5.account_info(), mt5.symbol_info(SYMBOL), mt5.symbol_info_tick(SYMBOL)
            if not account or account.trade_mode != 0 or account.currency != "USD":
                return None, None, "Configured terminal must be a USD demo account"
            pinned = os.getenv("DEMO_TERMINAL_FINGERPRINT")
            if pinned and hashlib.sha256(f"{account.login}:{account.server}".encode()).hexdigest() != pinned:
                return None, None, "Configured broker account changed; refresh the demo audit"
            if not info or not tick or info.currency_profit != "USD" or info.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
                return None, None, "Broker symbol is unavailable or not fully tradable"
            now = utc_now()
            quote = dict(time=tick.time_msc / 1000 - source.offset, bid=tick.bid, ask=tick.ask, available=True)
            import math
            commission, slippage = float(os.environ["BROKER_COMMISSION"]), float(os.environ["BROKER_SLIPPAGE"])
            if not all(math.isfinite(value) and value >= 0 for value in (commission, slippage)):
                return quote, None, "Explicit finite cost assumptions required"
            spec = dict(symbol=SYMBOL, time=now, max_age=20, minimum=info.volume_min, step=info.volume_step,
                        maximum=info.volume_max, contract=info.trade_contract_size, account_currency="USD",
                        conversion=1, units_per_currency=1, commission=commission, slippage=slippage)
            if not (0 < info.volume_min <= .01 <= info.volume_max and info.volume_step > 0 and info.trade_contract_size > 0):
                return quote, None, "Broker no longer supports the demo 0.01-lot entry"
            margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, .01, tick.ask)
            sell_margin = mt5.order_calc_margin(mt5.ORDER_TYPE_SELL, SYMBOL, .01, tick.bid)
            if margin is None or margin <= 0 or sell_margin is None or sell_margin <= 0:
                return quote, None, "Fresh broker specifications and explicit costs are required"
            spec["margin_rate"] = margin / (tick.ask * .01 * spec["contract"])
            spec["minimum_margins"] = {"BUY": margin, "SELL": sell_margin}
            return quote, spec, None
        finally:
            mt5.shutdown()


def check(store, signal, owner, now, quote=None, spec=None):
    from .scalp_research import ny_window, quote_risk
    result = dict(valid=False, account="DEMO USD100", lot=.01, exit_policy="single", checked_at=now,
                  quote=None, price=None, ratios=None, side="Ask" if signal and signal["direction"] == "BUY" else "Bid")
    if not signal:
        return {**result, "reason": "Signal not found"}
    if signal.get("strategy") != "M5 setup / M1 entry":
        return {**result, "reason": "This demo measures the frozen M5/M1 baseline only"}
    if signal["status"] not in ("PENDING", "FILLED") or signal.get("hits"):
        return {**result, "reason": "Signal is already past its entry phase"}
    if manual_pause(store, now):
        return {**result, "reason": "New entries paused by admin"}
    if store.get("demo_open", key(owner, signal["id"])):
        return {**result, "reason": "This demo opportunity was already checked at its first open"}
    if quote is None or spec is None:
        quote, spec, error = terminal_snapshot()
        if error:
            return {**result, "reason": error}
        now = utc_now()
        result["checked_at"] = now
    state = store.get("state", "market", {})
    pause = restriction(state.get("calendar", {}), now, False)
    decision, reason = gate(signal, quote, now, pause, window=ny_window(now))
    result.update(quote=quote, price=executable(signal, quote), side="Ask" if signal["direction"] == "BUY" else "Bid")
    if decision != "CONFIRM":
        return {**result, "reason": reason}
    if not spec or spec.get("symbol") != SYMBOL or spec.get("account_currency") != "USD" or not 0 <= now - spec["time"] <= spec["max_age"]:
        return {**result, "reason": "Fresh matching USD broker specifications required"}
    if .01 > spec["maximum"]:
        return {**result, "reason": "0.01 lot exceeds broker maximum volume"}
    trades = [trade for trade in store.all("demo_trade") if trade["owner"] == owner]
    if any(trade["status"] == "FILLED" for trade in trades):
        return {**result, "reason": "Existing demo exposure"}
    equity = round(100 + sum(trade.get("net", 0) for trade in trades), 2)
    profile = dict(equity=equity, free_margin=equity, units_per_currency=1, risk_pct=1)
    if spec.get("minimum_margins"):
        spec = {**spec, "margin_rate": spec["minimum_margins"][signal["direction"]] / (quote["ask"] * .01 * spec["contract"])}
    fit, volume = quote_risk(signal, quote, spec, profile, now, .01, "single")
    result.update(equity=equity, risk=fit, volume=volume, costs=dict(commission=spec["commission"],
                  slippage=spec["slippage"], assumption="Round-trip commission USD/lot and adverse price slippage"),
                  spec={name: spec[name] for name in ("minimum", "step", "maximum", "contract", "time")})
    if fit["decision"] != "FIT":
        return {**result, "reason": fit["reason"]}
    ready = [row for row in store.all("demo_ready") if row["owner"] == owner and row["time"] > now - 3600]
    if signal["id"] not in {row["signal"] for row in ready} and len({row["signal"] for row in ready}) >= 2:
        return {**result, "reason": "Two account-specific alerts per rolling hour reached"}
    from .config import NY
    from datetime import datetime
    today = datetime.fromtimestamp(now, NY).date()
    daily = sum(trade.get("net", 0) for trade in trades if trade.get("closed_at") and
                datetime.fromtimestamp(trade["closed_at"], NY).date() == today)
    start_equity = 100 + sum(trade.get("net", 0) for trade in trades if trade.get("closed_at") and
                            datetime.fromtimestamp(trade["closed_at"], NY).date() < today)
    if daily <= -.03 * start_equity:
        return {**result, "reason": "Demo daily loss limit reached"}
    return {**result, "valid": True, "reason": f"DEMO USD{equity:.2f}: 0.01 lot fits 1% risk; one full exit at TP1"}


def open_entry(store, signal, owner, recipient, now, result):
    if not result["valid"]:
        return
    store.put("demo_trade", key(owner, signal["id"]), dict(owner=owner, recipient=recipient, signal=signal["id"],
              status="FILLED", direction=signal["direction"], fill=result["price"], filled_at=now,
              stop=signal["initial_stop"], target=signal["targets"][0], lot=.01, costs=result["costs"],
              contract=result["spec"]["contract"], hold_seconds=signal.get("hold_seconds", 1800)))


def track(store, snapshot):
    for identity, trade in store.items("demo_trade"):
        if trade["status"] != "FILLED":
            continue
        sign = 1 if trade["direction"] == "BUY" else -1
        for tick in snapshot.get("ticks", []):
            if tick["time"] <= trade["filled_at"] or not tick.get("available"):
                continue
            price = tick["bid" if sign == 1 else "ask"]
            stop = sign * (price - trade["stop"]) <= 0
            target = sign * (price - trade["target"]) >= 0
            timeout = tick["time"] >= trade["filled_at"] + trade["hold_seconds"]
            if stop or target or timeout:
                trade.update(status="SL" if stop else "TP1" if target else "TIMEOUT", closed_at=tick["time"],
                             net=round(((sign * (price - trade["fill"]) - trade["costs"]["slippage"]) * trade["contract"]
                                        - trade["costs"]["commission"]) * .01, 2))
                store.put("demo_trade", identity, trade)
                alert_id = f"demo-exit:{identity}"
                store.put("alert", alert_id, dict(id=alert_id, profile=trade["recipient"], signal=trade["signal"],
                          kind="DEMO_EXIT", time=tick["time"], valid_until=tick["time"] + 3600,
                          title=f"DEMO single exit · {trade['status']}", body=f"Paper result USD{trade['net']:.2f}, 0.01 lot",
                          url="/#history", delivery="queued", attempts=0))
                break
