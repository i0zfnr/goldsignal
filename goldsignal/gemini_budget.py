from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import utc_now
from .store import transaction

PACIFIC = ZoneInfo("America/Los_Angeles")
REQUESTS_PER_MINUTE = 10
FLASH_REQUESTS_PER_DAY = 450
KIND = "gemini_budget"
KEY = "shared"


class GeminiPaused(Exception):
    def __init__(self, message, resume_at):
        super().__init__(message)
        self.resume_at = resume_at


def reserve(model):
    with transaction() as store:
        state = store.lock_record(KIND, KEY)
        now = utc_now()
        today = datetime.fromtimestamp(now, PACIFIC).date()
        recent = [stamp for stamp in state.get("recent", []) if stamp > now - 60]
        counts = state.get("counts", {}) if state.get("day") == today.isoformat() else {}
        daily_limit = FLASH_REQUESTS_PER_DAY if model == "gemini-3.5-flash-lite" else 6
        used = counts.get(model, 0)
        cooldown = state.get("cooldown", 0)
        if used >= daily_limit:
            reset = datetime.combine(today + timedelta(days=1), time.min, PACIFIC).timestamp()
            raise GeminiPaused("Xeniex’s Gemini daily cap reached. Calls resume at midnight Pacific.", reset)
        if cooldown > now:
            raise GeminiPaused("Gemini is cooling down after a Google quota error.", cooldown)
        if len(recent) >= REQUESTS_PER_MINUTE:
            raise GeminiPaused("Xeniex’s Gemini cap reached (10 requests per minute).", recent[0] + 60)
        counts[model] = used + 1
        store.put(KIND, KEY, {**state, "day": today.isoformat(), "counts": counts, "recent": [*recent, now]})


def pause_after_429(response):
    retry_after = response.headers.get("Retry-After", "")
    delay = max(60, int(retry_after)) if retry_after.isascii() and retry_after.isdecimal() and len(retry_after) <= 8 else 60
    with transaction() as store:
        state = store.lock_record(KIND, KEY)
        until = max(state.get("cooldown", 0), utc_now() + delay)
        store.put(KIND, KEY, {**state, "cooldown": until})
    return until
