import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from goldsignal import alerts, api, demo_account, demo_phone, news, scalp_research, store
from goldsignal.config import SYMBOL
from goldsignal import demo_session


@pytest.fixture
def demo(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'demo.sqlite3'}")
    monkeypatch.setattr(store, "engine", engine)
    monkeypatch.setattr(demo_account, "enabled", lambda: True)
    monkeypatch.setattr(demo_account, "assert_isolated", lambda: None)
    monkeypatch.setattr(demo_account, "utc_now", lambda: 100)
    monkeypatch.setattr(api, "utc_now", lambda: 100)
    monkeypatch.setattr(api, "get_id", lambda request, response: "owner")
    monkeypatch.setattr(scalp_research, "ny_window", lambda now: {"open": True})
    monkeypatch.setattr(demo_account, "restriction", lambda *args: None)
    store.migrate()
    yield
    engine.dispose()


def signal():
    return dict(id="fixture", symbol=SYMBOL, direction="BUY", status="PENDING", hits=0, fill=None,
                strategy="M5 setup / M1 entry", entry=[99.5, 100.3], initial_stop=99.3, stop=99.3,
                targets=[101, 102, 103], expiry=200, created=90)


def snapshot(ask=100):
    quote = dict(time=100, bid=ask - .1, ask=ask, available=True)
    spec = dict(symbol=SYMBOL, time=100, max_age=20, minimum=.01, step=.01, maximum=50,
                contract=100, account_currency="USD", conversion=1, commission=7, slippage=.1, margin_rate=.0005)
    return quote, spec


def test_demo_gate_blocks_risk_before_submission_and_rechecks_open(demo, monkeypatch):
    quote, spec = snapshot()
    with store.transaction() as data:
        fit = demo_account.check(data, signal(), "owner", 100, quote, spec)
        assert fit["valid"] and fit["lot"] == .01 and fit["exit_policy"] == "single"
        bad_quote, _ = snapshot(100.2)
        blocked = demo_account.check(data, signal(), "owner", 100, bad_quote, spec)
        assert not blocked["valid"] and blocked["reason"] == "Minimum lot exceeds your risk limit"
        data.put("signal", "fixture", signal())
        data.put("push", "device", {"owner": "owner"})
        data.put("alert", "alert", dict(id="alert", profile="device", signal="fixture"))
        data.put("demo_submit", "attempt", dict(alert="alert", kind="ENTRY", submitted_at=95))
    monkeypatch.setattr(demo_account, "terminal_snapshot", lambda: (bad_quote, spec, None))
    with TestClient(api.app) as client:
        result = client.post("/api/entry-open?signal=fixture&demo_alert=alert&demo_attempt=attempt")
        assert result.status_code == 200 and not result.json()["valid"]
        monkeypatch.setattr(demo_account, "terminal_snapshot", lambda: (quote, spec, None))
        assert not client.post("/api/entry-open?signal=fixture&demo_alert=alert&demo_attempt=attempt").json()["valid"]
    with store.transaction() as data:
        assert data.all("demo_trade") == []
        assert len(data.all("demo_event")) == 1


