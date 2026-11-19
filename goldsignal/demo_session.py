"""Launch an isolated live-feed paper account and collect future broker sessions."""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / ".research" / "demo-phone"


def audit_broker():
    from .market import MT5
    from .config import SYMBOL, UTC, utc_now
    from collections import defaultdict
    import hashlib
    source = MT5()
    mt5 = source.mt5
    if not mt5.initialize(*([source.path] if source.path else []), timeout=8000):
        raise RuntimeError("MT5 unavailable for broker audit")
    try:
        account, info, quote = mt5.account_info(), mt5.symbol_info(SYMBOL), mt5.symbol_info_tick(SYMBOL)
        if not account or not info or not quote:
            raise RuntimeError("Broker account/symbol/quote unavailable")
        deals = mt5.history_deals_get(datetime.now(UTC) - timedelta(days=90), datetime.now(UTC))
        positions = defaultdict(list)
        for deal in deals or []:
            if deal.symbol == SYMBOL and deal.type in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                positions[deal.position_id].append(deal)
        observed = []
        for rows in positions.values():
            incoming = sum(deal.volume for deal in rows if deal.entry == mt5.DEAL_ENTRY_IN)
            outgoing = sum(deal.volume for deal in rows if deal.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY))
            if incoming > 0 and abs(incoming - outgoing) < 1e-8:
                observed.append(round(-sum(deal.commission + deal.fee for deal in rows) / incoming, 6))
        margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, SYMBOL, .01, quote.ask)
        checked = utc_now()
        report = dict(checked_at=checked, symbol=SYMBOL, company=account.company,
                      mode="demo" if account.trade_mode == 0 else "real_or_contest", account_currency=account.currency,
                      account_fingerprint=hashlib.sha256(f"{account.login}:{account.server}".encode()).hexdigest(),
                      account_type_name="Commercial account subtype not exposed by MT5",
                      symbol_specs={name: getattr(info, name) for name in ("volume_min", "volume_step", "volume_max",
                                    "trade_contract_size", "trade_tick_size", "trade_tick_value", "digits", "currency_profit", "currency_margin", "trade_mode")},
                      minimum_buy_margin_current=margin,
                      margin_rate_current=margin / (quote.ask * .01 * info.trade_contract_size) if margin else None,
                      completed_round_trips_90d=len(observed), observed_commission_and_fee_per_lot=sorted(set(observed)),
                      history_query_success=deals is not None,
                      commission_status="observed_account_history_only" if observed else "unverified_no_complete_round_trips",
                      clock_offset_seconds=source.offset)
        FOLDER.mkdir(parents=True, exist_ok=True)
        audits = FOLDER / "broker-audits"
        audits.mkdir(exist_ok=True)
        (audits / f"{int(checked)}.json").write_text(json.dumps(report, indent=2))
        (ROOT / ".research" / "demo-broker-audit.json").write_text(json.dumps(report, indent=2))
        print(f"Broker snapshot saved; completed round trips={len(observed)}, observed fees/lot={report['observed_commission_and_fee_per_lot']}")
        return report
    finally:
        mt5.shutdown()


def configure():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    audit = json.loads((ROOT / ".research" / "demo-broker-audit.json").read_text())
    if audit["mode"] != "demo" or audit["account_currency"] != "USD":
        raise RuntimeError("A verified USD demo terminal is required")
    protocol_path = FOLDER / "protocol.json"
    if protocol_path.exists():
        pinned = json.loads(protocol_path.read_text()).get("account_fingerprint")
        if pinned and pinned != audit.get("account_fingerprint"):
            raise RuntimeError("Broker account changed from the frozen study; restore the pinned demo account")
    FOLDER.mkdir(parents=True, exist_ok=True)
    values = dict(GOLDSIGNAL_DEMO_ACCOUNT="1", MARKET_SOURCE="mt5", SIGNAL_REVIEW_MODE="rules",
                  DATABASE_URL="sqlite:///" + (FOLDER / "account.sqlite3").as_posix(), ENTRY_SESSIONS="new_york",
                  SECURE_COOKIE="1", BROKER_ACCOUNT_CURRENCY="USD", BROKER_UNITS_PER_CURRENCY="1",
                  BROKER_CONVERSION="1", BROKER_MARGIN_RATE=str(audit["margin_rate_current"]),
                  BROKER_COMMISSION="0", BROKER_SLIPPAGE="0.10",
                  DEMO_TERMINAL_FINGERPRINT=audit.get("account_fingerprint", ""),
                  BROKER_COSTS_AS_OF=datetime.fromtimestamp(audit["checked_at"], timezone.utc).isoformat())
    os.environ.update(values)
    for name in ("VAPID_PRIVATE_KEY_FILE", "VAPID_PUBLIC_KEY", "VAPID_SUBJECT"):
        if not os.getenv(name):
            raise RuntimeError(f"Existing Web Push configuration required: {name}")
    return audit


