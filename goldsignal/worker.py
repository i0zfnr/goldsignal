import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from filelock import FileLock

from . import news
from .alerts import add_alert, send_pending
from .config import DB, ENTRY_TTL, MODE, REVIEW, SYMBOL, session, utc_now
from .lifecycle import advance, realized
from .market import MT5, Replay, demo_profile
from .store import migrate, transaction
from .strategy import account_fit, gate, levels, setup

log = logging.getLogger(__name__)
DEMO = MODE == "demo"


def evaluate(signal, quote, now, calendar, model=None):
    calendar_reason = news.restriction(calendar, now, DEMO)
    result, reason = gate(signal, quote, now, calendar_reason)
    if result == "CONFIRM" and model and model[0] != "CONFIRM":
        return model
    return result, reason


def model_review(candidate, snapshot, calendar):
    if REVIEW == "rules":
        return None
    if REVIEW != "ollama":
        return "WAIT", "Unknown review mode"
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    if urlsplit(base).hostname not in ("127.0.0.1", "localhost", "::1"):
        return "WAIT", "Ollama URL must be local"
    try:
        evidence = dict(setup=candidate["evidence"], quote=snapshot["quote"],
                        upcoming=[item for item in calendar["events"] if item["time"] >= snapshot["now"]][:3])
        response = httpx.post(f"{base.rstrip('/')}/api/generate", timeout=8, json={
            "model": os.getenv("OLLAMA_MODEL", "qwen2.5:3b"), "stream": False, "format": "json",
            "prompt": "Review this setup conservatively. Reply with JSON keys decision (CONFIRM, WAIT, REJECT) "
                      "and reason (short string). You cannot override execution rules. Data: " + json.dumps(evidence),
        })
        response.raise_for_status()
        result = json.loads(response.json()["response"])
        if result["decision"] not in ("CONFIRM", "WAIT", "REJECT") or not isinstance(result["reason"], str):
            raise ValueError("Invalid review response")
        return result["decision"], result["reason"][:300]
    except Exception as exc:
        log.warning("Local model review failed: %s", exc)
        return "WAIT", "Local model review unavailable"


def new_candidate(snapshot):
    now, bars = snapshot["now"], snapshot["bars"]
    if snapshot["closed"] or not session(now)["open"]:
        return None
    evidence = setup(bars, now)
    if not evidence:
        return None
    candle = evidence["candle"]
    if now - candle["time"] - 900 >= ENTRY_TTL:
        return None
    signal_id = str(candle["time"]) + evidence["direction"][0]
    return dict(id=signal_id, symbol=SYMBOL, **levels(evidence["direction"], candle["close"]),
                direction=evidence["direction"], evidence=evidence, created=now,
                expiry=min(session(now)["cutoff"], candle["time"] + 900 + ENTRY_TTL, now + ENTRY_TTL),
                hits=0, exits=[], status="PENDING", fill=None,
                result_per_lot=0 if snapshot["spec"] else None, costs=snapshot["spec"])


def track(store, kind, snapshot, calendar):
    now, ticks = snapshot["now"], snapshot["ticks"]
    for signal in store.all(kind):
        if signal["status"] not in ("PENDING", "FILLED"):
            continue
        if not ticks and signal["status"] == "FILLED":
            continue
        for quote in [*ticks, None]:
            ts = quote["time"] if quote else now
            if ts < signal["created"] or (quote and ts < signal.get("last_tick", 0)):
                continue
            pause = None if kind == "shadow" else news.restriction(calendar, ts, DEMO)
            open_now = bool(quote and gate(signal, quote, ts, pause)[0] == "CONFIRM")
            events = advance(signal, quote, ts, open_now, signal["costs"])
            if quote:
                signal["last_tick"] = ts
            if kind == "signal":
                for name, stop in events:
                    record_event(store, {**signal, "stop": stop}, name, ts)
            if signal["status"] not in ("PENDING", "FILLED"):
                break
        store.put(kind, signal["id"], signal)


def record_event(store, signal, name, ts):
    key = f"{signal['id']}:{name}"
    if store.get("event", key):
        return
    note = "Stop moved to reference" if name == "TP1" and signal["fill"] != signal["reference"] else None
    store.put("event", key, dict(id=key, signal=signal["id"], kind=name, time=ts,
                                 fill=signal["fill"], stop=signal["stop"], note=note))
    for profile_id, entry in signal["eligible"].items():
        if entry["policy"] == "single" and (name in ("TP2", "TP3") or
                                           (signal["hits"] and name in ("STOPPED", "TIMED_OUT"))):
            continue
        add_alert(store, profile_id, signal, name, ts)


