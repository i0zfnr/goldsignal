import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from .config import MODE, STALE_SECONDS, SYMBOL, session, utc_now
from .news import restriction
from .store import migrate, transaction
from .access import identity, router
from .chat import router as chat_router


@asynccontextmanager
async def lifespan(app):
    migrate()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.include_router(chat_router)
COOKIE = "goldsignal_viewer"


@app.exception_handler(RequestValidationError)
async def invalid_request(request, exc):
    return JSONResponse({"detail": "Check the submitted fields and try again."}, status_code=422,
                        headers={"Cache-Control": "no-store"})


@app.middleware("http")
async def private_responses(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


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
        selected = store.get("signal", signal) if signal else active or next(iter(history), None)
        candidate = max(store.all("candidate"), key=lambda row: row["evaluated"], default=None)
        calendar = state.get("calendar", {})
        window = session(now)
        if status == "MARKET CLOSED" and window["open"]:
            window = session(window["cutoff"])
        def public(item):
            return {key: value for key, value in item.items() if key not in ("eligible", "costs")}
        return dict(
            symbol=SYMBOL, mode=MODE, status=status, clock=now, quote=quote, heartbeat=state.get("heartbeat"),
            error=state.get("error"), revision=state.get("revision", 0), candles=store.chart(after, frame), frame=frame,
            scan=state.get("scan") if status != "STALE" else None,
            session=window, active=public(selected) if selected else None,
            history=[public(item) for item in history[:15]],
            events=sorted((e for e in store.all("event") if selected and e["signal"] == selected["id"]), key=lambda e: e["time"]),
            candidate=public(candidate) if candidate else None,
            calendar={**calendar, "events": sorted(
                (row for row in calendar.get("events", []) if row["time"] >= now),
                key=lambda row: row["time"])[:6], "restriction": restriction(calendar, now, demo)},
            alerts=sorted((a for a in store.all("alert") if a["profile"] == "shared"),
                          key=lambda a: a["time"], reverse=True)[:20],
            push_key=os.getenv("VAPID_PUBLIC_KEY"), push_enabled=bool(store.get("push", profile_id)),
            metrics={"with_news": metrics(history), "without_news": metrics(store.all("shadow"))},
        )


class PushKeys(BaseModel):
    p256dh: str = Field(pattern=r"^[\w-]{80,100}$")
    auth: str = Field(pattern=r"^[\w-]{15,30}$")


class Subscription(BaseModel):
    endpoint: str = Field(max_length=3000)
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
        store.put("push", key, subscription.model_dump())
    return {"enabled": True}


@app.delete("/api/push")
def unsubscribe(request: Request, response: Response):
    with transaction() as store:
        store.delete("push", get_id(request, response))
    return {"enabled": False}


if Path("dist/index.html").is_file():
    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse("dist/index.html")

    app.mount("/", StaticFiles(directory="dist", html=True), name="dashboard")
