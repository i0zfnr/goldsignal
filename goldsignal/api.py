import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .config import MARKET_SESSIONS, MODE, MY, STALE_SECONDS, SYMBOL, session, utc_now
from .news import manual_pause, restriction
from .store import migrate, transaction
from .access import admin, identity, router
from .alerts import device_key, queue_test
from .chat import router as chat_router
from .diagnostics import record
from .strategy import executable, gate
from .sessions import summary as session_summary
from .workers import snapshot as worker_snapshot
from . import demo_account, demo_phone


@asynccontextmanager
async def lifespan(app):
    demo_account.assert_isolated()
    migrate()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.include_router(chat_router)
app.include_router(demo_phone.router)
COOKIE = "goldsignal_viewer"


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"detail": "Check the submitted fields and try again."}, status_code=422,
                        headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def private_responses(request, call_next):
    if not request.url.path.startswith("/api/"):
        return await call_next(request)
    if demo_account.enabled() and request.url.path == "/api/admin/chat":
        return JSONResponse({"detail": "AI calls are disabled in this demo account study."}, status_code=403,
                            headers={"Cache-Control": "no-store"})
    try:
        response = await call_next(request)
    except Exception:
        route = getattr(request.scope.get("route"), "path", "/api")
        await run_in_threadpool(record, "API", f"{request.method} {route} failed (HTTP 500).")
        raise
    if response.status_code >= 500:
        route = getattr(request.scope.get("route"), "path", "/api")
        await run_in_threadpool(record, "API", f"{request.method} {route} returned HTTP {response.status_code}.")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/admin/errors")
def backend_errors(request: Request):
    admin(request)
    with transaction() as store:
        return {"entries": store.recent("backend_log", 50)}


@app.get("/api/admin/workers")
def admin_workers(request: Request):
    admin(request)
    with transaction() as store:
        state = store.get("state", "market", {})
    now = utc_now()
    quote = state.get("quote") or {}
    spec = state.get("spec") or {}
    return {**worker_snapshot(state.get("workers"), now, state.get("heartbeat"), state.get("error")),
            "mode": MODE, "symbol": SYMBOL, "revision": state.get("revision", 0),
            "quote_age": round(now - quote["time"], 1) if quote.get("time") else None,
            "spec_age": round(now - spec["time"], 1) if spec.get("time") else None,
            "closed": bool(state.get("closed")), "scan": state.get("scan", {}).get("reason"),
            "scalp_scan": state.get("scalp_scan")}


def get_id(request, response):
    actor = identity(request)
    if actor:
        return actor["id"]
    if MODE != "demo" or os.getenv("ADMIN_PASSWORD_HASH"):
        raise HTTPException(401, "Sign in to use Goldsignal.")
    key = request.cookies.get(COOKIE, "")
    if len(key) != 32 or any(c not in "0123456789abcdef" for c in key):
        key = secrets.token_hex(16)
        response.set_cookie(COOKIE, key, max_age=365 * 86400, httponly=True, samesite="strict",
                            secure=os.getenv("SECURE_COOKIE", "0") == "1")
    return key


def metrics(signals):
    fills = [s for s in signals if s["fill"] is not None]
    return dict(entries=len(signals), fills=len(fills), tp1=sum(s["hits"] >= 1 for s in fills),
                result=None if any(s["result_per_lot"] is None for s in fills) else
                round(sum(s["result_per_lot"] for s in fills), 2))


@app.get("/api/performance")
def performance(request: Request, response: Response, period: Literal["day", "week", "month", "all"] = "day"):
    get_id(request, response)
    with transaction() as store:
        clock = store.get("state", "market", {}).get("now", utc_now()) if MODE == "demo" else utc_now()
        signals = store.all("signal")
    today = datetime.fromtimestamp(clock, MY).date()
    start = {"day": today, "week": today - timedelta(days=today.weekday()),
             "month": today.replace(day=1), "all": None}[period]

    def in_period(stamp):
        day = datetime.fromtimestamp(stamp, MY).date()
        return day <= today and (start is None or day >= start)

    totals = dict(wins=0, losses=0, flat=0, pips=0.0)
    buckets = {}
    for signal in signals:
        exits = signal.get("exits", [])
        fill = signal.get("fill")
        if fill is None or not exits or signal["status"] not in ("COMPLETED", "STOPPED", "TIMED_OUT"):
            continue
        closed = exits[-1]["time"]
        if not in_period(closed):
            continue
        direction = 1 if signal["direction"] == "BUY" else -1
        pips = round(sum(direction * (exit["price"] - fill) * exit["fraction"] / 0.10 for exit in exits), 2)
        result = "wins" if pips > 0 else "losses" if pips < 0 else "flat"
        local = datetime.fromtimestamp(closed, MY)
        label = local.strftime("%Y-%m" if period == "all" else "%Y-%m-%d")
        bucket = buckets.setdefault(label, dict(label=label, wins=0, losses=0, flat=0, pips=0.0))
        for summary in (totals, bucket):
            summary[result] += 1
            summary["pips"] = round(summary["pips"] + pips, 2)
    return {**totals, "signals": sum(in_period(s["created"]) for s in signals),
            "buckets": [buckets[key] for key in sorted(buckets)]}


