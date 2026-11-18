import json
import logging
import os

from pywebpush import WebPushException, webpush

from .config import MODE, utc_now
from .diagnostics import record
from .news import manual_pause, restriction
from .store import transaction
from .strategy import gate

log = logging.getLogger(__name__)


def add_alert(store, profile_id, signal, kind, ts):
    key = f"{profile_id}:{signal['id']}:{kind}"
    if store.get("alert", key):
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
            clock = state.get("now", now) if MODE == "demo" else utc_now()
            signal = store.get("signal", alert["signal"])
            eligible = True
            if alert["kind"] == "ENTRY":
                pause = restriction(state.get("calendar", {}), clock, MODE == "demo")
                quote = state.get("quote") if utc_now() - state.get("heartbeat", 0) <= 30 else None
                eligible = bool(not manual_pause(store, utc_now()) and signal and signal["status"] == "PENDING" and
                                gate(signal, quote, clock, pause)[0] == "CONFIRM")
        if not subscription or clock >= alert["valid_until"] or not eligible:
            alert["delivery"] = "expired"
        elif clock >= alert.get("retry_at", 0):
            alert["attempts"] += 1
            try:
                webpush(subscription, json.dumps({key: alert[key] for key in ("id", "title", "body", "url")}),
                        vapid_private_key=private, vapid_claims={"sub": os.environ["VAPID_SUBJECT"]},
                        ttl=max(1, int(alert["valid_until"] - clock)), timeout=5)
                alert["delivery"] = "sent"
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
        with transaction() as store:
            store.put("alert", alert["id"], alert)
