"""Frozen, local USD100 strategy search. No worker, orders, AI calls or push transport."""

import argparse
import bisect
import gzip
import hashlib
import json
from collections import Counter
from itertools import product
from pathlib import Path

import numpy as np

from . import scalp_research as replay
from .strategy import executable


SCENARIOS = {
    "base": dict(processing=2, post=5, commission=7, slippage=.10),
    "slow": dict(processing=2, post=30, commission=7, slippage=.10),
    "cost": dict(processing=2, post=5, commission=14, slippage=.20),
    "slow_cost": dict(processing=2, post=30, commission=14, slippage=.20),
    "zero_commission": dict(processing=2, post=5, commission=0, slippage=.10),
}
CRITERIA = dict(development_min_completed=10, validation_min_completed_per_window=5,
                minimum_mean_net=0, maximum_closed_drawdown=10, maximum_losing_streak=5,
                minimum_entries_per_session=.5, shortlist_limit=20)


def configurations(limit=960):
    unique = {}
    for family, lookback, confirmation, stop, reward in product(
            ("breakout_retest", "trend_pullback", "range_reversal"), (3, 6, 9, 12, 18),
            ("body", "engulf", "close_break", "wick"), ("trigger", "setup", "swing_m1", "swing_m5"),
            (.5, 1, 1.5, 2)):
        config = dict(family=family, lookback=lookback, confirmation=confirmation, stop=stop,
                      reward=reward, exit_policy="single", lot=.01, hold_seconds=1800)
        if family == "trend_pullback" and confirmation == "close_break":
            config["confirmation"] = "body"
        canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
        unique[canonical] = dict(id=hashlib.sha256(canonical.encode()).hexdigest()[:12], **config)
    return list(unique.values())[:limit]


def confirmed(rows, sign, rule):
    candle, previous = rows[-1], rows[-2]
    body = sign * (candle["close"] - candle["open"])
    if body <= 0:
        return False
    if rule == "body":
        return True
    if rule == "close_break":
        return sign * (candle["close"] - previous["high" if sign == 1 else "low"]) > 0
    if rule == "engulf":
        return (min(candle["open"], candle["close"]) <= min(previous["open"], previous["close"])
                and max(candle["open"], candle["close"]) >= max(previous["open"], previous["close"]))
    width = candle["high"] - candle["low"]
    tail = candle["open"] - candle["low"] if sign == 1 else candle["high"] - candle["open"]
    return width > 0 and tail >= body and sign * (candle["close"] - (candle["low"] + candle["high"]) / 2) >= width / 6


