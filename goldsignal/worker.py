import hashlib
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from filelock import FileLock

from . import news
from .access import MODEL, encryption
from .alerts import add_alert, send_pending
from .config import DB, ENTRY_TTL, MODE, REVIEW, SYMBOL, session, utc_now
from .lifecycle import advance
from .market import MT5, Replay
from .store import migrate, transaction
from .strategy import gate, levels, setup

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


def gemini_review(settings, candidate, snapshot, calendar):
    day = datetime.now(timezone.utc).date().isoformat()
    with transaction() as store:
        usage = store.get("ai_usage", "gemini", {})
        used = usage.get("count", 0) if usage.get("day") == day else 0
        if used >= 6:
            return "WAIT", "Gemini daily review limit reached"
        store.put("ai_usage", "gemini", {"day": day, "count": used + 1})
    try:
        key = encryption().decrypt(settings["ciphertext"].encode()).decode()
        setup_data = candidate["evidence"]
        candle = setup_data["candle"]
        evidence = {
            "side": candidate["direction"], "ref": candidate["reference"],
            "entry": candidate["entry"], "stop": candidate["initial_stop"], "targets": candidate["targets"],
            "swing": setup_data["swing"]["low" if candidate["direction"] == "BUY" else "high"],
            "body": round(candle["close"] - candle["open"], 2),
            "trend_delta": [round(series[-1] - series[0], 2) for series in setup_data["trend_closes"].values()],
            "pattern": setup_data["pattern"],
            "spread": round(snapshot["quote"]["ask"] - snapshot["quote"]["bid"], 2),
        }
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": key}, timeout=8,
            json={"contents": [{"parts": [{"text": (
                'Review one XAUUSD entry. Keep supplied side and levels. Trends M15/M30/H1. '
                'Next4 is historical return in side direction (bps), not a forecast. '
                'CONFIRM coherent evidence, WAIT uncertainty, REJECT contradiction. Reason max 12 words. '
                + json.dumps(evidence, separators=(",", ":"))
            )}]}], "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 96,
                                        "responseSchema": {"type": "OBJECT", "required": ["decision", "reason"],
                                            "properties": {"decision": {"type": "STRING", "enum": ["CONFIRM", "WAIT", "REJECT"]},
                                                           "reason": {"type": "STRING"}}},
                                        "thinkingConfig": {"thinkingBudget": 0}}},
        )
        response.raise_for_status()
        result = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        reason = result["reason"]
        if result["decision"] not in ("CONFIRM", "WAIT", "REJECT") or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Invalid Gemini decision")
        return result["decision"], " ".join(reason.split()[:12])[:160]
    except Exception as exc:
        log.warning("Gemini review unavailable (%s)", type(exc).__name__)
        return "WAIT", "Gemini review unavailable"


def new_candidate(snapshot):
    now, bars = snapshot["now"], snapshot["bars"]
    scan = snapshot["scan"] = {}
    if snapshot["closed"] or not session(now)["open"]:
        scan["reason"] = "Watching the feed. Entries are outside broker or session hours."
        return None
    evidence = setup(bars, now, scan)
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
    add_alert(store, "shared", signal, name, ts)
    for recipient, subscription in store.items("push"):
        if subscription:
            add_alert(store, recipient, signal, name, ts)


def process(source, step, cursor, calendar, revision):
    snapshot = source.read(cursor, step, utc_now())
    now = snapshot["now"]
    if DEMO:
        calendar = news.refresh(True, now, calendar)
    candidate = new_candidate(snapshot)
    scan = snapshot.get("scan", {})
    model = None
    configured = False
    review_provider = "rules"
    if candidate:
        with transaction() as store:
            gemini = store.get("ai", "gemini", {})
            configured = gemini.get("enabled")
            published = store.get("signal", candidate["id"]) if configured or REVIEW != "rules" else None
            prior = store.get("candidate", candidate["id"]) if configured or REVIEW != "rules" else None
        if configured or REVIEW != "rules":
            review_provider = "gemini" if configured else REVIEW
            model = prior.get("model") if prior and prior.get("review_provider", REVIEW) == review_provider else None
            pause = news.restriction(calendar, now, DEMO) if configured else None
            if not published and not model and gate(candidate, snapshot["quote"], now, pause)[0] == "CONFIRM":
                model = (gemini_review(gemini, candidate, snapshot, calendar) if configured
                         else model_review(candidate, snapshot, calendar))
                if not DEMO:
                    snapshot = source.read(cursor, step, utc_now())
    review_gate = model or (("WAIT", "Waiting for Gemini review") if configured else None)
    with transaction() as store:
        track(store, "signal", snapshot, calendar)
        track(store, "shadow", snapshot, calendar)
        now = snapshot["now"] if DEMO else utc_now()
        quote = snapshot["quote"]
        if candidate and not store.get("signal", candidate["id"]):
            decision, reason = evaluate(candidate, quote, now, calendar, review_gate)
            baseline, baseline_reason = gate(candidate, quote, now)
            key = candidate["id"]
            evidence = store.get("candidate", key, {})
            first = evidence.get("first", dict(time=now, quote=quote, calendar=calendar, result=decision, reason=reason))
            store.put("candidate", key, {**candidate, "first": first, "evaluated": now, "decision": decision,
                                        "reason": reason, "quote": quote, "calendar_sources": calendar.get("sources", {}),
                                        "calendar_reason": news.restriction(calendar, now, DEMO),
                                        "baseline": baseline, "baseline_reason": baseline_reason, "model": model,
                                        "review_provider": review_provider})
            if baseline == "CONFIRM" and (not model or model[0] == "CONFIRM") and not store.get("shadow", key):
                store.put("shadow", key, dict(candidate, exits=[], created=now))
            if decision == "CONFIRM":
                now = snapshot["now"] if DEMO else utc_now()
                if evaluate(candidate, quote, now, calendar, review_gate)[0] == "CONFIRM":
                    candidate.update(created=now)
                    if model:
                        candidate["review"] = {"provider": review_provider, "reason": model[1]}
                    store.put("signal", key, candidate)
                    record_event(store, candidate, "ENTRY", now)
        store.save_bars(snapshot["bars"], revision)
        for frame, bars in snapshot.get("frames", {}).items():
            store.save_bars(bars, revision, frame)
        store.put("state", "market", dict(now=snapshot["now"], quote=quote, spec=snapshot["spec"],
                  closed=snapshot["closed"], cursor=snapshot["cursor"], step=step + 1,
                  revision=revision, heartbeat=utc_now(), calendar=calendar, scan=scan, error=None))
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
            time.sleep(max(0.1, (float(os.getenv("REPLAY_STEP_SECONDS", "5")) if DEMO else 1) -
                           (time.monotonic() - cycle)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    name = hashlib.sha256(f"{DB}:{MODE}:{SYMBOL}".encode()).hexdigest()[:12]
    with FileLock(Path(f".worker-{name}.lock"), timeout=0):
        run()