@app.get("/api/sessions")
def sessions_report(request: Request, response: Response,
                    period: Literal["day", "week", "month", "all"] = "day"):
    get_id(request, response)
    with transaction() as store:
        clock = store.get("state", "market", {}).get("now", utc_now()) if MODE == "demo" else utc_now()
        signals = store.all("signal")
        candidates = store.all("candidate")
    today = datetime.fromtimestamp(clock, MY).date()
    start = {"day": today, "week": today - timedelta(days=today.weekday()),
             "month": today.replace(day=1), "all": None}[period]

    def in_period(stamp):
        day = datetime.fromtimestamp(stamp, MY).date()
        return day <= today and (start is None or day >= start)

    return {"sessions": session_summary(signals, candidates, in_period,
                                        [name for _, name, *_ in MARKET_SESSIONS])}


def entry_snapshot(store, signal, state, wall):
    clock = state.get("now", wall) if MODE == "demo" else wall
    quote = state.get("quote") if not state.get("error") and wall - state.get("heartbeat", 0) <= 30 else None
    price = executable(signal, quote) if quote else None
    if signal["status"] not in ("PENDING", "FILLED") or signal.get("hits", 0):
        valid, reason = False, "This signal is already past its entry phase."
    elif manual_pause(store, wall):
        valid, reason = False, "New entries paused by admin."
    else:
        decision, reason = gate(signal, quote, clock, restriction(state.get("calendar", {}), clock, MODE == "demo"))
        valid = decision == "CONFIRM"
    sign = 1 if signal["direction"] == "BUY" else -1
    risk = sign * (price - signal["initial_stop"]) if price is not None else 0
    ratios = [round(sign * (target - price) / risk, 2) for target in signal["targets"]] if valid and risk > 0 else None
    return {"valid": valid, "reason": reason, "quote": quote, "price": price, "ratios": ratios,
            "side": "Ask" if sign == 1 else "Bid", "checked_at": wall}


@app.get("/api/dashboard")
def dashboard(request: Request, response: Response, after: int | None = None, signal: str | None = None,
              frame: Literal["M1", "M5", "M15", "M30", "H1", "H4"] = "M15"):
    profile_id = get_id(request, response)
    response.headers["Cache-Control"] = "no-store"
    with transaction() as store:
        state = store.get("state", "market", {})
        demo = MODE == "demo"
        wall = utc_now()
        now = state.get("now", wall) if demo else wall
        quote = state.get("quote")
        stale = (not quote or wall - state.get("heartbeat", 0) > 30 or state.get("error")
                 or not -2 <= now - quote["time"] <= STALE_SECONDS or not quote["available"])
        status = "STALE" if state.get("error") or wall - state.get("heartbeat", 0) > 30 else (
            "MARKET CLOSED" if state.get("closed") else "STALE" if stale else "DEMO" if demo else "LIVE"
        )
        history = sorted(store.all("signal"), key=lambda s: s["created"], reverse=True)
        active = next((s for s in history if s["status"] in ("PENDING", "FILLED")), None)
        selected = store.get("signal", signal) if signal else active
        candidate = max(store.all("candidate"), key=lambda row: row["evaluated"], default=None)
        calendar = state.get("calendar", {})
        window = session(now)
        if status == "MARKET CLOSED" and window["open"]:
            window = session(window["cutoff"])
        def public(item):
            return {key: value for key, value in item.items() if key not in ("eligible", "costs", "demo_token")}
        visible_alerts = [alert for alert in store.all("alert") if
                          (store.get("push", alert["profile"], {}).get("owner") == profile_id
                           if demo_account.enabled() else alert["profile"] == "shared")]
        return dict(
            symbol=SYMBOL, mode=MODE, status="DEMO" if demo_account.enabled() and status == "LIVE" else status, clock=now, quote=quote, heartbeat=state.get("heartbeat"),
            error=state.get("error"), revision=state.get("revision", 0), candles=store.chart(after, frame), frame=frame,
            scan=state.get("scan") if status != "STALE" else None,
            scalp_scan=state.get("scalp_scan") if status != "STALE" else None,
            session=window, active=public(selected) if selected else None,
            entry_check=(demo_account.check(store, selected, profile_id, wall, quote=quote, spec=state.get("spec"))
                         if demo_account.enabled() and selected and not stale else
                         entry_snapshot(store, selected, state, wall) if selected else None),
            history=[public(item) for item in history[:15]],
            events=sorted((e for e in store.all("event") if selected and e["signal"] == selected["id"]), key=lambda e: e["time"]),
            candidate=public(candidate) if candidate else None,
            calendar={**calendar, "events": sorted(
                (row for row in calendar.get("events", []) if row["time"] >= now),
                key=lambda row: row["time"])[:16], "restriction": restriction(calendar, now, demo)},
            alerts=[public(a) for a in sorted(visible_alerts, key=lambda a: a["time"], reverse=True)[:20]],
            push_key=os.getenv("VAPID_PUBLIC_KEY"), push_enabled=bool(store.get("push", profile_id)),
            metrics={"with_news": metrics(history), "without_news": metrics(store.all("shadow"))},
        )


