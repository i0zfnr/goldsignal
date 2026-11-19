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
from .access import MODEL, PRO_MODEL, encryption
from .alerts import add_alert, send_pending
from .config import DB, ENTRY_TTL, MODE, REVIEW, STRATEGY_B_MTF, STRATEGY_B_VERSION, SYMBOL, session, utc_now
from .diagnostics import record
from .gemini_budget import GeminiPaused, pause_after_429, reserve
from .lifecycle import advance
from .market import MT5, Replay
from .range_fade import asian_range_candidate
from .scalp import scalp_candidate
from .scalp_v2 import analyze as analyze_v2
from .sessions import label as session_label
from .store import migrate, transaction
from .strategy import gate, levels, setup
from .telegram import format_entry, format_event, format_headsup, send_telegram
from .workers import blank as blank_workers, mark as mark_worker, mark_lane as mark_lane_worker
from . import demo_account

log = logging.getLogger(__name__)
DEMO = MODE == "demo"
GEMINI_RETRY_DELAYS = (3, 8)
ENTRY_LIMIT_PER_HOUR = 2
ENTRY_LIMIT_REASON = "Entry limit reached (2 signals per rolling hour)."


def failure_message(exc):
    message = str(exc).splitlines()[0] if str(exc) else ""
    if isinstance(exc, RuntimeError) and message.startswith(("MT5 ", "Demo feed account changed")):
        return f"Worker cycle failed: {type(exc).__name__}: {message}"[:300]
    return f"Worker cycle failed: {type(exc).__name__}. See the local worker log."


class GeminiTemporaryError(Exception):
    pass


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
        record("Ollama review", "Local model review failed.")
        return "WAIT", "Local model review unavailable"


def gemini_review(settings, candidate, snapshot, calendar, retrying=False):
    try:
        key = encryption().decrypt(settings["ciphertext"].encode()).decode()
        setup_data = candidate["evidence"]
        candle = setup_data.get("trigger", setup_data["candle"])
        evidence = {
            "side": candidate["direction"], "ref": candidate["reference"],
            "setup_type": "M5 breakout, M1 retest, M15 trend" if candidate.get("strategy") else "M15 rejection, M15/M30/H1 trend",
            "entry": candidate["entry"], "stop": candidate["initial_stop"], "targets": candidate["targets"],
            "swing": setup_data["swing"]["low" if candidate["direction"] == "BUY" else "high"],
            "body": round(candle["close"] - candle["open"], 2),
            "trend_delta": [round(series[-1] - series[0], 2) for series in setup_data["trend_closes"].values()],
            "pattern": setup_data["pattern"],
            "spread": round(snapshot["quote"]["ask"] - snapshot["quote"]["bid"], 2),
        }
        watch_event = news.nearby_watch_event(calendar, snapshot["now"])
        if watch_event:
            evidence["usd_release_offset_min"] = round((watch_event["time"] - snapshot["now"]) / 60)
        calendar_rule = " A nearby USD release adds timing risk only." if watch_event else ""
        reserve(MODEL)
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": key}, timeout=3.8,
            json={"contents": [{"parts": [{"text": (
                'Role: fast deterministic entry reviewer. Confirm only if side, entry, stop, targets are consistent. '
                'Output JSON only with keys decision (CONFIRM, WAIT, REJECT) and reason (max 10 words).'
                + calendar_rule + " Evidence: " + json.dumps(evidence, separators=(",", ":"))
            )}]}], "generationConfig": {"responseMimeType": "application/json",
                                        "temperature": 0,
                                        "topP": 0.1,
                                        "maxOutputTokens": 64,
                                        "responseSchema": {"type": "OBJECT", "required": ["decision", "reason"],
                                            "properties": {"decision": {"type": "STRING", "enum": ["CONFIRM", "WAIT", "REJECT"]},
                                                           "reason": {"type": "STRING"}}},
                                        "thinkingConfig": {"thinkingLevel": "minimal"}}},
        )
        response.raise_for_status()
        result = json.loads(response.json()["candidates"][0]["content"]["parts"][0]["text"])
        reason = result["reason"]
        if result["decision"] not in ("CONFIRM", "WAIT", "REJECT") or not isinstance(reason, str) or not reason.strip():
            raise ValueError("Invalid Gemini decision")
        if retrying:
            record("Gemini review", f"Retry returned a valid review ({result['decision']}).", level="info")
        return result["decision"], " ".join(reason.split()[:12])[:160]
    except GeminiPaused:
        raise
    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        problem = f"HTTP {status}" if status is not None else "connection failed"
        if status == 429:
            record("Gemini review", "Review failed (HTTP 429). Gemini calls paused.")
            until = pause_after_429(exc.response)
            raise GeminiPaused("Google returned HTTP 429. Gemini calls are paused.", until) from exc
        if status in (None, 500, 502, 503, 504):
            log.warning("Gemini temporarily unavailable (%s)", problem)
            raise GeminiTemporaryError(problem) from exc
        log.warning("Gemini review unavailable (%s)", problem)
        record("Gemini review", f"Review failed ({problem}).")
        return "WAIT", "Gemini review unavailable"
    except Exception as exc:
        log.warning("Gemini review unavailable (%s)", type(exc).__name__)
        record("Gemini review", "Could not prepare or read a valid review.")
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