def candidates(config, frames, opening, cutoff):
    closes = {name: [row["time"] + replay.FRAMES[name] for row in rows] for name, rows in frames.items()}
    found = {}
    for candle in frames["M1"]:
        now = candle["time"] + 60
        if not opening <= now < cutoff:
            continue
        m1 = replay.closed_slice(frames, closes, "M1", now, 3)
        m5 = replay.closed_slice(frames, closes, "M5", now, config["lookback"] + 1)
        m15 = replay.closed_slice(frames, closes, "M15", now, 4)
        if len(m1) != 3 or len(m5) != config["lookback"] + 1 or len(m15) != 4:
            continue
        if any(b["time"] - a["time"] != period for rows, period in ((m1, 60), (m5, 300), (m15, 900))
               for a, b in zip(rows, rows[1:])):
            continue
        setup, previous = m5[-1], m5[:-1]
        setup_close = setup["time"] + 300
        if not opening <= setup_close <= candle["time"] < setup_close + 300:
            continue
        high, low = max(row["high"] for row in previous), min(row["low"] for row in previous)
        average = sum(row["high"] - row["low"] for row in previous) / len(previous)
        trend = m15[-1]["close"] - m15[0]["close"]
        for side, sign in (("BUY", 1), ("SELL", -1)):
            if not confirmed(m1, sign, config["confirmation"]):
                continue
            if config["family"] == "breakout_retest":
                boundary = high if sign == 1 else low
                valid = (sign * trend > 0 and sign * (setup["close"] - setup["open"]) > 0
                         and sign * (setup["close"] - boundary) > 0
                         and abs(candle["low" if sign == 1 else "high"] - boundary) <= average * .20
                         and sign * (candle["close"] - boundary) > 0)
            elif config["family"] == "trend_pullback":
                valid = (sign * trend > 0 and sign * (previous[-1]["close"] - previous[0]["open"]) > 0
                         and sign * (setup["close"] - setup["open"]) < 0
                         and sign * (candle["close"] - m1[-2]["high" if sign == 1 else "low"]) > 0)
            else:
                boundary = low if sign == 1 else high
                valid = (abs(trend) <= (high - low) * .25
                         and sign * (setup["low" if sign == 1 else "high"] - boundary) < 0
                         and sign * (setup["close"] - boundary) > 0)
            if not valid:
                continue
            rows = {"trigger": m1[-1:], "setup": m5[-1:], "swing_m1": m1[-2:], "swing_m5": m5[-3:]}[config["stop"]]
            extreme = (min(row["low"] for row in rows) if sign == 1 else max(row["high"] for row in rows))
            buffer = max(.10, sum(row["high"] - row["low"] for row in rows) / len(rows) * .10)
            stop = round(extreme - sign * buffer, 2)
            reference = candle["close"]
            risk = sign * (reference - stop)
            if risk <= 0:
                continue
            identity = f"{setup_close}{side[0]}"
            if identity in found:
                continue
            found[identity] = dict(id=identity, strategy=config["family"], direction=side, close_time=now,
                                   created=now, expiry=min(now + 120, setup_close + 300, cutoff),
                                   reference=reference, entry=sorted([round(reference - sign * risk * .25, 2), reference]),
                                   initial_stop=stop, stop=stop, targets=[round(reference + sign * risk * config["reward"], 2)],
                                   max_spread=replay.MAX_SPREAD, hold_seconds=config["hold_seconds"])
    return sorted(found.values(), key=lambda row: (row["close_time"], row["id"]))


def tick_columns(ticks, events):
    times = np.array([row["time"] for row in ticks])
    bid = np.array([row["bid"] for row in ticks])
    ask = np.array([row["ask"] for row in ticks])
    news = np.zeros(len(ticks), dtype=bool)
    from .config import NEWS_AFTER, NEWS_BEFORE
    for event in events:
        if event.get("impact", "high") == "high":
            news |= ((times >= event["time"] - NEWS_BEFORE) & (times <= event["time"] + NEWS_AFTER)
                     & (times >= event.get("observed_from", -float("inf")))
                     & (times < event.get("observed_until", float("inf"))))
    return times, bid, ask, news


def eligible_quotes(item, columns):
    times, bid, ask, news = columns
    first, end = int(times.searchsorted(item["close_time"])), int(times.searchsorted(item["expiry"]))
    prices = (ask if item["direction"] == "BUY" else bid)[first:end]
    spread = ask[first:end] - bid[first:end]
    mask = (spread <= item["max_spread"]) & (prices >= item["entry"][0]) & (prices <= item["entry"][1]) & ~news[first:end]
    indices = (np.flatnonzero(mask) + first).tolist()
    if indices:
        return indices, None
    for index in range(first, min(end, first + 1)):
        if ask[index] - bid[index] > item["max_spread"]:
            return [], "Spread exceeds configured limit"
        elif not item["entry"][0] <= (ask[index] if item["direction"] == "BUY" else bid[index]) <= item["entry"][1]:
            return [], "Executable quote is outside the entry zone"
        else:
            return [], "Calendar pause"
    return [], "No broker ticks"


def metrics(rows, sessions):
    result = replay.summary(rows, sessions)
    closed = sorted((row for row in rows if row["outcome"] == "filled"), key=lambda row: row["exit_time"])
    streak = worst = 0
    for row in closed:
        streak = streak + 1 if row["net"] < 0 else 0
        worst = max(worst, streak)
    result["worst_losing_streak"] = worst
    result["first_blockers"] = dict(Counter(row["reason"] for row in rows if row["outcome"] not in ("filled", "incomplete")))
    result["otherwise_actionable"] = sum(row.get("action_gate", {}).get("decision") == "CONFIRM" for row in rows)
    result["partial_exit_first_blockers"] = dict(Counter(row["partial_first_blocker"] for row in rows))
    return result


