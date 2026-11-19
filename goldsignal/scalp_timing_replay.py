"""Staged, offline A/B replay. Uses no orders, AI services, or notification channel."""

import json
from collections import Counter
from itertools import product

from . import scalp_research as research


def scenario_key(period, processing, post, review, commission, account):
    return (f"{period}/processing{processing:g}/post{post:g}/review{review:g}/commission{commission:g}/"
            + ("strategy_per_lot" if account is None else f"USD{account}_1pct"))


def portfolio(candidates, results, account):
    rows, published = [], []
    exposure_until = realized = 0
    ordered = sorted(zip(candidates, results), key=lambda pair: (
        pair[1]["timing"].get("earliest_valid_submission", float("inf")), pair[0]["id"]))
    for item, original in ordered:
        result = {**original, "timing": {**original["timing"]},
                  "unconstrained_outcome": original["outcome"]}
        alert = result["alert_time"]
        if alert is not None:
            published = [stamp for stamp in published if stamp > alert - 3600]
            if len(published) >= 2 or alert < exposure_until:
                result.update(outcome="suppressed", reason="Two per hour cap or existing exposure",
                              alert_time=None, blocked_stage="portfolio")
                result["timing"]["submission"] = None
            elif account is not None and realized <= -account * .03:
                result.update(outcome="risk_blocked", reason="Tracked daily loss limit reached",
                              alert_time=None, blocked_stage="before_submission")
                result["timing"]["submission"] = None
            else:
                published.append(alert)
                exposure_until = result.get("exit_time", item["expiry"] + 1800
                                            if result["outcome"] == "incomplete" else item["expiry"])
                if result["outcome"] == "filled":
                    realized += result["net"]
        rows.append(dict(id=item["id"], strategy=item["strategy"], **result))
    return rows


def run(options):
    manifest = json.loads((options.archive / "manifest.json").read_text(encoding="utf-8"))
    frames = json.loads((options.archive / "candles.json").read_text(encoding="utf-8"))
    if manifest["symbol"] != research.SYMBOL or manifest["broker_hours"] != research.BROKER_HOURS:
        raise ValueError("Use archived symbol and broker-hours configuration")
    if not manifest["start"] < options.split < manifest["until"]:
        raise ValueError("Split must fall inside archived interval")
    records, coverage, counts, diagnostics = {}, {}, Counter(), {}
    for session in manifest["sessions"]:
        day = session["day"]
        period = "development" if day < options.split else "evaluation"
        ticks, coverage[day] = research.load_ticks(research.tick_file(options.archive, day))
        if not ticks:
            continue
        counts[period] += 1
        times = [tick["time"] for tick in ticks]
        detected, diagnostics[day] = research.detect(frames, session["opening"], session["cutoff"])
        candidates = [item for item in detected if item["id"].startswith("s")]
        for processing, post, commission, account in product(
                options.processing, options.post_delays, options.commissions, (None, 100, 1000)):
            key = scenario_key(period, processing, post, options.review, commission, account)
            costs = {**manifest["costs"], "commission": commission,
                     "slippage": manifest["costs"]["slippage"] * options.cost_multiplier}
            profile = None if account is None else dict(
                symbol=research.SYMBOL, currency="USD", units_per_currency=1, equity=account,
                free_margin=account, risk_pct=1, daily_loss_pct=3, exit_policy="split", max_age=1)
            results = [research.execute(item, ticks, times, post, manifest["calendar"].get("events", []),
                                        costs, profile, processing=processing, review=options.review)
                       for item in candidates]
            rows = portfolio(candidates, results, account)
            records.setdefault(key, []).extend(dict(day=day, **row) for row in rows)
        print(f"Staged replay {day}: {len(candidates)} identical M5/M1 candidates", flush=True)
    original = json.loads(options.previous.read_text(encoding="utf-8")) if options.previous.exists() else None
    originals = ([row for row in original["records"]["evaluation/B/5s/strategy_per_lot"]
                  if row["outcome"] == "filled"] if original else [])
    survivors = {}
    for key, rows in records.items():
        if not key.startswith("evaluation/") or not key.endswith("strategy_per_lot"):
            continue
        by_id = {row["id"]: row for row in rows}
        survivors[key] = [dict(id=row["id"], day=row["day"], original_net=row["net"],
                               outcome=by_id[row["id"]]["outcome"], reason=by_id[row["id"]]["reason"],
                               unconstrained_outcome=by_id[row["id"]]["unconstrained_outcome"],
                               net=by_id[row["id"]].get("net"), timing=by_id[row["id"]]["timing"])
                          for row in originals]
    report = dict(
        version=2, symbol=manifest["symbol"], archive=str(options.archive),
        covered_sessions=dict(counts), coverage=coverage, split=options.split,
        assumptions=dict(review_seconds=options.review, processing_seconds=options.processing,
                         post_submission_seconds=options.post_delays,
                         commission_USD_per_lot_round_trip=options.commissions,
                         slippage_price=manifest["costs"]["slippage"] * options.cost_multiplier,
                         phone_measurements=False, actual_account_commission_verified=False),
        model="Review once from confirmation; process after eligibility; recheck/retry before first valid submission; "
              "post delay starts at submission; first action quote is final. Risk profiles screen before submission and at action.",
        comparison="A post30 versus B post5 at identical processing, review, commission, rules and tick stream.",
        production_risk="Shared ENTRY publication has no viewer account_fit gate. Profile screening here is counterfactual.",
        summaries={key: research.summary(rows, counts[key.split('/')[0]]) for key, rows in records.items()},
        records=records, original_13_survivors=survivors,
        original_publication_plus_30_diagnostic=original.get("original_four_30s") if original else None,
        setup_diagnostics=diagnostics, paid_api_calls=0,
        limitations=manifest["limitations"] + [
            "Five evaluation sessions are historical, previously inspected, not a fresh holdout",
            "One active exposure and per-profile publication screen are research constraints",
            "Calendar cache lacks point-in-time historical completeness",
            "Processing retries are deterministic, not measured worker scheduling",
            "No push transport or user receipt was measured"],
    )
    research.write_json(options.output, report)
