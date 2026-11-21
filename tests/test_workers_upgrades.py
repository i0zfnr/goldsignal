"""Tests for Worker Upgrades: Telegram delivery policy, Strategy C Range Fade, Kuro Latency."""

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
    assert "XENIEX · XAUUSD.vx" in text
    assert "SELL · ENTRY SIGNAL" in text
    assert "3718.28 – 3723.67" in text
    assert "3726.10" in text
    assert "TP1" in text

    legacy_scalp = telegram.format_entry({**signal, "evidence": {"grade": "M5/M1 scalp"}}, 1795100000)
    assert "ENTRY SIGNAL [A]" in legacy_scalp

    # Zone touch formatting
    zone = {"bottom": 3718.28, "top": 3723.67, "direction": "SELL"}
    ztouch = telegram.format_zone_touch("SELL", zone, 3720.0, 1795100000)
    assert "PRICE IN ENTRY ZONE" in ztouch
    assert "NOT A TRADE SIGNAL" in ztouch
    assert "DO NOT ENTER" in ztouch
    assert "SUPPLY ENTRY ZONE" in ztouch
    assert "3718.28 – 3723.67" in ztouch

    # Lifecycle event formatting
    event_tp1 = telegram.format_event(dict(signal, fill=3720.00, stop=3720.00), "TP1", 1795100100)
    assert "TP1" in event_tp1
    assert "3720.00" in event_tp1


def test_telegram_dispatch_policy_allows_only_signal_and_entry_zone(monkeypatch):
    delivered = []
    monkeypatch.setattr(telegram, "send_telegram",
                        lambda text, *_args, **_kwargs: delivered.append(text) or True)

    futures = [
        telegram.dispatch_telegram("RESEARCH WATCH ONLY", category="ADMIN"),
        telegram.dispatch_telegram("HEADS-UP", category="RESEARCH"),
        telegram.dispatch_telegram("ENTRY SIGNAL [B+]", category="SIGNAL"),
    ]
    assert not delivered and not any(futures)

    futures = [
        telegram.dispatch_telegram("ENTRY SIGNAL [A+]", category="SIGNAL"),
        telegram.dispatch_telegram("PRICE IN ENTRY ZONE", category="PRICE_ENTRY_ZONE"),
    ]
    for future in futures:
        assert future is not None and future.result() is True
    assert len(delivered) == 2


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


def test_admin_user_crud_operations(db, monkeypatch):
    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())

    with TestClient(app) as operator:
        operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})

        # 1. Create User
        res = operator.post("/api/admin/keys", json={"label": "VIP Scalper 1"})
        assert res.status_code == 201
        data = res.json()
        key_id = data["id"]
        secret = data["key"]
        assert secret.startswith("gs_")

        # 2. Update User Label
        update_res = operator.put("/api/admin/keys", json={"id": key_id, "label": "VIP Scalper Prime", "revoked": False})
        assert update_res.status_code == 200
        assert update_res.json()["key"]["label"] == "VIP Scalper Prime"

        # 3. Toggle Revoke
        revoke_res = operator.put("/api/admin/keys", json={"id": key_id, "label": "VIP Scalper Prime", "revoked": True})
        assert revoke_res.status_code == 200
        assert revoke_res.json()["key"]["revoked"] is True

        # 4. Permanent Delete
        del_res = operator.delete("/api/admin/keys", params={"id": key_id, "permanent": True})
        assert del_res.status_code == 200
        assert del_res.json()["deleted"] is True


def test_admin_error_log_and_performance_reset(db, monkeypatch):
    from goldsignal import diagnostics
    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())

    with TestClient(app) as operator:
        operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})

        # Record test log
        diagnostics.record("TestWorker", "Test log message")
        logs_24h = operator.get("/api/admin/errors", params={"timeframe": "24h"}).json()
        assert len(logs_24h["entries"]) >= 1

        # Clear logs
        cleared = operator.delete("/api/admin/errors").json()
        assert cleared["cleared"] is True
        logs_after = operator.get("/api/admin/errors").json()
        assert len(logs_after["entries"]) == 0

        # Performance API check and reset
        perf = operator.get("/api/admin/performance").json()
        assert "signals_count" in perf

        reset_res = operator.post("/api/admin/performance/reset").json()
        assert reset_res["reset"] is True
        assert reset_res["archive_id"].startswith("backup:")


