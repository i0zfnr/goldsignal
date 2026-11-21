import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Literal

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .access import MODEL, admin, encryption
from .diagnostics import record
from .gemini_budget import GeminiPaused, pause_after_429, reserve
from .store import transaction

router = APIRouter()
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="gemini-chat")
lock = Lock()
jobs = {}


class Turn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=8000)


class Conversation(BaseModel):
    turns: list[Turn] = Field(min_length=1, max_length=40)


import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Literal

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .access import MODEL, admin, encryption
from .diagnostics import record
from .gemini_budget import GeminiPaused, pause_after_429, reserve
from .store import transaction

router = APIRouter()
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gemini-chat")
lock = Lock()
jobs = {}


class Turn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=8000)


class Conversation(BaseModel):
    turns: list[Turn] = Field(min_length=1, max_length=40)


def build_market_context(store):
    state = store.get("state", "market") or {}
    quote = state.get("quote") or {}
    b_analysis = state.get("b_analysis") or {}
    signals = sorted(store.all("signal"), key=lambda s: s.get("created", 0), reverse=True)[:5]
    calendar = state.get("calendar") or {}
    now = state.get("now", 0)
    upcoming_news = [e for e in calendar.get("events", []) if e.get("time", 0) >= now][:4]
    zones = b_analysis.get("zones", [])

    return {
        "symbol": "XAUUSD.vx",
        "quote": {"bid": quote.get("bid"), "ask": quote.get("ask"), "spread": round((quote.get("ask", 0) - quote.get("bid", 0)), 2) if quote.get("ask") else 0},
        "market_closed": state.get("closed", False),
        "m15_direction": b_analysis.get("m15", {}).get("direction"),
        "m5_context": b_analysis.get("m5", {}).get("direction"),
        "h1_direction": b_analysis.get("h1", {}).get("direction"),
        "strategy_b_status": b_analysis.get("next_step"),
        "strategy_b_reason": b_analysis.get("reason"),
        "active_liquidity_zones": [
            {"direction": z["direction"], "range": f"{z['bottom']} - {z['top']}", "power": f"{z.get('power', 8)}/10", "condition": "TESTED" if z.get("mitigated") else "FRESH"}
            for z in zones
        ],
        "recent_signals": [
            {"id": s.get("id"), "direction": s.get("direction"), "entry": s.get("entry"), "stop": s.get("stop"), "status": s.get("status"), "hits": s.get("hits")}
            for s in signals
        ],
        "upcoming_economic_events": [
            {"title": n.get("title"), "impact": n.get("impact"), "time": n.get("time")}
            for n in upcoming_news
        ],
    }


def ask(key, turns, context=None):
    try:
        reserve(MODEL)
        system_instruction = (
            "You are Xeniex AI, an elite institutional trading copilot and market analyst embedded in the Xeniex terminal.\n"
            "You have direct real-time telemetry access to the live Valetax MT5 broker feed, SMC liquidity zones, and signal engine.\n\n"
            f"LIVE XENIEX TELEMETRY & SYSTEM STATE:\n{json.dumps(context, indent=2)}\n\n"
            "Rules for your replies:\n"
            "- Answer questions directly, intelligently, and concisely in English.\n"
            "- When asked about price, market structure, zones, or signals, cite the exact numbers from the telemetry above.\n"
            "- Use clean Markdown formatting: bold keywords, code blocks for price levels, and bullet points.\n"
            "- Apply Smart Money Concepts (liquidity pools, supply/demand order blocks, multi-timeframe bias).\n"
            "- If asked for advice, combine technical structure with sound 1% risk management."
        )
        payload = {
            "contents": [{"role": turn.role, "parts": [{"text": turn.text}]} for turn in turns],
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.2,
                "maxOutputTokens": 1024,
            },
        }
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": key}, timeout=40, json=payload,
        )
        if response.status_code >= 400:
            record("Gemini chat", f"Request failed (HTTP {response.status_code}).")
        if response.status_code in (400, 401, 403):
            return {"error": "Gemini rejected the request. Check your AI Studio key and project access."}
        if response.status_code == 404:
            return {"error": "The configured Gemini model is unavailable for this Google project."}
        if response.status_code == 429:
            pause_after_429(response)
            return {"error": "Google Gemini quota exceeded. Check AI Studio or try again later."}
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(part["text"] for part in parts if part.get("text") and not part.get("thought"))
        if not text:
            record("Gemini chat", "Gemini returned an empty response.")
        return {"text": text} if text else {"error": "Gemini returned an empty response."}
    except GeminiPaused as exc:
        return {"error": str(exc)}
    except httpx.HTTPStatusError:
        return {"error": "Gemini did not return a response. Try again."}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        record("Gemini chat", "Gemini connection failed or returned an unreadable response.")
        return {"error": "Gemini did not return a response. Try again."}


@router.post("/api/admin/chat", status_code=202)
def start_chat(body: Conversation, request: Request):
    admin(request)
    if body.turns[-1].role != "user":
        raise HTTPException(422, "End the conversation with a message.")
    if len(body.model_dump_json().encode()) > 8192:
        raise HTTPException(400, "This conversation is too large. Send a shorter message.")
    with transaction() as store:
        settings = store.get("ai", "gemini", {})
        context = build_market_context(store)
    if not settings.get("ciphertext"):
        raise HTTPException(409, "Save a Google AI Studio key in Gemini review to use chat.")
    try:
        key = encryption().decrypt(settings["ciphertext"].encode()).decode()
    except (ValueError, KeyError, InvalidToken):
        raise HTTPException(503, "The saved Gemini key could not be opened.") from None
    with lock:
        if any(not job.done() for job in jobs.values()):
            raise HTTPException(409, "Gemini is still answering the previous message.")
        jobs.clear()
        job_id = secrets.token_urlsafe(18)
        code = getattr(ask, "__code__", None)
        if code and code.co_argcount == 2:
            jobs[job_id] = executor.submit(ask, key, body.turns)
        else:
            jobs[job_id] = executor.submit(ask, key, body.turns, context)
    return {"id": job_id}


@router.get("/api/admin/chat")
def chat_result(id: str, request: Request):
    admin(request)
    with lock:
        job = jobs.get(id)
    if job is None:
        raise HTTPException(404, "This chat response is no longer available.")
    return job.result() if job.done() else {"pending": True}
