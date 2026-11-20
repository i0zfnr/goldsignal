from datetime import datetime

from .config import HOLD_TTL, MY
from .strategy import executable


def advance(signal, quote, now, can_fill, costs):
    fractions = signal.get("exit_fractions", (1 / 3,) * 3)
    status = signal["status"]
    if status == "PENDING":
        if now >= signal["expiry"]:
            signal["status"] = "EXPIRED"
            return [("EXPIRED", signal["stop"])]
        if quote and can_fill and signal["entry"][0] <= executable(signal, quote) <= signal["entry"][1]:
            signal.update(status="FILLED", fill=executable(signal, quote), filled_at=now,
                          holding_until=now + signal.get("hold_seconds", HOLD_TTL))
            return [("FILLED", signal["stop"])]
    if status != "FILLED" or not quote:
        return []
    price = executable(signal, quote, exit_side=True)
    sign = 1 if signal["direction"] == "BUY" else -1
    events = []
    if sign * (price - signal["stop"]) <= 0:
        events.append(("STOPPED", signal["stop"]))
    elif now >= signal["holding_until"]:
        events.append(("TIMED_OUT", signal["stop"]))
    else:
        while signal["hits"] < 3 and sign * (price - signal["targets"][signal["hits"]]) >= 0:
            index = signal["hits"]
            signal["hits"] += 1
            signal["exits"].append(dict(time=now, price=price, kind=f"TP{index + 1}", fraction=fractions[index]))
            if index < 2:
                signal["stop"] = signal["reference"] if index == 0 else signal["targets"][0]
            events.append((f"TP{index + 1}", signal["stop"]))
    if events and events[0][0] in ("STOPPED", "TIMED_OUT"):
        if signal.get("hits", 0) >= 1:
            signal["status"] = f"TP{signal['hits']}_SECURED" if events[0][0] == "STOPPED" else "COMPLETED"
        else:
            signal["status"] = events[0][0]
        signal["exits"].append(dict(time=now, price=price, kind=signal["status"], fraction=sum(fractions[signal["hits"]:])))
    if signal["hits"] == 3:
        signal["status"] = "COMPLETED"
    if costs:
        contract, conversion, slip, commission = [costs[key] for key in ("contract", "conversion", "slippage", "commission")]
        signal["result_per_lot"] = round(sum(
            ((sign * (row["price"] - signal["fill"]) - slip) * contract * conversion - commission) * row["fraction"]
            for row in signal["exits"]
        ), 2)
    return events


def day(ts):
    return datetime.fromtimestamp(ts, MY).date()


def profile_result(signal, entry, today):
    costs = signal["costs"]
    sign = 1 if signal["direction"] == "BUY" else -1
    if entry["policy"] == "single":
        exits = signal["exits"][:1]
        lots = [entry["fit"]["lot"]]
    else:
        lot, minimum, step = entry["fit"]["lot"], entry["fit"]["minimum"], entry["step"]
        extra = round((lot - 3 * minimum) / step)
        lots = [minimum + (extra // 3 + (i < extra % 3)) * step for i in range(3)]
        exits = signal["exits"]
        if exits and exits[-1]["kind"] in ("STOPPED", "TIMED_OUT"):
            lots = lots[:len(exits) - 1] + [sum(lots[len(exits) - 1:])]
    return sum(((sign * (row["price"] - signal["fill"]) - costs["slippage"]) *
                costs["contract"] * costs["conversion"] - costs["commission"]) * lot
               for row, lot in zip(exits, lots) if day(row["time"]) == today)


def realized(store, profile_id, now, currency=None, units=None):
    total = 0
    for signal in store.all("signal"):
        entry = signal.get("eligible", {}).get(profile_id)
        if entry and (currency is None or (currency == entry["fit"]["currency"] and units == entry["units"])):
            total += profile_result(signal, entry, day(now))
    return total