def process(source, step, cursor, calendar, revision):
    snapshot = source.read(cursor, step, utc_now())
    now = snapshot["now"]
    if DEMO:
        calendar = news.refresh(True, now, calendar)
    candidate = new_candidate(snapshot)
    model = None
    if candidate and REVIEW != "rules":
        with transaction() as store:
            published = store.get("signal", candidate["id"])
            prior = store.get("candidate", candidate["id"])
        model = prior.get("model") if prior else None
        if not published and not model and gate(candidate, snapshot["quote"], now)[0] == "CONFIRM":
            model = model_review(candidate, snapshot, calendar)
            if not DEMO:
                snapshot = source.read(cursor, step, utc_now())
    with transaction() as store:
        track(store, "signal", snapshot, calendar)
        track(store, "shadow", snapshot, calendar)
        now = snapshot["now"] if DEMO else utc_now()
        quote = snapshot["quote"]
        if candidate and not store.get("signal", candidate["id"]):
            decision, reason = evaluate(candidate, quote, now, calendar, model)
            baseline, baseline_reason = gate(candidate, quote, now)
            key = candidate["id"]
            evidence = store.get("candidate", key, {})
            first = evidence.get("first", dict(time=now, quote=quote, calendar=calendar, result=decision, reason=reason))
            store.put("candidate", key, {**candidate, "first": first, "evaluated": now, "decision": decision,
                                        "reason": reason, "quote": quote, "calendar_sources": calendar.get("sources", {}),
                                        "calendar_reason": news.restriction(calendar, now, DEMO),
                                        "baseline": baseline, "baseline_reason": baseline_reason, "model": model})
            if baseline == "CONFIRM" and (not model or model[0] == "CONFIRM") and not store.get("shadow", key):
                store.put("shadow", key, dict(candidate, exits=[], created=now))
            if decision == "CONFIRM":
                eligible = {}
                profiles = store.all("profile")
                if DEMO:
                    profiles.append({"id": "demo", **demo_profile(utc_now())})
                for profile in profiles:
                    profile_id = profile["id"]
                    fit = account_fit(candidate, profile, snapshot["spec"], now,
                                      realized(store, profile_id, now, profile["currency"], profile["units_per_currency"]),
                                      profile_now=utc_now())
                    if fit["decision"] == "FIT":
                        eligible[profile_id] = dict(fit=fit, step=snapshot["spec"]["step"], policy=profile["exit_policy"],
                                                    units=profile["units_per_currency"])
                now = snapshot["now"] if DEMO else utc_now()
                if evaluate(candidate, quote, now, calendar, model)[0] == "CONFIRM":
                    candidate.update(created=now, eligible=eligible)
                    store.put("signal", key, candidate)
                    record_event(store, candidate, "ENTRY", now)
        store.save_bars(snapshot["bars"], revision)
        store.put("state", "market", dict(now=snapshot["now"], quote=quote, spec=snapshot["spec"],
                  closed=snapshot["closed"], cursor=snapshot["cursor"], step=step + 1,
                  revision=revision, heartbeat=utc_now(), calendar=calendar, error=None))
    return snapshot


def run():
    if MODE not in ("demo", "mt5"):
        raise ValueError("MARKET_SOURCE must be demo or mt5")
    migrate()
    source = Replay() if DEMO else MT5()
    with transaction() as store:
        state = store.get("state", "market", {})
    step, cursor, revision = state.get("step", 0), state.get("cursor"), state.get("revision", 0)
    calendar = state.get("calendar", {})
    with ThreadPoolExecutor(max_workers=2) as background:
        refresh_job = push_job = None
        log.info("Worker running, source=%s, symbol=%s", MODE, SYMBOL)
        while True:
            cycle = time.monotonic()
            try:
                if refresh_job and refresh_job.done():
                    calendar = refresh_job.result()
                    refresh_job = None
                if not DEMO and refresh_job is None and utc_now() - calendar.get("refreshed", 0) > 300:
                    refresh_job = background.submit(news.refresh, False, utc_now(), calendar)
                snapshot = process(source, step, cursor, calendar, revision + 1)
                step, cursor, revision = step + 1, snapshot["cursor"], revision + 1
                if push_job is None or push_job.done():
                    if push_job:
                        push_job.result()
                    push_job = background.submit(send_pending, snapshot["now"])
            except Exception:
                log.exception("Worker cycle failed")
                with transaction() as store:
                    prior = store.get("state", "market", {})
                    clock = utc_now()
                    if not DEMO:
                        unavailable = {"now": clock, "ticks": []}
                        track(store, "signal", unavailable, calendar)
                        track(store, "shadow", unavailable, calendar)
                    store.put("state", "market", {**prior, "heartbeat": clock, "error": "Market worker cycle failed"})
            time.sleep(max(0.1, (float(os.getenv("REPLAY_STEP_SECONDS", "5")) if DEMO else 2) -
                           (time.monotonic() - cycle)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    name = hashlib.sha256(f"{DB}:{MODE}:{SYMBOL}".encode()).hexdigest()[:12]
    with FileLock(Path(f".worker-{name}.lock"), timeout=0):
        run()
