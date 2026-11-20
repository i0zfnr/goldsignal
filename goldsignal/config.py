import json
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
MY = ZoneInfo("Asia/Kuala_Lumpur")
MODE = os.getenv("MARKET_SOURCE", "demo")
SYMBOL = os.getenv("BROKER_SYMBOL", "XAUUSD")
DB = os.getenv("DATABASE_URL", "sqlite:///goldsignal.sqlite3")
ENTRY_START = time.fromisoformat(os.getenv("ENTRY_START", "08:00"))
ENTRY_END = time.fromisoformat(os.getenv("ENTRY_END", "17:00"))
ENTRY_SESSIONS = frozenset(os.getenv("ENTRY_SESSIONS", "sydney,tokyo,london,new_york").split(","))
MARKET_SESSIONS = (
    ("sydney", "Sydney", ZoneInfo("Australia/Sydney"), time(8), time(17)),
    ("tokyo", "Tokyo", ZoneInfo("Asia/Tokyo"), time(9), time(18)),
    ("london", "London", ZoneInfo("Europe/London"), time(8), time(17)),
    ("new_york", "New York", NY, ENTRY_START, ENTRY_END),
)
BROKER_HOURS = os.getenv("BROKER_HOURS", "")
BROKER_HOLIDAYS = set(filter(None, os.getenv("BROKER_CLOSED_DATES", "").split(",")))
BROKER_DATE_HOURS = json.loads(os.getenv("BROKER_DATE_HOURS") or "{}")
FRIDAY_CLOSE = time.fromisoformat(os.getenv("BROKER_FRIDAY_CLOSE", "17:00"))
SUNDAY_OPEN = time.fromisoformat(os.getenv("BROKER_SUNDAY_OPEN", "18:00"))
MAX_SPREAD = float(os.getenv("MAX_SPREAD", "0.5"))
STALE_SECONDS = int(os.getenv("QUOTE_MAX_AGE", "20"))
QUOTE_FUTURE_TOLERANCE = int(os.getenv("QUOTE_FUTURE_TOLERANCE_SECONDS", "10"))
ENTRY_TTL = int(os.getenv("ENTRY_TTL_MIN", "30")) * 60
HOLD_TTL = int(os.getenv("HOLD_TTL_MIN", "180")) * 60
NEWS_BEFORE = int(os.getenv("NEWS_BEFORE_MIN", "20")) * 60
NEWS_AFTER = int(os.getenv("NEWS_AFTER_MIN", "15")) * 60
CALENDAR_MAX_AGE = int(os.getenv("CALENDAR_MAX_AGE_HOURS", "6")) * 3600
SWING = int(os.getenv("SWING_BARS", "2"))
ZONE_WIDTH = float(os.getenv("ZONE_WIDTH", "0.8"))
TREND = int(os.getenv("TREND_BARS", "4"))
REVIEW = os.getenv("SIGNAL_REVIEW_MODE", "rules")
STRATEGY_B_VERSION = os.getenv("STRATEGY_B_VERSION", "katana_v1")
STRATEGY_B_MTF = os.getenv("STRATEGY_B_MTF", "M15")


def utc_now():
    return datetime.now(UTC).timestamp()


def broker_windows(day, hours):
    if not hours:
        return [(time.min, time.max)]
    override = BROKER_DATE_HOURS.get(day.isoformat())
    if override is None and (day.weekday() == 5 or day.isoformat() in BROKER_HOLIDAYS):
        return []
    times = hours if override is None else override
    windows = []
    for pair in filter(None, times.split(",")):
        start, end = (time.max if t == "24:00" else time.fromisoformat(t) for t in pair.split("-"))
        if override is None and day.weekday() == 4:
            end = min(end, FRIDAY_CLOSE)
        if override is None and day.weekday() == 6:
            start = max(start, SUNDAY_OPEN)
        if start < end:
            windows.append((start, end))
    return sorted(windows)


def session(ts, broker_hours=None, selected=None):
    hours = broker_hours if broker_hours is not None else ("" if MODE == "demo" else BROKER_HOURS)
    market = []
    for key, name, zone, opening, closing in MARKET_SESSIONS:
        if key not in (ENTRY_SESSIONS if selected is None else selected):
            continue
        today = datetime.fromtimestamp(ts, zone).date()
        for offset in range(-1, 8):
            day = today + timedelta(days=offset)
            if day.weekday() < 5:
                market.append((int(datetime.combine(day, opening, zone).timestamp()),
                               int(datetime.combine(day, closing, zone).timestamp()), name))
    today = datetime.fromtimestamp(ts, NY).date()
    eligible = []
    for offset in range(-1, 8):
        day = today + timedelta(days=offset)
        for opening, closing in broker_windows(day, hours):
            broker_start = int(datetime.combine(day, opening, NY).timestamp())
            end = datetime.combine(day, closing, NY)
            broker_end = int((end + timedelta(microseconds=1) if closing == time.max else end).timestamp())
            eligible.extend((max(start, broker_start), min(finish, broker_end))
                            for start, finish, _ in market
                            if max(start, broker_start) < min(finish, broker_end))
    windows = []
    for start, end in sorted(eligible):
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    window = next(((start, end) for start, end in windows if ts < end), None)
    if window is None:
        return {"open": False, "opening": None, "cutoff": None, "next_myt": None, "active": [], "next": []}
    start, end = window
    opened = start <= ts < end
    names = [name for key, name, *_ in MARKET_SESSIONS
             if any(label == name and a <= (ts if opened else start) < b for a, b, label in market)]
    return {"open": opened, "opening": start, "cutoff": end,
            "next_myt": datetime.fromtimestamp(start, MY).isoformat(),
            "active": names if opened else [], "next": [] if opened else names}
