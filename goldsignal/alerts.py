import json
import logging
import os
from hashlib import sha256

from pywebpush import WebPushException, webpush

from .config import MODE, utc_now
from .diagnostics import record
from .news import manual_pause, restriction
from .store import transaction
from .strategy import gate
from . import demo_account, demo_phone
from urllib.parse import urlencode
import secrets

log = logging.getLogger(__name__)


def device_key(endpoint):
    return "device:" + sha256(endpoint.encode()).hexdigest()


def queue_test(store, recipient, now):
    key = f"{recipient}:test"
    previous = store.get("alert", key)
    if previous and (previous["delivery"] == "queued" or now - previous["time"] < 30):
        return
    store.put("alert", key, dict(id=key, profile=recipient, signal=None, kind="TEST", time=now,
                                valid_until=now + 120, title="Goldsignal test notification",
                                body="Notifications are working on this device.", url="/#alerts",
                                delivery="queued", attempts=0))


def add_alert(store, profile_id, signal, kind, ts):
    key = f"{profile_id}:{signal['id']}:{kind}"
    if store.get("alert", key):
        return
    if demo_account.enabled() and profile_id != "shared" and kind != "ENTRY":
        return
    entry = kind == "ENTRY"
    label = " · M5/M1 scalp" if signal.get("strategy") else ""
    title = f"{'DEMO · ' if MODE == 'demo' else ''}{signal['symbol']} {signal['direction']}{label} · {kind}"
    body = f"Entry {signal['entry'][0]:.2f}–{signal['entry'][1]:.2f} · SL {signal['stop']:.2f}" if entry else (
        f"Simulated tracking · stop {signal['stop']:.2f}"
    )
    if kind == "TP1" and signal["fill"] != signal["reference"]:
        body += " · moved to reference"
    frame = "&frame=M1" if signal.get("strategy") else ""
    settings = store.get("push", profile_id, {})
    store.put("alert", key, dict(id=key, profile=profile_id, signal=signal["id"], kind=kind, time=ts,
                                valid_until=signal["expiry"] if entry else ts + 3600,
                                title=title, body=body, url=f"/?signal={signal['id']}&alert=1{frame}#signal",
                                delivery="queued" if settings else "preview", attempts=0))


def send_pending(now):
    private = os.getenv("VAPID_PRIVATE_KEY_FILE")
    if not private:
        return
    with transaction() as store:
        alerts = [a for a in store.all("alert") if a["delivery"] == "queued"][:20]
    for alert in alerts:
        with transaction() as store:
            subscription = store.get("push", alert["profile"])
            state = store.get("state", "market", {})
            clock = state.get("now", now) if MODE == "demo" and alert["kind"] != "TEST" else utc_now()
            signal = store.get("signal", alert["signal"])
            eligible = True
            if alert["kind"] == "ENTRY":
                pause = restriction(state.get("calendar", {}), clock, MODE == "demo")
                quote = state.get("quote") if utc_now() - state.get("heartbeat", 0) <= 30 else None
                eligible = True if demo_account.enabled() else bool(not manual_pause(store, utc_now()) and signal and
                                signal["status"] in ("PENDING", "FILLED") and not signal.get("hits") and
                                gate(signal, quote, clock, pause)[0] == "CONFIRM")
                if demo_account.enabled():
                    owner = subscription.get("owner") if subscription else None
                    account_check = demo_account.check(store, signal, owner, clock) if owner else {"valid": False, "reason": "Demo device owner required"}
                    store.put("demo_check", alert["id"], {"alert": alert["id"], **account_check})
                    eligible = account_check["valid"]
                    alert["demo_account"] = account_check
                    if eligible:
                        alert["title"] = f"DEMO ENTRY READY · {signal['direction']} · 0.01 lot"
                        alert["body"] = (f"USD100 paper · one full exit at {signal['targets'][0]:.2f} · SL {signal['initial_stop']:.2f}. "
                                         f"Cost assumptions: USD{account_check['costs']['commission']:g}/lot round trip + "
                                         f"{account_check['costs']['slippage']:g} price slippage.")
                    else:
                        alert["title"] = "DEMO entry blocked"
                        alert["body"] = f"First reason: {account_check['reason']}"
        if not subscription or clock >= alert["valid_until"] or not eligible:
            alert["delivery"] = "expired"
        elif clock >= alert.get("retry_at", 0):
            alert["attempts"] += 1
            attempt = None
            actual_submission = None
            provider_status = None
            try:
                payload = {key: alert[key] for key in ("id", "title", "body", "url")}
                if demo_account.enabled():
                    attempt = secrets.token_hex(16)
                    with transaction() as store:
                        payload["demo"] = demo_phone.prepare(store, alert, attempt)
                        submitted = utc_now()
                        store.put("demo_submit", attempt, dict(alert=alert["id"], submitted_at=submitted, kind=alert["kind"]))
                        if alert["kind"] == "ENTRY":
                            store.put("demo_ready", alert["id"], dict(owner=subscription["owner"], signal=signal["id"], time=submitted))
                    if alert["signal"]:
                        before, separator, fragment = alert["url"].partition("#")
                        payload["url"] = before + ("&" if "?" in before else "?") + urlencode(dict(demo_alert=alert["id"], demo_attempt=attempt)) + separator + fragment
                actual_submission = utc_now()
                outcome = webpush(subscription, json.dumps(payload),
                        vapid_private_key=private, vapid_claims={"sub": os.environ["VAPID_SUBJECT"]},
                        ttl=max(1, int(alert["valid_until"] - clock)), timeout=5)
                alert["delivery"] = "sent"
                provider_status = getattr(outcome, "status_code", None)
            except WebPushException as exc:
                status = exc.response.status_code if exc.response is not None else None
                transient = status in (None, 408, 425, 429) or (status is not None and status >= 500)
                alert["delivery"] = "queued" if transient and alert["attempts"] < 4 else "failed"
                alert["retry_at"] = clock + 15 * 2 ** (alert["attempts"] - 1)
                log.warning("Push %s returned HTTP %s", alert["id"], status)
                problem = f"HTTP {status}" if status is not None else "connection failed"
                record("Push delivery", f"Attempt {alert['attempts']} failed ({problem}).")
            except Exception:
                log.exception("Push delivery failed for %s", alert["id"])
                record("Push delivery", "Push delivery failed.")
                alert["delivery"] = "failed"
            finally:
                if attempt:
                    with transaction() as store:
                        if actual_submission is not None:
                            store.put("demo_submit", attempt, dict(alert=alert["id"], submitted_at=actual_submission, kind=alert["kind"]))
                            candidate = store.get("demo_candidate", alert.get("signal"), {})
                            eligible_observation = store.get("demo_eligible", alert.get("signal"), {})
                            demo_phone.record(store, alert["id"], attempt, "submission", submitted_at=actual_submission, kind=alert["kind"],
                                              candidate=candidate, eligibility=eligible_observation)
                        demo_phone.record(store, alert["id"], attempt, "provider_result", finished_at=utc_now(),
                                          accepted=alert["delivery"] == "sent", status=provider_status)
        with transaction() as store:
            store.put("alert", alert["id"], alert)