def setup():
    import secrets
    from .access import digest
    from .config import NY, utc_now
    from .scalp_grid import configurations, CRITERIA
    from .store import migrate, transaction
    audit = configure()
    migrate()
    secret_path = FOLDER / "access-key.txt"
    if not secret_path.exists():
        secret = "gs_" + secrets.token_urlsafe(24)
        with transaction() as store:
            subject = digest(secret)
            store.put("access_key", subject, dict(id=subject, label="Android demo timing", created=utc_now(), revoked=False))
        secret_path.write_text(secret)
    protocol = FOLDER / "protocol.json"
    if not protocol.exists():
        import hashlib
        configs = configurations()
        start = datetime.fromtimestamp(utc_now(), NY).date()
        if start.isoformat() <= "2026-11-18":
            start = datetime.fromisoformat("2026-11-19").date()
        protocol.write_text(json.dumps(dict(created_at=utc_now(), start=str(start), development_sessions=20,
            validation_sessions=[10, 10], final_sessions=10, configurations=configs, criteria=CRITERIA,
            configuration_sha256=hashlib.sha256(json.dumps(configs, sort_keys=True).encode()).hexdigest(),
            measured_entry_pairs_required=20, measured_session_days_required=3, maximum_clock_uncertainty_seconds=1,
            test_notifications_excluded_from_strategy_delay_fit=True, paid_api_calls=0,
            final_policy="Reserve the next ten admitted sessions after both validation windows; freeze finalists before opening final returns",
            no_retuning=True), indent=2))
    saved = json.loads(protocol.read_text())
    if "account_fingerprint" not in saved:
        saved.update(account_fingerprint=audit.get("account_fingerprint"), broker_company=audit["company"], symbol=audit["symbol"])
        protocol.write_text(json.dumps(saved, indent=2))
    print("Isolated demo configured. Viewer key: " + str(secret_path))


def collect():
    from .config import NY, utc_now
    from .scalp_research import export
    protocol = json.loads((FOLDER / "protocol.json").read_text())
    folder = FOLDER / "archives"
    folder.mkdir(exist_ok=True)
    print(f"Collector armed from {protocol['start']}; archives follow completed New York sessions after 18:00 NY", flush=True)
    while True:
        target = protocol["development_sessions"] + sum(protocol["validation_sessions"]) + protocol["final_sessions"]
        if len(admitted_archives(protocol)) >= target:
            print(f"Collection complete: {target} admitted sessions; final data remains unscored", flush=True)
            return
        now = datetime.fromtimestamp(utc_now(), NY)
        day = datetime.fromisoformat(protocol["start"]).replace(tzinfo=NY)
        while day.date() <= now.date():
            if day.weekday() < 5 and day.replace(hour=18) < now:
                destination = folder / str(day.date())
                if not destination.exists():
                    try:
                        export(SimpleNamespace(start=str(day.date()), until=f"{day.date()}T18:00", commission=0,
                                               slippage=.10, archive=destination))
                        broker_audit = audit_broker()
                        manifest_path = destination / "manifest.json"
                        manifest = json.loads(manifest_path.read_text())
                        manifest["broker_audit"] = broker_audit
                        manifest_path.write_text(json.dumps(manifest, indent=2))
                        if broker_audit.get("account_fingerprint") != protocol.get("account_fingerprint"):
                            print("Collector paused: configured broker account changed", flush=True)
                            return
                        if len(admitted_archives(protocol)) >= target:
                            print(f"Collection complete: {target} admitted sessions; final data remains unscored", flush=True)
                            return
                    except Exception as exc:
                        # Preserve failed partial exports for inspection instead of overwriting broker data.
                        print(f"Collection incomplete {day.date()}: {type(exc).__name__}", flush=True)
            day += timedelta(days=1)
        time.sleep(30)


def admitted_archives(protocol):
    archives = {}
    for path in sorted((FOLDER / "archives").glob("*/manifest.json")):
        manifest = json.loads(path.read_text())
        if (manifest.get("broker_audit", {}).get("account_fingerprint") != protocol.get("account_fingerprint")
                or manifest.get("broker") != protocol.get("broker_company")
                or manifest.get("symbol") != protocol.get("symbol")):
            continue
        for session in manifest["sessions"]:
            if (session["day"] >= protocol["start"] and session["count"] and session["gaps_over_20s"] == 0
                    and session["first"] <= session["opening"] + 20 and session["last"] >= session["cutoff"] - 20):
                previous = archives.get(session["day"])
                if not previous or manifest["archived_at"] > previous[2]["archived_at"]:
                    archives[session["day"]] = (session, path.parent, manifest)
    return [archives[day] for day in sorted(archives)]


