import math
import os
from datetime import datetime
from typing import Protocol

from .config import BROKER_HOURS, NY, SYMBOL, UTC, broker_windows, utc_now
from .strategy import PATTERN_HISTORY

MT5_HISTORY = PATTERN_HISTORY + 10
FRAMES = {"M1": 60, "M5": 300, "M30": 1800, "H1": 3600, "H4": 14400}

REPLAY_START = int(datetime(2026, 11, 16, 15, tzinfo=UTC).timestamp())
REPLAY_PRICES = (3793.62, 3793.52, 3794.42, 3792.90, 3790.10, 3789.70,
                 3787.10, 3786.40, 3783.10, 3784.00, 3783.50, 3785.00)


def bar(ts, opening, high, low, close):
    return dict(time=ts, open=round(opening, 2), high=round(high, 2),
                low=round(low, 2), close=round(close, 2))


def demo_spec(now):
    return dict(symbol=SYMBOL, time=now, max_age=60, demo=True, minimum=0.01, step=0.01,
                maximum=10, contract=100, margin_rate=0.01, account_currency="USD",
                units_per_currency=1, conversion=1, commission=7, slippage=0.10)


def demo_profile(now):
    return dict(symbol=SYMBOL, updated=now, max_age=86400, equity=5000, free_margin=4000,
                currency="USD", units_per_currency=1, risk_pct=1, daily_loss_pct=3,
                exit_policy="split")


