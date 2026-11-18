import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Literal

import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .access import MODEL, admin, encryption
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


def ask(key, turns):
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": key}, timeout=40,
            json={"contents": [{"role": turn.role, "parts": [{"text": turn.text}]} for turn in turns]},
        )
        if response.status_code in (400, 401, 403):
            return {"error": "Gemini rejected the request. Check your AI Studio key and project access."}
        if response.status_code == 404:
            return {"error": "The configured Gemini model is unavailable for this Google project."}
        if response.status_code == 429:
            return {"error": "Google Gemini quota exceeded. Check AI Studio or try again later."}
        response.raise_for_status()
        parts = response.json()["candidates"][0]["content"]["parts"]
        text = "\n".join(part["text"] for part in parts if part.get("text") and not part.get("thought"))
        return {"text": text} if text else {"error": "Gemini returned an empty response."}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return {"error": "Gemini did not return a response. Try again."}


@router.post("/api/admin/chat", status_code=202)
def start_chat(body: Conversation, request: Request):
    admin(request)
    if body.turns[-1].role != "user":
        raise HTTPException(422, "End the conversation with a message.")
    with transaction() as store:
        settings = store.get("ai", "gemini", {})
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
        jobs[job_id] = executor.submit(ask, key, body.turns)
    return {"id": job_id}


@router.get("/api/admin/chat")
def chat_result(id: str, request: Request):
    admin(request)
    with lock:
        job = jobs.get(id)
    if job is None:
        raise HTTPException(404, "This chat response is no longer available.")
    return job.result() if job.done() else {"pending": True}