def timing_report(output, allowed_days=None):
    from .config import utc_now
    from .store import transaction
    with transaction() as store:
        events = store.all("demo_event")
        submissions = dict(store.items("demo_submit"))
        signals = {item["id"]: item for item in store.all("signal")}
        alerts = {item["id"]: item for item in store.all("alert")}
        calendars = sorted(store.all("demo_calendar"), key=lambda item: item["observed_at"])
        devices = len(store.all("push"))
    from .config import NY
    from .news import restriction
    from .scalp_research import load_ticks, ny_window
    from .strategy import gate
    import bisect
    calendar_times = [row["observed_at"] for row in calendars]
    tick_cache = {}
    grouped = {}
    for event in events:
        grouped.setdefault(event["attempt"], {})[event["stage"]] = event
    pairs, reasons = [], {}
    for attempt, submission in submissions.items():
        stages = grouped.get(attempt, {})
        if submission["kind"] != "ENTRY":
            reasons["test_or_exit_excluded"] = reasons.get("test_or_exit_excluded", 0) + 1
            continue
        if allowed_days is not None and str(datetime.fromtimestamp(submission["submitted_at"], NY).date()) not in allowed_days:
            reasons["outside_development_calibration"] = reasons.get("outside_development_calibration", 0) + 1
            continue
        if not all(name in stages for name in ("push_handled", "notification_click", "server_entry_open", "provider_result")):
            reasons["unopened_or_missing_stage"] = reasons.get("unopened_or_missing_stage", 0) + 1
            continue
        push, click, opened = (stages[name] for name in ("push_handled", "notification_click", "server_entry_open"))
        if not stages["provider_result"].get("accepted") or any(
                row.get("clock_offset") is None or row.get("clock_uncertainty") is None or row["clock_uncertainty"] > 1
                or row.get("clock_calibrated_at") is None or abs(row["clock_calibrated_at"] - row["client_at"]) > 120
                for row in (push, click)):
            reasons["clock_or_provider_quality"] = reasons.get("clock_or_provider_quality", 0) + 1
            continue
        submitted = submission["submitted_at"]
        push_at, click_at = (row["client_at"] + row["clock_offset"] for row in (push, click))
        action_at = opened["check"]["checked_at"]
        submission_event = stages.get("submission", {})
        candidate, eligibility = submission_event.get("candidate", {}), submission_event.get("eligibility", {})
        if not candidate or not eligibility:
            reasons["missing_processing_observation"] = reasons.get("missing_processing_observation", 0) + 1
            continue
        if not candidate["confirmation_at"] <= candidate["detected_at"] <= eligibility["observed_at"] <= submitted:
            reasons["noncausal_processing_order"] = reasons.get("noncausal_processing_order", 0) + 1
            continue
        day = str(datetime.fromtimestamp(submitted, NY).date())
        archive = FOLDER / "archives" / day / f"{day}.ticks.csv.gz"
        if not archive.exists():
            reasons["completed_session_archive_pending"] = reasons.get("completed_session_archive_pending", 0) + 1
            continue
        if day not in tick_cache:
            tick_cache[day] = load_ticks(archive)[0]
        item = signals[alerts[submission["alert"]]["signal"]]
        first_eligible = None
        window = ny_window(candidate["confirmation_at"])
        for tick in tick_cache[day]:
            if tick["time"] < candidate["detected_at"]:
                continue
            if tick["time"] > submitted:
                break
            index = bisect.bisect_right(calendar_times, tick["time"]) - 1
            pause = restriction(calendars[index]["calendar"], tick["time"], False) if index >= 0 else "No observed calendar"
            if gate(item, tick, tick["time"], pause, window=window)[0] == "CONFIRM":
                first_eligible = tick["time"]
                break
        if first_eligible is None:
            reasons["eligible_quote_reconstruction_failed"] = reasons.get("eligible_quote_reconstruction_failed", 0) + 1
            continue
        if not submitted <= push_at <= click_at <= action_at:
            reasons["noncausal_clock_order"] = reasons.get("noncausal_clock_order", 0) + 1
            continue
        pairs.append(dict(attempt=attempt, submitted_at=submitted, push_handled_at=push_at,
                          click_at=click_at, server_opened_at=opened["opened_at"], action_quote_checked_at=action_at,
                          delivery_seconds=push_at - submitted, reaction_seconds=click_at - push_at,
                          post_submission_seconds=action_at - submitted,
                          detection_seconds=candidate["detected_at"] - candidate["confirmation_at"],
                          processing_seconds=submitted - first_eligible,
                          eligible_broker_quote_at=first_eligible,
                          observed_eligibility_to_submission_seconds=submitted - eligibility["observed_at"],
                          valid_at_open=opened["check"]["valid"]))
    days = {str(datetime.fromtimestamp(pair["submitted_at"], NY).date()) for pair in pairs}
    from collections import Counter
    report = dict(generated_at=utc_now(), pairs=pairs, paired_count=len(pairs), session_days=len(days), excluded=reasons,
                  observed_stage_counts=dict(Counter(event["stage"] for event in events)),
                  enrolled_devices=devices, collected_session_archives=len(list((FOLDER / "archives").glob("*/manifest.json"))),
                  usable_for_grid=len(pairs) >= 20 and len(days) >= 3,
                  calibration_days=sorted(allowed_days) if allowed_days is not None else None,
                  device="Android Chrome/PWA", limitations=["Push handler is not OS display receipt", "Client clock uncertainty and drift remain", "Entry-open includes page launch/network/check time"])
    with Path(output).open("x") as file:
        json.dump(report, file, indent=2)
    print(f"Real paired ENTRY samples: {len(pairs)} across {len(days)} days; ready={report['usable_for_grid']}")