def passes(result, minimum):
    return (result["completed"] >= minimum and result["mean_net"] is not None and result["mean_net"] > 0
            and result["closed_trade_drawdown"] <= CRITERIA["maximum_closed_drawdown"]
            and result["worst_losing_streak"] <= CRITERIA["maximum_losing_streak"]
            and result["executable_per_session"] >= CRITERIA["minimum_entries_per_session"])


def simulate(config, prepared, scenario, sink):
    equity = 100.0
    all_rows = []
    for session, ticks, times, events, detected in prepared:
        costs = {**session["costs"], "commission": scenario["commission"], "slippage": scenario["slippage"]}
        scheduled = []
        for item, indices, failure in detected:
            if failure:
                result = dict(outcome="blocked", reason=failure, alert_time=None, timing={}, action_gate={})
            else:
                result = replay.execute(item, ticks, times, scenario["post"], events, costs,
                                        processing=scenario["processing"], review=scenario.get("review", 0), detection=scenario.get("detection", 0),
                                        eligible_indices=indices, trace_only=True)
            scheduled.append((item, indices, result))
        scheduled.sort(key=lambda entry: (entry[2].get("timing", {}).get("earliest_valid_submission", float("inf")), entry[0]["id"]))
        published = []
        exposure_until = daily_net = 0
        day_start_equity = equity
        for item, indices, schedule in scheduled:
            result = schedule
            stamp = result.get("alert_time")
            if stamp is not None:
                published = [old for old in published if old > stamp - 3600]
                if len(published) >= 2 or stamp < exposure_until:
                    result = dict(outcome="suppressed", reason="Two per hour cap or existing exposure", alert_time=None,
                                  timing=schedule["timing"], action_gate=schedule.get("action_gate", {}))
                elif daily_net <= -.03 * day_start_equity:
                    result = dict(outcome="risk_blocked", reason="Tracked daily loss limit reached", alert_time=None,
                                  timing=schedule["timing"], action_gate=schedule.get("action_gate", {}))
                else:
                    profile = dict(equity=equity, free_margin=equity, units_per_currency=1, risk_pct=1)
                    result = replay.execute(item, ticks, times, scenario["post"], events, costs, profile,
                                            processing=scenario["processing"], fixed_lot=.01, exit_policy="single",
                                            review=scenario.get("review", 0), detection=scenario.get("detection", 0), eligible_indices=indices)
                    if result["alert_time"] is not None:
                        published.append(result["alert_time"])
                        exposure_until = result.get("exit_time", item["expiry"] + 1800
                                                    if result["outcome"] == "incomplete" else item["expiry"])
                        if result["outcome"] == "filled":
                            equity = round(equity + result["net"], 2)
                            daily_net = round(daily_net + result["net"], 2)
            partial_reason = result["reason"]
            if result.get("submission_risk", {}).get("decision") == "FIT":
                partial_reason = "Invalid exit volume: three broker-valid partials require at least 0.03 lot"
            row = dict(config=config["id"], scenario=scenario, day=session["day"], id=item["id"],
                       natural_stop=item["initial_stop"], partial_first_blocker=partial_reason, **result)
            all_rows.append(row)
            sink.write(json.dumps(row, allow_nan=False) + "\n")
    result = metrics(all_rows, len(prepared))
    result["ending_equity"] = equity
    return result


def prepare(config, sessions, frames):
    prepared = []
    for session, ticks, times, events, columns in sessions:
        detected = []
        for item in candidates(config, frames, session["opening"], session["cutoff"]):
            indices, failure = eligible_quotes(item, columns)
            detected.append((item, indices, failure))
        prepared.append((session, ticks, times, events, detected))
    return prepared