def test_admin_can_delete_single_performance_record(db, monkeypatch):
    from goldsignal import store

    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())
    with store.transaction() as data:
        data.put("signal", "s1", dict(id="s1", created=100, status="COMPLETED", fill=100,
                                      result_per_lot=10, direction="BUY", grade="A"))
        data.put("event", "e1", dict(id="e1", signal="s1"))
        data.put("alert", "a1", dict(id="a1", signal="s1", profile="shared", kind="TP1"))
        data.put("shadow", "s1", dict(id="s1"))

    with TestClient(app) as operator:
        operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})
        response = operator.request("DELETE", "/api/admin/performance/signal", json={"signal_id": "s1"})
        assert response.status_code == 200
        result = response.json()
        assert result["deleted"] is True and result["signal_id"] == "s1"
        assert operator.request("DELETE", "/api/admin/performance/signal",
                                json={"signal_id": "s1"}).status_code == 404

    with store.transaction() as data:
        assert data.get("signal", "s1") is None
        assert data.get("event", "e1") is None
        assert data.get("alert", "a1") is None
        assert data.get("shadow", "s1") is None
        archived = data.get("archive_performance", result["archive_id"])
        assert archived["signal"]["id"] == "s1"
        assert len(archived["events"]) == 1 and len(archived["alerts"]) == 1


def test_admin_scanner_report(db, monkeypatch):
    from goldsignal import store
    from goldsignal.config import utc_now

    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())
    now = utc_now()
    with store.transaction() as data:
        data.put("state", "market", {"now": now})
        data.put("candidate", "c1", dict(id="c1", evaluated=now, decision="WAIT",
                                         reason="current reason", first={"reason": "No active M15 liquidity zone."},
                                         lane="B", strategy="B · liquidity scalp", session="London"))
        data.put("signal", "s1", dict(id="s1", created=now, status="COMPLETED", grade="A",
                                      fill=100, hits=1, result_per_lot=1,
                                      exits=[dict(time=now + 60, price=101, fraction=1)]))

    with TestClient(app) as operator:
        operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})
        report = operator.get("/api/admin/scanner-report?period=day").json()

    assert report["detected"] >= 1 and report["held"] >= 1
    assert report["published"] >= 1 and report["wins"] >= 1
    assert any(row["reason"] == "No active M15 liquidity zone." for row in report["blocked_reasons"])


def test_hayate_and_ryu_workers_telemetry(db):
    from goldsignal import workers
    state = workers.blank()
    assert state["hayate"]["label"] == "Hayate"
    assert state["ryu"]["label"] == "Ryu"
    assert state["shinra"]["label"] == "Shinra"
    assert "taka" in state["division"]
    assert "ren" in state["division"]
    assert "kai" in state["division"]
    assert "sora" in state["division"]
    workers.mark(state, "live", reason="Parallel compute 3 lanes", at=100, name="hayate")
    workers.mark(state, "idle", reason="0 queued", at=100, name="ryu")
    workers.mark(state, "live", reason="1,000 candles scanned", at=100, name="shinra")
    workers.mark_division(state, "taka", "live", reason="Wyckoff sweep", at=100)
    snap = workers.snapshot(state, now=105, heartbeat=104)
    assert snap["hayate"]["status"] == "live"
    assert snap["hayate"]["age_seconds"] == 5.0
    assert snap["ryu"]["status"] == "idle"
    assert snap["shinra"]["label"] == "Shinra"
    assert len(snap["division"]) == 4
    taka = next(s for s in snap["division"] if s["name"] == "taka")
    assert taka["status"] == "live"
    assert taka["reason"] == "Wyckoff sweep"


def test_shinra_pattern_research_engine():
    from goldsignal import pattern_research
    bars = [make_bar(i * 900, 100 + i * 0.5, 101 + i * 0.5, 99 + i * 0.5, 100.5 + i * 0.5) for i in range(30)]
    res = pattern_research.conduct_research(bars, price=115.0, direction="SELL")
    assert "shinra" in res
    assert "taka" in res
    assert "ren" in res
    assert "kai" in res
    assert res["shinra"]["director"] == "Shinra"
    assert "edge_score" in res["shinra"]
    assert "status" in res["shinra"]

