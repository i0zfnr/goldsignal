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
BROKER_HOURS = os.getenv("BROKER_HOURS", "")
BROKER_HOLIDAYS = set(filter(None, os.getenv("BROKER_CLOSED_DATES", "").split(",")))
BROKER_DATE_HOURS = json.loads(os.getenv("BROKER_DATE_HOURS") or "{}")
FRIDAY_CLOSE = time.fromisoformat(os.getenv("BROKER_FRIDAY_CLOSE", "17:00"))
SUNDAY_OPEN = time.fromisoformat(os.getenv("BROKER_SUNDAY_OPEN", "18:00"))
MAX_SPREAD = float(os.getenv("MAX_SPREAD", "0.5"))
STALE_SECONDS = int(os.getenv("QUOTE_MAX_AGE", "20"))
ENTRY_TTL = int(os.getenv("ENTRY_TTL_MIN", "30")) * 60
HOLD_TTL = int(os.getenv("HOLD_TTL_MIN", "180")) * 60
NEWS_BEFORE = int(os.getenv("NEWS_BEFORE_MIN", "20")) * 60
NEWS_AFTER = int(os.getenv("NEWS_AFTER_MIN", "15")) * 60
CALENDAR_MAX_AGE = int(os.getenv("CALENDAR_MAX_AGE_HOURS", "6")) * 3600
SWING = int(os.getenv("SWING_BARS", "2"))
ZONE_WIDTH = float(os.getenv("ZONE_WIDTH", "0.8"))
TREND = int(os.getenv("TREND_BARS", "4"))
REVIEW = os.getenv("SIGNAL_REVIEW_MODE", "rules")


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


def session(ts, broker_hours=None):
    now = datetime.fromtimestamp(ts, NY)
    hours = broker_hours if broker_hours is not None else ("" if MODE == "demo" else BROKER_HOURS)
    for days in range(8):
        day = now.date() + timedelta(days=days)
        if day.weekday() >= 5:
            continue
        for opening, closing in broker_windows(day, hours):
            start = datetime.combine(day, max(ENTRY_START, opening), NY)
            end = datetime.combine(day, min(ENTRY_END, closing), NY)
            if start >= end or now >= end:
                continue
            return {
                "open": start <= now < end,
                "opening": int(start.timestamp()),
                "cutoff": int(end.timestamp()),
                "next_myt": start.astimezone(MY).isoformat(),
            }
    return {"open": False, "opening": None, "cutoff": None, "next_myt": None}