def rank(result):
    return (-result["executable_per_session"], -(result["mean_net"] if result["mean_net"] is not None else -float("inf")),
            result["closed_trade_drawdown"], result["worst_losing_streak"])


def run(options):
    config_list = configurations(options.limit)
    manifest = json.loads((options.archive / "manifest.json").read_text(encoding="utf-8"))
    frames = json.loads((options.archive / "candles.json").read_text(encoding="utf-8"))
    if manifest["symbol"] != replay.SYMBOL or manifest["broker_hours"] != replay.BROKER_HOURS:
        raise ValueError("Archived symbol and broker-hours configuration required")
    scenarios = SCENARIOS
    development_until = "2026-11-12"
    validation_windows = [["2026-11-12", "2026-11-14"], ["2026-11-16", "2026-11-19"]]
    study = None
    if getattr(options, "study", None):
        study = json.loads(options.study.read_text())
        if not getattr(options, "timing", None):
            raise ValueError("A real phone timing report is required for the prospective study")
        timing = json.loads(options.timing.read_text())
        if not timing.get("usable_for_grid") or timing["paired_count"] < study["measured_entry_pairs_required"]:
            raise ValueError("Insufficient real, paired ENTRY phone timing; assumptions will not be substituted")
        if config_list != study["configurations"]:
            raise ValueError("Frozen study configurations changed")
        if study["criteria"] != CRITERIA:
            raise ValueError("Frozen study selection criteria changed")
        admitted = [row for row in manifest["sessions"] if row["day"] >= study["start"]]
        n = study["development_sessions"]
        a, b = study["validation_sessions"]
        if len(admitted) < n + a + b:
            raise ValueError(f"Need {n + a + b} admitted future sessions; have {len(admitted)}")
        admitted = admitted[:n + a + b]
        from .config import NY
        from datetime import datetime
        calibration_days = {row["day"] for row in admitted[:n]}
        if any(str(datetime.fromtimestamp(pair["submitted_at"], NY).date()) not in calibration_days for pair in timing["pairs"]):
            raise ValueError("Timing calibration must exclude validation and final periods")
        from datetime import date, timedelta
        development_until = admitted[n]["day"]
        validation_windows = [[admitted[n]["day"], admitted[n + a]["day"]],
                              [admitted[n + a]["day"], str(date.fromisoformat(admitted[-1]["day"]) + timedelta(days=1))]]
        manifest["sessions"] = admitted

        def quantile(field, fraction):
            values = sorted(row[field] for row in timing["pairs"])
            return values[round((len(values) - 1) * fraction)]

        scenarios = {name: {**value, "post": quantile("post_submission_seconds", .9 if name in ("slow", "slow_cost") else .5),
                             "processing": quantile("processing_seconds", .5), "review": 0, "detection": quantile("detection_seconds", .5)}
                     for name, value in SCENARIOS.items()}
        scenarios["slow_processing"] = {**scenarios["base"], "processing": quantile("processing_seconds", .9)}
        scenarios["slow_detection"] = {**scenarios["base"], "detection": quantile("detection_seconds", .9)}
    folder = options.output
    folder.mkdir(parents=True, exist_ok=False)
    plan = dict(version=1, configs=config_list, canonical_unique=len(config_list), criteria=CRITERIA,
                scenarios=scenarios, archive=str(options.archive), development_until=development_until,
                validation_windows=validation_windows,
                final_period="Future completed New York sessions after shortlist freeze; never used for selection",
                risk="USD100 initial equity; 1% current closed equity; fixed 0.01 lot; executable entry to natural stop plus costs",
                rule="One active/pending opportunity; two alerts/rolling hour; 3% daily realized loss stop",
                spread="Fixed existing MAX_SPREAD, not the baseline's strategy-specific 0.20R spread ceiling",
                timing=("Measured detection prelag, eligibility-to-submission elapsed, and submission-to-action delay; AI review0. Shared median/p90 stresses"
                        if study else "Review0; processing2 after eligibility; post5 or30 after valid submission; all assumptions"),
                code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                prospective_study=study, measured_timing_source=str(options.timing) if study else None)
    replay.write_json(folder / "plan.json", plan)
    sessions = []
    for session in manifest["sessions"]:
        ticks, audit = replay.load_ticks(replay.tick_file(options.archive, session["day"]))
        if not ticks or audit["gaps_over_20s"]:
            raise ValueError(f"Incomplete tick coverage: {session['day']}")
        times = [tick["time"] for tick in ticks]
        events = manifest["calendar"].get("events", [])
        sessions.append(({**session, "costs": manifest["costs"]}, ticks, times, events, tick_columns(ticks, events)))
    development = [row for row in sessions if row[0]["day"] < plan["development_until"]]
    if not development:
        raise ValueError("No development sessions")
    results, eligible, stage_counts = {}, [], Counter(generated=len(config_list))
    with gzip.open(folder / "candidate-ledger.jsonl.gz", "wt", encoding="utf-8") as sink:
        for index, config in enumerate(config_list):
            prepared = prepare(config, development, frames)
            result = {name: simulate(config, prepared, scenario, sink) for name, scenario in scenarios.items()}
            results[config["id"]] = dict(config=config, development=result)
            base = result["base"]
            stage_counts["nonzero_development"] += base["completed"] > 0
            if passes(base, CRITERIA["development_min_completed"]):
                eligible.append(config)
            if (index + 1) % 40 == 0:
                print(f"Development {index + 1}/{len(config_list)}; eligible {len(eligible)}", flush=True)
        stage_counts["development_pass"] = len(eligible)
        eligible.sort(key=lambda config: rank(results[config["id"]]["development"]["base"]))
        shortlist = eligible[:CRITERIA["shortlist_limit"]]
        replay.write_json(folder / "development-shortlist.json", shortlist)
        stage_counts["shortlisted_before_validation"] = len(shortlist)
        finalists = []
        for config in shortlist:
            windows = {}
            for lower, upper in plan["validation_windows"]:
                selected = [row for row in sessions if lower <= row[0]["day"] < upper]
                if not selected:
                    raise ValueError("Missing validation window")
                prepared = prepare(config, selected, frames)
                windows[lower] = {name: simulate(config, prepared, scenario, sink) for name, scenario in scenarios.items()}
            results[config["id"]]["validation"] = windows
            base_pass = all(passes(window["base"], CRITERIA["validation_min_completed_per_window"]) for window in windows.values())
            stage_counts["validation_base_pass"] += base_pass
            stresses = [name for name in scenarios if name not in ("base", "zero_commission")]
            for scenario in stresses:
                stage_counts["validation_" + scenario + "_pass"] += base_pass and all(
                    passes(window[scenario], CRITERIA["validation_min_completed_per_window"]) for window in windows.values())
            if base_pass and all(passes(window[name], CRITERIA["validation_min_completed_per_window"])
                                 for window in windows.values() for name in stresses):
                finalists.append(config)
        stage_counts["all_validation_stresses_pass"] = len(finalists)
    replay.write_json(folder / "frozen-finalists.json", dict(configs=finalists, plan=plan,
                                                           selection_closed=True, final_data_not_evaluated=True))
    ranking = sorted((key for key, result in results.items() if result["development"]["base"]["completed"]),
                     key=lambda key: rank(results[key]["development"]["base"]))
    replay.write_json(folder / "results.json", dict(stage_counts=dict(stage_counts), results=results,
                                                   development_ranking=ranking, paid_api_calls=0,
                                                   final="Not evaluated. Requires future uninspected completed session data."))
    print(dict(stage_counts), flush=True)


