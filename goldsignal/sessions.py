from datetime import datetime

from .config import MARKET_SESSIONS

MIN_SAMPLE = 30
EVIDENCE_SAMPLE = 150


def label(ts):
    if ts is None:
        return None
    active = []
    for _, name, zone, opening, closing in MARKET_SESSIONS:
        local = datetime.fromtimestamp(ts, zone)
        if local.weekday() >= 5:
            continue
        start = local.replace(hour=opening.hour, minute=opening.minute, second=0, microsecond=0)
        end = local.replace(hour=closing.hour, minute=closing.minute, second=0, microsecond=0)
        if start <= local < end:
            active.append((start, name))
    return max(active)[1] if active else None


def wilson(wins, total, z=1.96):
    if total <= 0:
        return None, None
    p = wins / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5) / denominator
    return round(max(0.0, centre - margin) * 100, 1), round(min(1.0, centre + margin) * 100, 1)


def status(closed, wins):
    if closed == 0:
        return "No closed trades"
    if closed < MIN_SAMPLE:
        return f"Collecting evidence ({closed}/{MIN_SAMPLE})"
    if closed < EVIDENCE_SAMPLE:
        return "Provisional"
    return "Historical sample; uncalibrated"


def summary(signals, candidates, in_period, names):
    rows = {name: dict(session=name, detected=0, published=0, closed=0, wins=0, losses=0,
                        flat=0, pips=0.0, win_rate=None, low=None, high=None,
                        status="No closed trades", last=None) for name in names}
    for item in candidates:
        stamp = item.get("evaluated") or item.get("created")
        if stamp is None or not in_period(stamp):
            continue
        key = item.get("session") or label(stamp)
        if key in rows:
            rows[key]["detected"] += 1
    for signal in signals:
        if not in_period(signal.get("created", 0)):
            continue
        key = signal.get("session") or label(signal["created"])
        if key not in rows:
            continue
        rows[key]["published"] += 1
        rows[key]["last"] = max(rows[key]["last"] or 0, signal["created"])
        exits = signal.get("exits", [])
        if signal.get("fill") is None or not exits or signal["status"] not in ("COMPLETED", "STOPPED", "TIMED_OUT", "TP1_SECURED", "TP2_SECURED"):
            continue
        closed = exits[-1]["time"]
        if not in_period(closed):
            continue
        direction = 1 if signal["direction"] == "BUY" else -1
        pips = round(sum(direction * (exit["price"] - signal["fill"]) * exit["fraction"] / 0.10
                         for exit in exits), 2)
        row = rows[key]
        row["closed"] += 1
        row["pips"] = round(row["pips"] + pips, 2)
        if pips > 0 or signal.get("hits", 0) >= 1 or signal.get("status", "").startswith("TP"):
            row["wins"] += 1
        elif pips < 0:
            row["losses"] += 1
        else:
            row["flat"] += 1
    for row in rows.values():
        if row["closed"]:
            row["win_rate"] = round(100 * row["wins"] / row["closed"], 1)
            row["low"], row["high"] = wilson(row["wins"], row["closed"])
        row["status"] = status(row["closed"], row["wins"])
    return list(rows.values())