def replay_frames(history, now):
    frames = {}
    for name, period in FRAMES.items():
        rows = []
        if period < 900:
            for candle in history[-(250 * period // 900 + 2):]:
                for offset in range(0, 900, period):
                    stamp = candle["time"] + offset
                    if stamp > now:
                        break
                    start = candle["open"] + (candle["close"] - candle["open"]) * offset / 900
                    end = candle["open"] + (candle["close"] - candle["open"]) * (offset + period) / 900
                    rows.append(bar(stamp, start, max(start, end), min(start, end), end))
        else:
            for candle in history:
                stamp = candle["time"] // period * period
                if rows and rows[-1]["time"] == stamp:
                    prior = rows[-1]
                    rows[-1] = bar(stamp, prior["open"], max(prior["high"], candle["high"]),
                                   min(prior["low"], candle["low"]), candle["close"])
                else:
                    rows.append({**candle, "time": stamp})
        frames[name] = rows[-250:]
    return frames


class MarketSource(Protocol):
    def read(self, cursor: float | None, step: int, now: float) -> dict: ...


class Replay:
    def read(self, cursor, step, now):
        week, phase = divmod(step, len(REPLAY_PRICES))
        start = REPLAY_START + week * 7 * 86400
        history = []
        for i in range(-250, 0):
            close = 3794.8 - i * 0.21 + math.sin(i * 0.63) * 2.05 + math.sin(i * 0.17) * 1.25
            if i in (-4, -3, -2):
                close = {-4: 3796.16, -3: 3795.67, -2: 3795.02}[i]
            opening = history[-1]["close"] if history else close + 0.2
            high, low = max(opening, close) + 0.52, min(opening, close) - 0.49
            if i == -7:
                high = 3799.18
            if i in (-9, -8, -6, -5):
                high = min(high, 3798.90)
            if i == -1:
                opening, high, low, close = 3795.02, 3799.12, 3792.92, 3793.42
            history.append(bar(start + i * 900, opening, high, low, close))
        quotes = [round(x, 2) for x in REPLAY_PRICES[:phase + 1]]
        price = quotes[-1]
        ts = start + phase * 180 + 1
        for offset in range(0, phase + 1, 5):
            prices = quotes[offset:offset + 5]
            history.append(bar(start + offset * 180, prices[0], max(prices), min(prices), prices[-1]))
        quote = dict(time=ts, bid=price, ask=round(price + 0.24, 2), available=True)
        return dict(now=ts, bars=history, frames=replay_frames(history, ts), quote=quote, ticks=[quote], spec=demo_spec(ts),
                    closed=False, cursor=ts)


class MT5:
    def __init__(self):
        import MetaTrader5 as mt5

        self.mt5 = mt5
        self.path = os.getenv("MT5_TERMINAL_PATH")
        self.offset = int(os.getenv("MT5_SERVER_OFFSET_MINUTES", "0")) * 60
        self.connected = False
        self.history = {}
        self.loaded_frames = set()
        if not BROKER_HOURS:
            raise ValueError("Set BROKER_HOURS from the exact broker symbol schedule")

    def read(self, cursor, step, now):
        try:
            return self._read(cursor, step, now)
        except RuntimeError:
            self.reset()
            return self._read(cursor, step, utc_now())

    def reset(self):
        self.connected = False
        try:
            self.mt5.shutdown()
        except Exception:
            pass

    def _read(self, cursor, step, now):
        mt5 = self.mt5
        try:
            if not self.connected:
                if not mt5.initialize(*([self.path] if self.path else []), timeout=8000):
                    raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
                if not mt5.symbol_select(SYMBOL, True):
                    raise RuntimeError(f"MT5 symbol unavailable: {SYMBOL}")
                self.connected = True
            terminal, info, tick = mt5.terminal_info(), mt5.symbol_info(SYMBOL), mt5.symbol_info_tick(SYMBOL)
            if not terminal or not terminal.connected or info is None or tick is None:
                raise RuntimeError(f"MT5 connection or quote unavailable: {mt5.last_error()}")
            local = datetime.fromtimestamp(now, NY)
            closed = (
                not any(a <= local.time() < b for a, b in broker_windows(local.date(), BROKER_HOURS))
                or info.trade_mode in (mt5.SYMBOL_TRADE_MODE_DISABLED, mt5.SYMBOL_TRADE_MODE_CLOSEONLY)
            )
            quote = self.quote(tick.time_msc - self.offset * 1000, tick.bid, tick.ask, not closed)
            permission = {mt5.SYMBOL_TRADE_MODE_LONGONLY: "BUY", mt5.SYMBOL_TRADE_MODE_SHORTONLY: "SELL",
                          mt5.SYMBOL_TRADE_MODE_CLOSEONLY: "EXIT", mt5.SYMBOL_TRADE_MODE_DISABLED: "EXIT"}.get(
                              info.trade_mode, "BOTH")
            quote["permission"] = permission
            start = cursor - 900 if cursor is not None else now
            if not self.history:
                initial = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 0, MT5_HISTORY)
                if initial is None:
                    raise RuntimeError(f"MT5 history fetch failed: {mt5.last_error()}")
                for row in initial:
                    stamp = int(row["time"]) - self.offset
                    self.history[stamp] = bar(stamp, row["open"], row["high"], row["low"], row["close"])
            candles = () if cursor is None else mt5.copy_rates_range(SYMBOL, mt5.TIMEFRAME_M15,
                                     datetime.fromtimestamp(start + self.offset, UTC),
                                     datetime.fromtimestamp(now + self.offset, UTC))
            if candles is None:
                raise RuntimeError(f"MT5 candle fetch failed: {mt5.last_error()}")
            ticks = []
            if cursor is not None:
                # Bound each catch-up batch while preserving broker tick order.
                end = min(now, cursor + 300)
                rows = mt5.copy_ticks_range(SYMBOL, datetime.fromtimestamp(cursor + self.offset, UTC),
                                            datetime.fromtimestamp(end + self.offset, UTC), mt5.COPY_TICKS_INFO)
                if rows is None:
                    raise RuntimeError(f"MT5 tick fetch failed: {mt5.last_error()}")
                ticks = [self.quote(row["time_msc"] - self.offset * 1000, row["bid"], row["ask"], True)
                         for row in rows if cursor < row["time_msc"] / 1000 - self.offset <= end
                         and 0 < row["bid"] <= row["ask"]]
                for item in ticks:
                    item["permission"] = permission
                ticks.sort(key=lambda item: item["time"])
            else:
                end = now
            bars = self.history.copy()
            for row in candles:
                stamp = int(row["time"]) - self.offset
                bars[stamp] = bar(stamp, row["open"], row["high"], row["low"], row["close"])
            ordered = sorted(bars)
            self.history = {key: bars[key] for key in ordered[-MT5_HISTORY:]}
            frames = self.chart_frames(cursor, now)
            return dict(now=now, quote=quote, ticks=ticks, cursor=end, closed=closed,
                        bars=[bars[key] for key in ordered], frames=frames, spec=self.spec(info, now))
        except Exception:
            mt5.shutdown()
            self.connected = False
            raise

    def chart_frames(self, cursor, now):
        frames = {}
        mt5 = self.mt5
        for name, period in FRAMES.items():
            timeframe = getattr(mt5, f"TIMEFRAME_{name}")
            if name not in self.loaded_frames or cursor is None:
                rows = mt5.copy_rates_from_pos(SYMBOL, timeframe, 0, 250)
            else:
                rows = mt5.copy_rates_range(SYMBOL, timeframe,
                                            datetime.fromtimestamp(cursor - period + self.offset, UTC),
                                            datetime.fromtimestamp(now + self.offset, UTC))
            if rows is not None and len(rows):
                frames[name] = [
                    bar(int(row["time"]) - self.offset, row["open"], row["high"], row["low"], row["close"])
                    for row in rows
                ]
                self.loaded_frames.add(name)
        return frames

    @staticmethod
    def quote(ms, bid, ask, available):
        return dict(time=float(ms) / 1000, bid=float(bid), ask=float(ask),
                    available=bool(available and 0 < bid <= ask))

    @staticmethod
    def spec(info, now):
        required = ("BROKER_ACCOUNT_CURRENCY", "BROKER_CONVERSION", "BROKER_MARGIN_RATE",
                    "BROKER_COMMISSION", "BROKER_SLIPPAGE", "BROKER_UNITS_PER_CURRENCY", "BROKER_COSTS_AS_OF")
        if any(not os.getenv(key) for key in required):
            return None
        currency, fx, margin, commission, slip, units, as_of = [os.environ[key] for key in required]
        try:
            checked = datetime.fromisoformat(as_of)
            fx, margin, commission, slip, units = map(float, (fx, margin, commission, slip, units))
        except ValueError:
            return None
        maximum_age = int(os.getenv("BROKER_COSTS_MAX_AGE_HOURS", "24")) * 3600
        if (checked.tzinfo is None or not 0 <= now - checked.timestamp() <= maximum_age
                or not (fx > 0 and margin > 0 and commission >= 0 and slip >= 0 and units in (1, 100))
                or not all(math.isfinite(v) for v in (fx, margin, commission, slip))
                or not 0 < info.volume_min <= info.volume_max
                or not (info.volume_step > 0 and info.trade_contract_size > 0)):
            return None
        return dict(symbol=SYMBOL, time=now, max_age=min(60, checked.timestamp() + maximum_age - now),
                    demo=False, minimum=info.volume_min,
                    step=info.volume_step, maximum=info.volume_max, contract=info.trade_contract_size,
                    account_currency=currency.upper(), conversion=fx, margin_rate=margin,
                    commission=commission, slippage=slip, units_per_currency=units)