def audit_previous(source, output):
    """Reuse identical tested configurations; remove logical aliases and recount publications from rows."""
    original = json.loads((source / "results.json").read_text(encoding="utf-8"))
    old_plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
    if old_plan["criteria"] != CRITERIA or old_plan["scenarios"] != SCENARIOS:
        raise ValueError("Cannot reuse different rules or scenarios")
    canonical = {config["id"]: config for config in configurations()}
    for key, config in canonical.items():
        if original["results"].get(key, {}).get("config") != config:
            raise ValueError("Every canonical configuration must already have identical tested rules")
    output.mkdir(parents=True, exist_ok=False)
    results = {key: original["results"][key] for key in canonical}
    scenario_names = {json.dumps(value, sort_keys=True): name for name, value in SCENARIOS.items()}
    published, rows_count = Counter(), 0
    fingerprints = {key: hashlib.sha256() for key in canonical}
    with gzip.open(source / "candidate-ledger.jsonl.gz", "rt", encoding="utf-8") as incoming, \
            gzip.open(output / "candidate-ledger.jsonl.gz", "wt", encoding="utf-8") as outgoing:
        for line in incoming:
            row = json.loads(line)
            key = row["config"]
            if key not in canonical:
                continue
            if row["day"] >= old_plan["development_until"]:
                raise ValueError("This audit supports the empty-shortlist development run only")
            name = scenario_names[json.dumps(row["scenario"], sort_keys=True)]
            published[key, name] += row.get("alert_time") is not None
            if name == "base":
                behavior = {field: value for field, value in row.items() if field != "config"}
                fingerprints[key].update(json.dumps(behavior, sort_keys=True).encode())
            outgoing.write(line)
            rows_count += 1
    for key, result in results.items():
        for name, summary in result["development"].items():
            summary["alerts"] = published[key, name]
            summary["executable_percent"] = (round(100 * summary["executable_entries"] / summary["alerts"], 2)
                                             if summary["alerts"] else None)
    eligible = [key for key, result in results.items() if passes(result["development"]["base"], CRITERIA["development_min_completed"])]
    if eligible:
        raise ValueError("Reuse cannot change shortlist; rerun staged selection if any configuration qualifies")
    groups = {}
    for key, fingerprint in fingerprints.items():
        groups.setdefault(fingerprint.hexdigest(), []).append(key)
    plan = {**old_plan, "configs": list(canonical.values()), "canonical_unique": len(canonical),
            "raw_generated": len(old_plan["configs"]), "reuse_source": str(source),
            "normalization": "Pullback already requires close-break, so close_break confirmation aliases body",
            "source_plan_sha256": hashlib.sha256((source / "plan.json").read_bytes()).hexdigest(),
            "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "engine_sha256": hashlib.sha256(Path(replay.__file__).read_bytes()).hexdigest()}
    stage_counts = dict(raw_generated=len(old_plan["configs"]), canonical_distinct=len(canonical),
                        nonzero_development=sum(result["development"]["base"]["completed"] > 0 for result in results.values()),
                        development_pass=0, shortlisted_before_validation=0, validation_evaluated=0,
                        validation_base_pass=0, validation_slow_pass=0, validation_cost_pass=0,
                        validation_slow_cost_pass=0, all_validation_stresses_pass=0, final_evaluated=0)
    ranking = sorted((key for key, result in results.items() if result["development"]["base"]["completed"]),
                     key=lambda key: rank(results[key]["development"]["base"]))
    replay.write_json(output / "plan.json", plan)
    replay.write_json(output / "results.json", dict(stage_counts=stage_counts, results=results,
                                                   development_ranking=ranking, ledger_rows=rows_count,
                                                   observed_behavior_groups=list(groups.values()),
                                                   paid_api_calls=0, audit="Identical cached executions; canonical aliases removed; publications recounted",
                                                   final="No eligible shortlist. Validation and fresh final period not evaluated."))
    replay.write_json(output / "development-shortlist.json", [])
    replay.write_json(output / "frozen-finalists.json", dict(configs=[], plan=plan, selection_closed=True,
                                                           final_data_not_evaluated=True))
    print(stage_counts, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=960)
    parser.add_argument("--audit-previous", type=Path)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--timing", type=Path)
    options = parser.parse_args()
    if not 1 <= options.limit <= 960:
        parser.error("Limit must be between 1 and 960 canonical variants")
    if options.audit_previous:
        audit_previous(options.audit_previous, options.output)
    elif options.archive:
        run(options)
    else:
        parser.error("An archive or an existing run to audit is required")


if __name__ == "__main__":
    main()
