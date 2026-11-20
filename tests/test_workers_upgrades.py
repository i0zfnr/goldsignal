"""Tests for Worker Upgrades: Telegram, Heads-up, Strategy C Range Fade, Kuro Latency."""

from goldsignal import telegram
from goldsignal.range_fade import asian_range_candidate
from goldsignal.api import app
from fastapi.testclient import TestClient
from goldsignal.access import password_hash
from cryptography.fernet import Fernet
import pytest


def make_bar(time, open_, high, low, close):
    return dict(time=time, open=float(open_), high=float(high), low=float(low), close=float(close))


def test_telegram_message_formatters():
    signal = {
        "symbol": "XAUUSD.vx",
        "direction": "SELL",
        "entry": [3718.28, 3723.67],
        "initial_stop": 3726.10,
        "stop": 3726.10,
        "targets": [3710.00, 3702.00],
        "lane": "B",
        "strategy": "Liquidity scalp",
    }
    # Entry formatting
    text = telegram.format_entry(signal, 1795100000)
    assert "GOLDSIGNAL · XAUUSD.vx" in text
    assert "SELL · ENTRY SIGNAL" in text
    assert "3718.28 – 3723.67" in text
    assert "3726.10" in text
    assert "TP1" in text

    # Heads-up formatting
    zone = {"bottom": 3718.28, "top": 3723.67, "direction": "SELL"}
    rej = {"close": 3717.50}
    headsup = telegram.format_headsup("SELL", zone, rej, 1795100000)
    assert "HEADS-UP" in headsup
    assert "M5 Rejection at M15 Zone" in headsup
    assert "3718.28 – 3723.67" in headsup

    # Zone touch formatting
    ztouch = telegram.format_zone_touch("SELL", zone, 3720.0, 1795100000)
    assert "PRICE ENTERED ZONE" in ztouch
    assert "SUPPLY ZONE" in ztouch
    assert "3718.28 – 3723.67" in ztouch

    # Lifecycle event formatting
    event_tp1 = telegram.format_event(dict(signal, fill=3720.00, stop=3720.00), "TP1", 1795100100)
    assert "TP1" in event_tp1
    assert "3720.00" in event_tp1


def test_strategy_c_asian_range_fade():
    # Outside Asian window (e.g. 02:00 MYT -> timestamp where MYT hour is 2)
    # 2026-11-20 02:00 MYT = 2026-11-19 18:00 UTC
    snapshot = dict(now=1795111200, symbol="XAUUSD.vx")
    cand, scan = asian_range_candidate(snapshot, [], [])
    assert cand is None
    assert "Outside Asian sweep" in scan or "Waiting" in scan


def test_telegram_admin_api_endpoints(db, monkeypatch):
    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())

    with TestClient(app) as operator, TestClient(app) as viewer:
        # Non-admin rejected
        assert viewer.get("/api/admin/telegram").status_code == 403
        assert viewer.put("/api/admin/telegram", json={"bot_token": "1234567890:ABCdefGhIjk", "chat_id": "@chan"}).status_code == 403

        # Admin logs in
        login = operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})
        assert login.status_code == 200

        # Initial config check
        cfg = operator.get("/api/admin/telegram").json()
        assert "configured" in cfg

        # Save telegram settings
        res = operator.put("/api/admin/telegram", json={
            "bot_token": "1234567890:ABCdefGhIjkLmNoPqRsTuVwXyZ",
            "chat_id": "@testchannel",
            "enabled": True,
        })
        assert res.status_code == 200
        assert res.json()["chat_id"] == "@testchannel"

        # Verify get returns masked token
        cfg2 = operator.get("/api/admin/telegram").json()
        assert cfg2["configured"] is True
        assert cfg2["chat_id"] == "@testchannel"
        assert cfg2["masked_token"].startswith("123456")
