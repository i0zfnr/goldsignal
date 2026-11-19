"""Scoped demo Web Push telemetry. Provider acceptance is not device receipt."""

import hashlib
import secrets

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from . import demo_account
from .config import utc_now
from .store import transaction

router = APIRouter()


def require_demo():
    if not demo_account.enabled():
        raise HTTPException(404, "Not found")
    demo_account.assert_isolated()


def record(store, alert, attempt, stage, **fields):
    key = hashlib.sha256(f"{alert}:{attempt}:{stage}".encode()).hexdigest()
    existing = store.get("demo_event", key)
    if not existing:
        store.put("demo_event", key, dict(alert=alert, attempt=attempt, stage=stage,
                                         server_received_at=utc_now(), **fields))
    return key


def prepare(store, alert, attempt):
    if not alert.get("demo_token"):
        alert["demo_token"] = secrets.token_urlsafe(32)
    alert["demo_attempt"] = attempt
    store.put("alert", alert["id"], alert)
    return dict(alert=alert["id"], attempt=attempt, token=alert["demo_token"])


class PhoneEvent(BaseModel):
    alert: str = Field(max_length=128)
    attempt: str = Field(min_length=16, max_length=64)
    token: str = Field(min_length=40, max_length=80)
    stage: Literal["push_handled", "notification_shown", "notification_click"]
    client_at: float = Field(ge=0, le=4102444800, allow_inf_nan=False)
    monotonic: float = Field(ge=0, allow_inf_nan=False)
    context: str = Field(max_length=64)
    clock_offset: float | None = Field(default=None, allow_inf_nan=False)
    clock_uncertainty: float | None = Field(default=None, ge=0, le=300, allow_inf_nan=False)
    clock_calibrated_at: float | None = Field(default=None, ge=0, le=4102444800, allow_inf_nan=False)


@router.get("/api/demo/clock")
def clock():
    require_demo()
    return {"server_at": utc_now()}


@router.post("/api/demo/phone-event")
def phone_event(body: PhoneEvent):
    require_demo()
    with transaction() as store:
        alert = store.get("alert", body.alert)
        submission = store.get("demo_submit", f"{body.attempt}")
        if (not alert or not submission or submission["alert"] != body.alert or
                not secrets.compare_digest(alert.get("demo_token", ""), body.token)):
            raise HTTPException(404, "Demo measurement not found")
        if utc_now() > alert["time"] + 7 * 86400:
            raise HTTPException(410, "Demo measurement expired")
        data = body.model_dump(exclude={"token", "alert", "attempt", "stage"})
        record(store, body.alert, body.attempt, body.stage, **data)
    return {"recorded": True}