def track(store, kind, snapshot, calendar, stopped=False):
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
            open_now = bool(not stopped and quote and gate(signal, quote, ts, pause)[0] == "CONFIRM")
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
    if name != "ENTRY":
        send_telegram(format_event(signal, name, ts))


def process(source, step, cursor, calendar, revision):
    cycle_start = time.perf_counter()
    snapshot = source.read(cursor, step, utc_now())
    if demo_account.enabled():
        import hashlib
        account = source.mt5.account_info()
        fingerprint = hashlib.sha256(f"{account.login}:{account.server}".encode()).hexdigest() if account else None
        if not account or account.trade_mode != 0 or fingerprint != os.getenv("DEMO_TERMINAL_FINGERPRINT"):
            raise RuntimeError("Demo feed account changed; paper tracking paused")
    now = snapshot["now"]
    if DEMO:
        calendar = news.refresh(True, now, calendar)
    workers = blank_workers()
    mark_worker(workers, "running", at=now)
    candidate = new_candidate(snapshot)
    scan = snapshot.get("scan", {})
    frames = snapshot.get("frames", {})
    b_analysis = None
    scalp = None
    scalp_scan = "Waiting for the M5 and M1 feed."
    with transaction() as store:
        gemini = store.get("ai", "gemini", {})
        if demo_account.enabled():
            gemini = {}
        stopped = news.manual_pause(store, utc_now())
        if demo_account.enabled():
            demo_account.track(store, snapshot)
            calendar_id = str(calendar.get("refreshed", "initial"))
            if not store.get("demo_calendar", calendar_id):
                store.put("demo_calendar", calendar_id, dict(observed_at=utc_now(), calendar=calendar))
        if "M5" in frames and "M1" in frames:
            def recent(frame, limit=12):
                bars = {bar["time"]: bar for bar in store.chart(frame=frame, limit=limit)}
                bars.update({bar["time"]: bar for bar in frames.get(frame, [])})
                return [bars[time] for time in sorted(bars)[-limit:]]
            m5_recent = recent("M5", 250)
            if STRATEGY_B_VERSION == "katana_v1" and "H1" in frames:
                b_settings = store.get("settings", "strategy_b") or {}
                b_mtf = b_settings.get("mtf") or STRATEGY_B_MTF
                b_frames = {f: recent(f, 250) for f in ("M1", "M5", "M30", "H1")}
                b_bars_dict = {b["time"]: b for b in store.chart(limit=250)}
                b_bars_dict.update({b["time"]: b for b in snapshot.get("bars", [])})
                b_bars = [b_bars_dict[t] for t in sorted(b_bars_dict)[-250:]]
                b_snapshot = {**snapshot, "bars": b_bars, "frames": b_frames}
                b_analysis = analyze_v2(b_snapshot, mtf=b_mtf)
                scalp = b_analysis.get("candidate")
                scalp_scan = b_analysis.get("reason") or "Waiting for setup"
            else:
                scalp, scalp_scan = scalp_candidate(snapshot, recent("M5", 12), recent("M1", 12))
        mark_lane_worker(workers, "A", "kaze", "setup" if candidate else "waiting",
                         reason=scan.get("reason"), at=now)
        mark_lane_worker(workers, "B", "kaze", "setup" if scalp else "waiting",
                         reason=scalp_scan, at=now)

        # Strategy C: Asian Range Fade
        range_cand = None
        range_scan = "Waiting for Asian session window."
        if "M5" in frames and "M1" in frames:
            range_cand, range_scan = asian_range_candidate(snapshot, m5_recent, snapshot.get("bars", []))
        mark_lane_worker(workers, "C", "kaze", "setup" if range_cand else "waiting",
                         reason=range_scan, at=now)

        # Early Heads-up when M5 rejection occurs before M1 confirmation:
        if b_analysis and b_analysis.get("rejection") and b_analysis.get("next_step") == "WAITING FOR M1 CONFIRMATION":
            rej = b_analysis["rejection"]
            zone = b_analysis.get("zone", {})
            headsup_key = f"headsup:{zone.get('id', 'z')}:{rej['time']}"
            if not store.get("alert", headsup_key):
                store.put("alert", headsup_key, dict(
                    id=headsup_key, profile="shared", signal=None, kind="HEADS_UP", time=now,
                    valid_until=now + 300,
                    title=f"XAUUSD {zone.get('direction', '')} · Heads-up (M5 Rejection)",
                    body=f"M5 closed outside zone {zone.get('bottom', 0):.2f}–{zone.get('top', 0):.2f}. Waiting for M1 confirmation break.",
                    url="/#signal", delivery="sent", attempts=1,
                ))
                send_telegram(format_headsup(zone.get("direction", "SELL"), zone, rej, now))

        pending = [item for item in (candidate, scalp, range_cand) if item and not store.get("signal", item["id"])]
        for item in pending:
            item.setdefault("session", session_label(snapshot["now"]))
            lane = "C" if item.get("id", "").startswith("c_") else ("B" if item.get("strategy") else "A")
            item.setdefault("lane", lane)
        if demo_account.enabled():
            for item in pending:
                if item.get("strategy") and not store.get("demo_candidate", item["id"]):
                    store.put("demo_candidate", item["id"], dict(detected_at=utc_now(),
                              confirmation_at=item["evidence"]["trigger"]["time"] + 60))
        previous = {item["id"]: store.get("candidate", item["id"]) for item in pending}
        recent_entries = [signal["created"] for signal in store.all("signal")
                          if signal["created"] > now - 3600] if pending else []
    configured = gemini.get("enabled")
    provider = "gemini" if configured else REVIEW
    reviews = {}
    retries = {}
    reviewed = False
    model = None
    for item in pending:
        prior = previous[item["id"]]
        same_provider = prior and prior.get("review_provider", REVIEW) == provider
        model = prior.get("model") if same_provider else None
        retry = prior.get("gemini_retry") if same_provider and configured else None
        pause = news.restriction(calendar, now, DEMO) if configured else None
        if (not stopped and len(recent_entries) < ENTRY_LIMIT_PER_HOUR
                and (not model or (retry and now >= retry["after"])) and provider != "rules"
                and gate(item, snapshot["quote"], now, pause)[0] == "CONFIRM"):
            try:
                model = (gemini_review(gemini, item, snapshot, calendar,
                                       retrying=bool(retry and retry["failures"])) if configured else
                         model_review(item, snapshot, calendar))
                retry = None
            except GeminiPaused as exc:
                after = now + max(1, exc.resume_at - utc_now())
                retry = {"failures": retry["failures"] if retry else 0, "after": after} if after < item["expiry"] else None
                model = "WAIT", str(exc)
            except GeminiTemporaryError as exc:
                failures = retry["failures"] + 1 if retry else 1
                clock = snapshot["now"] if DEMO else utc_now()
                after = clock + GEMINI_RETRY_DELAYS[failures - 1] if failures <= len(GEMINI_RETRY_DELAYS) else None
                retry = {"failures": failures, "after": after} if after is not None and after < item["expiry"] else None
                outcome = "Retry scheduled." if retry else "No retry remains for this entry."
                record("Gemini review", f"Attempt {failures} failed ({exc}). {outcome}",
                       level="info" if retry else "error")
                model = ("WAIT", "Gemini temporarily unavailable. Retry scheduled." if retry else
                         "Gemini unavailable. No retry remains for this entry.")
            reviewed = True
        reviews[item["id"]] = model
        retries[item["id"]] = retry
        mark_lane_worker(workers, item.get("lane", "A"), "nanao",
                         "disabled" if provider == "rules" else (model[0] if model else "waiting"),
                         reason="Rules-only review" if provider == "rules" else (
                             model[1] if model else "Waiting for review"), at=now)
    if b_analysis and b_analysis.get("next_step") == "WAITING FOR M1 CONFIRMATION":
        mark_lane_worker(workers, "B", "nanao", "waiting",
                         reason="Pre-warming AI review for zone rejection...", at=now)
    if reviewed and not DEMO:
        snapshot = source.read(cursor, step, utc_now())
    with transaction() as store:
        stopped = news.manual_pause(store, utc_now())
        track(store, "signal", snapshot, calendar, stopped)
        track(store, "shadow", snapshot, calendar, stopped)
        now = snapshot["now"] if DEMO else utc_now()
        quote = snapshot["quote"]
        if stopped:
            scan["reason"] = "New entries paused by admin."
            scalp_scan = scan["reason"]
        for item in pending:
            key = item["id"]
            model = reviews[key]
            review_gate = model or (("WAIT", "Waiting for Gemini review") if configured else None)
            decision, reason = (("WAIT", scan["reason"]) if stopped else
                                evaluate(item, quote, now, calendar, review_gate))
            baseline, baseline_reason = gate(item, quote, now)
            if demo_account.enabled() and baseline == "CONFIRM" and not store.get("demo_eligible", key):
                store.put("demo_eligible", key, dict(observed_at=utc_now(), quote_time=quote["time"]))
            capped = sum(stamp > now - 3600 for stamp in recent_entries) >= ENTRY_LIMIT_PER_HOUR
            if not stopped and capped and baseline == "CONFIRM":
                decision, reason = "WAIT", ENTRY_LIMIT_REASON
            evidence = previous[key] or {}
            first = evidence.get("first", dict(time=now, quote=quote, calendar=calendar, result=decision, reason=reason))
            store.put("candidate", key, {**item, "first": first, "evaluated": now, "decision": decision,
                                        "reason": reason, "quote": quote, "calendar_sources": calendar.get("sources", {}),
                                        "calendar_reason": news.restriction(calendar, now, DEMO),
                                        "baseline": baseline, "baseline_reason": baseline_reason, "model": model,
                                        "review_provider": provider, "gemini_retry": retries[key]})
            if item.get("strategy"):
                scalp_scan = f"{decision}: {reason}"
            mark_lane_worker(workers, item.get("lane", "A"), "mizu", decision, reason=reason, at=now)
            if not stopped and baseline == "CONFIRM" and (not model or model[0] == "CONFIRM") and not store.get("shadow", key):
                store.put("shadow", key, dict(item, exits=[], created=now))
            if decision == "CONFIRM":
                publish_time = snapshot["now"] if DEMO else utc_now()
                if evaluate(item, quote, publish_time, calendar, review_gate)[0] == "CONFIRM":
                    item.update(created=publish_time)
                    if model:
                        item["review"] = {"provider": provider, "reason": model[1]}
                    store.put("signal", key, item)
                    recent_entries.append(publish_time)
                    record_event(store, item, "ENTRY", publish_time)
                    send_telegram(format_entry(item, publish_time))
                    mark_lane_worker(workers, item.get("lane", "A"), "hikari", "published",
                                     reason=f"{item['direction']} {key}", at=now)
                    if item.get("strategy"):
                        scalp_scan = f"{item['direction']} scalp signal published."
        store.save_bars(snapshot["bars"], revision)
        for frame, bars in snapshot.get("frames", {}).items():
            store.save_bars(bars, revision, frame)
        for lane in ("A", "B", "C"):
            for stage in ("mizu", "nanao", "hikari"):
                if workers["lanes"][lane]["stages"][stage]["status"] == "idle":
                    mark_lane_worker(workers, lane, stage, "waiting", reason="No candidate", at=now)
        latency_ms = round((time.perf_counter() - cycle_start) * 1000, 1)
        feed_reason = f"Feed {'live' if not snapshot.get('closed') else 'closed'} · {latency_ms}ms"
        mark_worker(workers, "idle", reason=feed_reason, at=now)
        state_payload = dict(now=snapshot["now"], quote=quote, spec=snapshot["spec"],
                  closed=snapshot["closed"], cursor=snapshot["cursor"], step=step + 1,
                  revision=revision, heartbeat=utc_now(), calendar=calendar, scan=scan, scalp_scan=scalp_scan,
                  workers=workers, latency_ms=latency_ms, error=None)
        if b_analysis:
            state_payload["b_analysis"] = b_analysis
        store.put("state", "market", state_payload)
    return snapshot


def run():
    demo_account.assert_isolated()
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
            except Exception as exc:
                log.exception("Worker cycle failed")
                record("Market worker", failure_message(exc))
                with transaction() as store:
                    prior = store.get("state", "market", {})
                    clock = utc_now()
                    if not DEMO:
                        unavailable = {"now": clock, "ticks": []}
                        track(store, "signal", unavailable, calendar)
                        track(store, "shadow", unavailable, calendar)
                    failed = blank_workers()
                    mark_worker(failed, "error", reason=str(exc)[:300], at=clock)
                    store.put("state", "market", {**prior, "heartbeat": clock, "workers": failed,
                                                  "error": "Market worker cycle failed"})
            time.sleep(max(0.1, (float(os.getenv("REPLAY_STEP_SECONDS", "5")) if DEMO else 1) -
                           (time.monotonic() - cycle)))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    name = hashlib.sha256(f"{DB}:{MODE}:{SYMBOL}".encode()).hexdigest()[:12]
    with FileLock(Path(f".worker-{name}.lock"), timeout=0):
        run()