@app.post("/api/entry-open")
def entry_open(signal: str, request: Request, response: Response, demo_alert: str | None = None,
               demo_attempt: str | None = None):
    opened_at = utc_now()
    viewer = get_id(request, response)
    with transaction() as store:
        item = store.get("signal", signal)
        if not item:
            raise HTTPException(404, "Signal not found.")
        if demo_account.enabled():
            alert = store.get("alert", demo_alert) if demo_alert else None
            subscription = store.get("push", alert["profile"], {}) if alert else {}
            submission = store.get("demo_submit", demo_attempt) if demo_attempt else None
            if (not alert or alert.get("signal") != signal or subscription.get("owner") != viewer or
                    not submission or submission["alert"] != demo_alert):
                raise HTTPException(409, "Open the account-specific demo notification to check this entry.")
            previous_open = store.get("demo_open", demo_account.key(viewer, signal))
            result = previous_open["check"] if previous_open else demo_account.check(store, item, viewer, utc_now())
            demo_phone.record(store, demo_alert, demo_attempt, "server_entry_open", opened_at=opened_at, check=result)
            if not previous_open:
                store.put("demo_open", demo_account.key(viewer, signal), dict(check=result, alert=demo_alert, attempt=demo_attempt))
                demo_account.open_entry(store, item, viewer, alert["profile"], utc_now(), result)
        else:
            result = entry_snapshot(store, item, store.get("state", "market", {}), utc_now())
        store.put("entry_open", secrets.token_hex(16), {"viewer": viewer, "signal": signal, **result})
    return result


class PushKeys(BaseModel):
    p256dh: str = Field(pattern=r"^[\w-]{80,100}$")
    auth: str = Field(pattern=r"^[\w-]{15,30}$")


class PushDevice(BaseModel):
    endpoint: str = Field(max_length=3000)


class Subscription(PushDevice):
    keys: PushKeys


@app.put("/api/push")
def subscribe(subscription: Subscription, request: Request, response: Response):
    key = get_id(request, response)
    try:
        endpoint = urlsplit(subscription.endpoint)
        port = endpoint.port
    except ValueError as exc:
        raise HTTPException(422, "Invalid Web Push endpoint") from exc
    providers = ("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
                 "notify.windows.com")
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or port is not None or not any(
        endpoint.hostname == host or endpoint.hostname.endswith("." + host) for host in providers
    ):
        raise HTTPException(422, "Unsupported Web Push endpoint")
    with transaction() as store:
        for legacy_id, saved in store.items("push"):
            if not legacy_id.startswith("device:") and saved.get("endpoint") == subscription.endpoint:
                store.delete("push", legacy_id)
        store.put("push", device_key(subscription.endpoint), {**subscription.model_dump(), "owner": key})
    return {"enabled": True}


def registered_device(store, owner, endpoint):
    recipient = device_key(endpoint)
    saved = store.get("push", recipient)
    if saved and saved.get("owner") == owner:
        return recipient
    legacy = store.get("push", owner)
    if legacy and legacy.get("endpoint") == endpoint:
        return owner
    return None


@app.post("/api/push/status")
def push_status(device: PushDevice, request: Request, response: Response):
    owner = get_id(request, response)
    with transaction() as store:
        recipient = registered_device(store, owner, device.endpoint)
        test = store.get("alert", f"{recipient}:test", {}) if recipient else {}
    return {"enabled": recipient is not None, "test": test.get("delivery")}


@app.post("/api/push/test")
def test_push(device: PushDevice, request: Request, response: Response):
    owner = get_id(request, response)
    with transaction() as store:
        recipient = registered_device(store, owner, device.endpoint)
        if recipient is None:
            raise HTTPException(409, "Enable notifications on this device first.")
        if not os.getenv("VAPID_PRIVATE_KEY_FILE"):
            raise HTTPException(503, "Push delivery is unavailable.")
        queue_test(store, recipient, utc_now())
    return {"queued": True}


@app.delete("/api/push")
def unsubscribe(request: Request, response: Response, device: PushDevice | None = None):
    owner = get_id(request, response)
    with transaction() as store:
        recipient = registered_device(store, owner, device.endpoint) if device else owner
        if recipient:
            store.delete("push", recipient)
    return {"enabled": False}


if Path("dist/index.html").is_file():
    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse("dist/index.html")

    app.mount("/", StaticFiles(directory="dist", html=True), name="dashboard")