def test_failed_account_gate_never_calls_webpush(demo, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", "fixture")
    monkeypatch.setattr(demo_account, "check", lambda *args: {"valid": False, "reason": "Minimum lot exceeds your risk limit"})
    monkeypatch.setattr(alerts, "webpush", lambda *args, **kwargs: pytest.fail("Risk-blocked alert was submitted"))
    with store.transaction() as data:
        data.put("signal", "fixture", signal())
        data.put("push", "device", {"owner": "owner"})
        alerts.add_alert(data, "device", signal(), "ENTRY", 90)
    alerts.send_pending(100)
    with store.transaction() as data:
        assert data.all("alert")[0]["delivery"] == "expired"
        assert data.all("demo_check")[0]["reason"] == "Minimum lot exceeds your risk limit"


def test_phone_events_are_capability_scoped_and_idempotent(demo):
    attempt = "0123456789abcdef"
    token = "a" * 43
    with store.transaction() as data:
        data.put("alert", "alert", dict(id="alert", demo_token=token, time=demo_phone.utc_now()))
        data.put("demo_submit", attempt, dict(alert="alert", kind="TEST"))
    payload = dict(alert="alert", attempt=attempt, token=token, stage="push_handled", client_at=100,
                   monotonic=1, context="worker", clock_offset=0, clock_uncertainty=.1)
    with TestClient(api.app) as client:
        assert client.post("/api/demo/phone-event", json={**payload, "token": "b" * 43}).status_code == 404
        assert client.post("/api/demo/phone-event", json=payload).status_code == 200
        assert client.post("/api/demo/phone-event", json=payload).status_code == 200
    with store.transaction() as data:
        events = data.all("demo_event")
        assert len(events) == 1 and token not in json.dumps(events)


def test_single_exit_closes_full_minimum_lot_once(demo):
    with store.transaction() as data:
        quote, spec = snapshot()
        fit = demo_account.check(data, signal(), "owner", 100, quote, spec)
        demo_account.open_entry(data, signal(), "owner", "device", 100, fit)
        tick = dict(time=110, bid=101.1, ask=101.2, available=True)
        demo_account.track(data, {"ticks": [tick]})
        demo_account.track(data, {"ticks": [tick]})
        trade = data.all("demo_trade")[0]
        assert trade["status"] == "TP1" and trade["lot"] == .01
        assert trade["net"] == .93
        assert len(data.all("alert")) == 1


def test_submission_is_separate_from_provider_acceptance_and_device_receipt(demo, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", "fixture")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:fixture@example.com")
    monkeypatch.setattr(alerts, "utc_now", lambda: 100)
    monkeypatch.setattr(demo_account, "check", lambda *args: {"valid": True, "checked_at": 100,
                        "costs": {"commission": 0, "slippage": .1}})
    sent = []
    monkeypatch.setattr(alerts, "webpush", lambda subscription, body, **kwargs: sent.append(json.loads(body)))
    with store.transaction() as data:
        data.put("signal", "fixture", signal())
        data.put("push", "device", {"owner": "owner"})
        alerts.add_alert(data, "device", signal(), "ENTRY", 90)
    alerts.send_pending(100)
    assert sent[0]["title"].startswith("DEMO ENTRY READY")
    assert "demo_alert=" in sent[0]["url"] and "demo_attempt=" in sent[0]["url"]
    with store.transaction() as data:
        assert {event["stage"] for event in data.all("demo_event")} == {"submission", "provider_result"}
        assert len(data.all("demo_submit")) == 1
        assert len(data.all("demo_ready")) == 1


def test_demo_telemetry_routes_are_off_by_default(demo, monkeypatch):
    monkeypatch.setattr(demo_account, "enabled", lambda: False)
    with TestClient(api.app) as client:
        assert client.get("/api/demo/clock").status_code == 404


def test_demo_chat_cannot_make_paid_ai_calls(demo):
    with TestClient(api.app) as client:
        response = client.post("/api/admin/chat", json={"turns": [{"role": "user", "text": "fixture"}]})
        assert response.status_code == 403 and "disabled" in response.json()["detail"]


def test_recorded_calendar_is_not_applied_before_it_was_observed():
    events = [dict(title="Fixture", time=1000, impact="high", observed_from=400, observed_until=500)]
    assert scalp_research.news_pause(events, 350) is None
    assert scalp_research.news_pause(events, 450) == "Calendar pause: Fixture"
    assert scalp_research.news_pause(events, 550) is None


def test_demo_risk_budget_follows_closed_equity(demo):
    quote, spec = snapshot()
    item = {**signal(), "initial_stop": 99.17}
    with store.transaction() as data:
        assert demo_account.check(data, item, "owner", 100, quote, spec)["valid"]
        data.put("demo_trade", "loss", dict(owner="owner", status="SL", net=-1, closed_at=90))
        result = demo_account.check(data, item, "owner", 100, quote, spec)
        assert result["equity"] == 99
        assert not result["valid"] and result["reason"] == "Minimum lot exceeds your risk limit"


def test_archive_admission_requires_full_bounds_and_deduplicates_days(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_session, "FOLDER", tmp_path)
    protocol = dict(start="2026-11-19", account_fingerprint="fixture", broker_company="Fixture", symbol="Fixture")
    session = dict(day="2026-11-19", count=100, gaps_over_20s=0, first=100, opening=100, last=200, cutoff=200)
    for name, gap, first, checked in [("a", 0, 100, 1), ("b", 0, 100, 2), ("c", 1, 100, 3), ("d", 0, 130, 4)]:
        folder = tmp_path / "archives" / name
        folder.mkdir(parents=True)
        manifest = dict(symbol="Fixture", broker="Fixture", broker_audit={"account_fingerprint": "fixture"},
                        archived_at=checked, sessions=[{**session, "gaps_over_20s": gap, "first": first}])
        (folder / "manifest.json").write_text(json.dumps(manifest))
    admitted = demo_session.admitted_archives(protocol)
    assert len(admitted) == 1 and admitted[0][1].name == "b"