def rerun(output):
    from .scalp_grid import run
    protocol = json.loads((FOLDER / "protocol.json").read_text())
    archives = admitted_archives(protocol)
    allowed_days = {row[0]["day"] for row in archives[:protocol["development_sessions"]]}
    timing_path = FOLDER / "frozen-timing.json"
    if not timing_path.exists():
        candidate_path = FOLDER / f"timing-{time.time_ns()}.json"
        timing_report(candidate_path, allowed_days)
        measured = json.loads(candidate_path.read_text())
        if measured["usable_for_grid"]:
            with timing_path.open("x") as frozen:
                json.dump(measured, frozen, indent=2)
        else:
            raise RuntimeError("Waiting for 20 genuine paired development ENTRY opens across three New York sessions; no assumed delays substituted")
    timing = json.loads(timing_path.read_text())
    from .config import NY
    if any(str(datetime.fromtimestamp(pair["submitted_at"], NY).date()) not in allowed_days for pair in timing["pairs"]):
        raise RuntimeError("Development admission roster changed after timing freeze; do not refit on validation or final data")
    needed = protocol["development_sessions"] + sum(protocol["validation_sessions"])
    if len({row[0]["day"] for row in archives}) < needed:
        raise RuntimeError(f"Waiting for {needed} admitted new sessions; have {len(archives)}. Final-period data remains reserved")
    chosen = archives[:needed]
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    dataset = output / "dataset"
    dataset.mkdir()
    frames = {}
    events = []
    for session, folder, manifest in chosen:
        os.link(folder / f"{session['day']}.ticks.csv.gz", dataset / f"{session['day']}.ticks.csv.gz")
        for frame, rows in json.loads((folder / "candles.json").read_text()).items():
            frames.setdefault(frame, {}).update({row["time"]: row for row in rows})
    from .store import transaction
    from .config import NEWS_AFTER, NEWS_BEFORE, utc_now
    with transaction() as store:
        snapshots = sorted(store.all("demo_calendar"), key=lambda row: row["observed_at"])
    for index, snapshot in enumerate(snapshots):
        lower = snapshot["observed_at"]
        if lower > chosen[-1][0]["requested_until"]:
            break
        upper = snapshots[index + 1]["observed_at"] if index + 1 < len(snapshots) else utc_now()
        for event in snapshot["calendar"].get("events", []):
            if event["time"] + NEWS_AFTER >= lower and event["time"] - NEWS_BEFORE < upper:
                events.append({**event, "observed_from": lower, "observed_until": upper})
    manifest = {**chosen[0][2], "sessions": [row[0] for row in chosen],
                "until": chosen[-1][2]["until"], "calendar": {"events": events, "point_in_time_observations": True},
                "final_period_excluded": True}
    (dataset / "manifest.json").write_text(json.dumps(manifest))
    (dataset / "candles.json").write_text(json.dumps({frame: [rows[t] for t in sorted(rows)] for frame, rows in frames.items()}))
    run(SimpleNamespace(archive=dataset, output=output / "grid", limit=960, study=FOLDER / "protocol.json", timing=timing_path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("audit", "setup", "serve", "worker", "collect", "timing", "rerun"))
    parser.add_argument("--output")
    options = parser.parse_args()
    if options.action == "audit":
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        audit_broker()
        return
    configure()
    if options.action == "setup":
        setup()
    elif options.action == "serve":
        import uvicorn
        uvicorn.run("goldsignal.api:app", host="127.0.0.1", port=8012, log_level="warning")
    elif options.action == "worker":
        from .worker import run
        run()
    elif options.action == "collect":
        collect()
    elif options.action == "timing":
        timing_report(options.output or FOLDER / f"timing-{int(time.time())}.json")
    else:
        try:
            rerun(options.output or FOLDER / "prospective-run")
        except RuntimeError as exc:
            parser.exit(2, f"Study not ready: {exc}\n")


if __name__ == "__main__":
    main()
