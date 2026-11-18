from datetime import datetime

from cryptography.fernet import Fernet
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from goldsignal import alerts, chat, config, news, store, worker
from goldsignal.api import app
from goldsignal.access import password_hash
from goldsignal.lifecycle import advance
from goldsignal.market import REPLAY_START, Replay, demo_profile, demo_spec
from goldsignal.strategy import account_fit, compare_pattern, gate, levels, setup
from goldsignal.replay_report import allocate, candidates, replay
from goldsignal.scalp import scalp_candidate


def test_access_and_gemini_storage(db, monkeypatch):
    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())
    with TestClient(app) as operator, TestClient(app) as viewer:
        assert viewer.get("/api/dashboard").status_code == 401
        assert viewer.get("/api/admin/settings").status_code == 403
        login = operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})
        assert login.status_code == 200 and "HttpOnly" in login.headers["set-cookie"]
        secret = operator.post("/api/admin/keys", json={"label": "Fixture viewer"}).json()["key"]
        assert viewer.post("/api/auth/viewer", json={"credential": secret}).status_code == 200
        assert viewer.get("/api/dashboard?frame=M1").json()["frame"] == "M1"
        assert viewer.put("/api/admin/gemini", json={"enabled": True}).status_code == 403
        assert viewer.put("/api/admin/pause", json={"paused": True}).status_code == 403
        assert operator.put("/api/admin/pause", json={"paused": True}).json()["paused"]
        tick(0)
        assert operator.get("/api/dashboard").json()["candidate"]["reason"] == "New entries paused by admin."
        assert not operator.put("/api/admin/pause", json={"paused": False}).json()["paused"]
        provider_key = "AQ.fixture-provider-key"
        assert operator.put("/api/admin/gemini", json={"api_key": provider_key, "enabled": True}).status_code == 200
        settings = operator.get("/api/admin/settings")
        assert settings.json()["enabled"] and secret not in settings.text and provider_key not in settings.text
        monkeypatch.setattr(chat, "ask", lambda key, turns: {"text": "Fixture response"}
                            if key == provider_key and turns[-1].text == "Explain the setup." else {"error": "Unexpected request"})
        prompt = {"turns": [{"role": "user", "text": "Explain the setup."}]}
        assert viewer.post("/api/admin/chat", json=prompt).status_code == 403
        job = operator.post("/api/admin/chat", json=prompt)
        assert job.status_code == 202
        assert operator.get("/api/admin/chat", params=job.json()).json() == {"text": "Fixture response"}
        with store.transaction() as data:
            assert data.get("ai_usage", "gemini") is None
        with store.transaction() as data:
            assert provider_key not in str(data.get("ai", "gemini"))
        assert operator.delete("/api/admin/keys", params={"id": settings.json()["keys"][0]["id"]}).status_code == 200
        assert viewer.get("/api/dashboard").status_code == 401
        assert operator.delete("/api/auth/session").status_code == 200
        assert operator.get("/api/admin/settings").status_code == 403


def test_pattern_rsi8_uses_actual_sample():
    bars = [dict(time=i * 900, open=3700 + i, high=3702 + i, low=3699 + i, close=3701 + i)
            for i in range(1100)]
    pattern = compare_pattern(bars, 1)
    assert pattern["history"] == 1000 and pattern["rsi8"] == 100
    assert pattern["matches"] == 5 and pattern["next4_bps"] > 0


def test_gemini_caps_and_invalid_review_hold(db, monkeypatch):
    key = Fernet.generate_key()
    cipher = Fernet(key)
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", key.decode())
    calls = []

    class Reply:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"decision":"BUY","reason":"invalid"}'}]}}]}

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        assert "generativelanguage.googleapis.com" in url
        assert kwargs["json"]["generationConfig"]["maxOutputTokens"] == 96
        assert kwargs["json"]["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"
        assert len(kwargs["json"]["contents"][0]["parts"][0]["text"]) < 650
        return Reply()

    monkeypatch.setattr(worker.httpx, "post", post)
    config_row = {"enabled": True, "ciphertext": cipher.encrypt(b"fixture-provider-key").decode()}
    with store.transaction() as data:
        data.put("ai", "gemini", config_row)
    tick(0)
    tick(1)
    with store.transaction() as data:
        assert len(calls) == 1 and not data.all("signal")
        assert data.all("candidate")[0]["reason"] == "Gemini review unavailable"
    s = sample()
    for _ in range(6):
        worker.gemini_review(config_row, worker.new_candidate(s), s, {})
    assert len(calls) == 6


@pytest.fixture
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    monkeypatch.setattr(store, "engine", engine)
    store.migrate()
    yield
    engine.dispose()


def sample():
    return Replay().read(None, 0, 0)


def tick(step):
    snapshot = Replay().read(None, step, 0)
    return worker.process(Replay(), step, None, news.refresh(True, snapshot["now"], {}), step + 1)


def stamp(value):
    return datetime.fromisoformat(value).timestamp()


def test_sell_levels_and_closed_swing():
    s = sample()
    candidate = worker.new_candidate(s)
    assert candidate["direction"] == "SELL"
    assert candidate["reference"] == 3793.42
    assert candidate["entry"] == [3793.42, 3796.42]
    assert candidate["stop"] == 3799.42
    assert candidate["targets"] == [3790.42, 3787.42, 3783.42]
    assert (candidate["initial_stop"] - candidate["reference"]) / 0.1 == 60
    assert candidate["evidence"]["swing_confirmed"] <= s["now"]
    assert setup(s["bars"], REPLAY_START - 1) is None


@pytest.mark.parametrize(("opening", "myt_hour"), [
    ("2026-03-06T13:00:00+00:00", 21),
    ("2026-03-09T12:00:00+00:00", 20),
    ("2026-11-02T13:00:00+00:00", 21),
])
def test_dst_and_boundaries(opening, myt_hour, monkeypatch):
    monkeypatch.setattr(config, "ENTRY_SESSIONS", {"new_york"})
    now = stamp(opening)
    assert not config.session(now - 1)["open"]
    result = config.session(now)
    assert result["open"]
    assert datetime.fromisoformat(result["next_myt"]).hour == myt_hour
    assert config.session(result["cutoff"] - 1)["open"]
    assert not config.session(result["cutoff"])["open"]


def test_broker_overlap_and_weekend():
    saturday = stamp("2026-11-21T15:00:00+00:00")
    assert not config.session(saturday)["open"]
    monday = stamp("2026-11-23T15:00:00+00:00")
    assert not config.session(monday, "11:00-12:00")["open"]
    assert config.session(monday + 3600, "11:00-12:00")["open"]


def test_regional_sessions_and_broker_rollover(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_SESSIONS", {"sydney", "tokyo", "london", "new_york"})
    hours = "00:00-17:00,18:00-24:00"
    first = config.session(stamp("2026-11-22T22:59:59+00:00"), hours)
    assert not first["open"] and first["next"] == ["Sydney"]
    asia = config.session(stamp("2026-11-23T02:00:00+00:00"), hours)
    assert asia["active"] == ["Sydney", "Tokyo"]
    overlap = config.session(stamp("2026-11-23T14:00:00+00:00"), hours)
    assert overlap["active"] == ["London", "New York"]
    assert asia["cutoff"] == overlap["cutoff"] == stamp("2026-11-23T22:00:00+00:00")
    assert not config.session(overlap["cutoff"], hours)["open"]


def test_broker_exception_with_early_close(monkeypatch):
    monday = stamp("2026-11-23T15:00:00+00:00")
    monkeypatch.setattr(config, "BROKER_DATE_HOURS", {"2026-11-23": "00:00-11:00"})
    current = config.session(monday, "00:00-24:00")
    assert current["open"] and current["cutoff"] == monday + 3600
    assert not config.session(current["cutoff"], "00:00-24:00")["open"]


def test_stale_quote_calendar_spread_and_zone():
    s = sample()
    now = s["now"]
    candidate = worker.new_candidate(s)
    quote = s["quote"]
    assert gate(candidate, quote, now)[0] == "CONFIRM"
    assert gate(candidate, {**quote, "time": now - 90}, now)[0] == "WAIT"
    assert gate(candidate, {**quote, "ask": quote["bid"] + 1}, now)[0] == "WAIT"
    assert gate(candidate, {**quote, "bid": 3700, "ask": 3700.24}, now)[0] == "WAIT"
    result, reason = worker.evaluate(candidate, quote, now, {"sources": {"Fixture": 0}})
    assert result == "WAIT" and "stale" in reason


def test_confirmation_after_cutoff(db, monkeypatch):
    s = sample()
    end = config.session(s["now"])["cutoff"]
    before = {**s, "now": end - 1, "quote": {**s["quote"], "time": end - 1}}
    after = {**s, "now": end, "quote": {**s["quote"], "time": end}}
    candidate = {**worker.new_candidate(s), "expiry": end}
    snapshots = iter((before, after))

    class Source:
        def read(self, *args):
            return next(snapshots)

    monkeypatch.setattr(worker, "DEMO", False)
    monkeypatch.setattr(worker, "REVIEW", "ollama")
    monkeypatch.setattr(worker, "new_candidate", lambda snap: candidate)
    monkeypatch.setattr(worker, "model_review", lambda *args: ("CONFIRM", "Fixture response"))
    monkeypatch.setattr(worker, "utc_now", lambda: end)
    worker.process(Source(), 0, None, {"sources": dict.fromkeys(("BLS", "BEA", "Fed"), end - 1)}, 1)
    with store.transaction() as data:
        assert data.get("candidate", candidate["id"])["decision"] == "REJECT"
        assert not data.all("signal")
        assert not data.all("alert")


def test_small_account_budget_and_exit_policies():
    now = REPLAY_START
    signal = {"direction": "SELL", **levels("SELL", 3793.42)}
    spec = demo_spec(now)
    profile = {**demo_profile(now), "equity": 100, "free_margin": 100}
    fit = account_fit(signal, profile, spec, now)
    assert (fit["decision"], fit["minimum_before_cost"], fit["budget"]) == ("SKIP", 6, 1)
    assert account_fit(signal, profile, None, now)["decision"] == "SKIP"
    fit = account_fit(signal, demo_profile(now), spec, now)
    assert fit["decision"] == "FIT" and fit["lot"] == 0.08
    assert fit["loss"] <= fit["budget"]
    profile.update(equity=700, free_margin=100)
    assert "cannot split" in account_fit(signal, profile, spec, now)["reason"]
    assert account_fit(signal, {**profile, "exit_policy": "single"}, spec, now)["lot"] == 0.01
    assert account_fit(signal, demo_profile(now), spec, now, -150)["decision"] == "SKIP"
    assert account_fit(signal, demo_profile(now), spec, now + 61)["decision"] == "SKIP"


def test_tick_order_and_terminal_states():
    s = sample()
    signal = worker.new_candidate(s)
    quote = s["quote"]
    now = s["now"]
    assert advance(signal, quote, now, True, signal["costs"])[0][0] == "FILLED"
    assert advance(signal, {**quote, "ask": 3787}, now + 1, False, signal["costs"]) == [
        ("TP1", 3793.42), ("TP2", 3790.42),
    ]
    assert advance(signal, {**quote, "ask": 3791}, now + 2, False, signal["costs"])[0][0] == "STOPPED"
    assert advance(signal, {**quote, "ask": 3780}, now + 3, True, signal["costs"]) == []
    pending = worker.new_candidate(s)
    assert advance(pending, None, pending["expiry"], False, pending["costs"])[0][0] == "EXPIRED"
    filled = worker.new_candidate(s)
    advance(filled, quote, now, True, filled["costs"])
    assert advance(filled, quote, filled["holding_until"], False, filled["costs"])[0][0] == "TIMED_OUT"


def test_filled_signal_updates_after_cutoff(db):
    s = sample()
    candidate = worker.new_candidate(s)
    cutoff = config.session(s["now"])["cutoff"]
    candidate.update(created=cutoff - 120, expiry=cutoff, eligible={})
    quote = {**s["quote"], "time": cutoff - 60}
    advance(candidate, quote, cutoff - 60, True, candidate["costs"])
    state = {**s, "now": cutoff + 1,
             "ticks": [{**quote, "time": cutoff + 1, "bid": 3789.77, "ask": 3790.01}]}
    with store.transaction() as data:
        data.put("signal", candidate["id"], candidate)
        worker.track(data, "signal", state, {})
        assert data.all("event")[0]["kind"] == "TP1"
        assert data.all("event")[0]["note"] == "Stop moved to reference"
        assert data.get("signal", candidate["id"])["hits"] == 1


def test_end_to_end_and_duplicate_events(db, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Default demo attempted network access")

    monkeypatch.setattr(worker.httpx, "post", no_network)
    monkeypatch.setattr(news, "download", no_network)
    with TestClient(app) as client:
        tick(0)
        state = client.get("/api/dashboard").json()
        assert state["status"] == "DEMO" and len(state["candles"]) == 250
        assert state["candidate"]["decision"] == "CONFIRM" and state["active"]["status"] == "PENDING"
        assert state["scan"]["closed_at"] == REPLAY_START
        opened = client.post("/api/entry-open", params={"signal": state["active"]["id"]}).json()
        assert opened["valid"] and opened["side"] == "Bid" and len(opened["ratios"]) == 3
        with store.transaction() as data:
            assert data.all("entry_open")[0]["price"] == opened["price"]
        assert "fit" not in state and "profile" not in state
        assert [item["kind"] for item in state["alerts"]] == ["ENTRY"]
        for step in range(1, 9):
            tick(step)
            tick(step)
        latest = client.get("/api/dashboard", params={"after": state["revision"]}).json()
        assert len(latest["candles"]) == 2
        assert latest["active"]["status"] == "COMPLETED"
        assert latest["history"][0]["hits"] == 3
        assert [row["kind"] for row in latest["events"]] == ["ENTRY", "FILLED", "TP1", "TP2", "TP3"]
        assert latest["events"][2]["stop"] == 3793.42
        assert latest["events"][3]["stop"] == 3790.42
        assert len(latest["alerts"]) == 5
        assert len({item["id"] for item in latest["alerts"]}) == 5
        assert client.put("/api/profile", json={}).status_code in (404, 405)


def test_baseline_replay_delay_and_broker_valid_exits():
    source = Replay()
    snapshot = source.read(None, 0, 0)
    _, found = candidates(snapshot["bars"], REPLAY_START, REPLAY_START + 60)
    assert len(found) == 1
    ticks = [source.read(None, step, 0)["quote"] for step in range(9)]
    profile = demo_profile(REPLAY_START)
    costs = demo_spec(REPLAY_START)
    trade = replay(found[0], ticks, 0, [], profile, costs, REPLAY_START + 2000)
    assert trade["outcome"] == "filled" and trade["net_account"] > 0
    assert trade["sizing"]["exit_lots"] == [0.03, 0.03, 0.02]
    assert allocate(0.05, 0.01, 0.01) == [0.02, 0.02, 0.01]
    missed = replay(found[0], ticks, 540, [], {**profile, "equity": 100}, costs, REPLAY_START + 2000)
    assert missed["outcome"] == "missed_after_delay"
    assert missed["sizing"]["reason"] == "Minimum lot exceeds your risk limit"


def test_scalp_waits_for_closed_m1_and_publishes_once(db):
    now = REPLAY_START + 61
    m15 = [dict(time=REPLAY_START + i * 900, open=95 + i, close=96 + i, high=99, low=90)
           for i in range(-4, 0)]
    m5 = [dict(time=REPLAY_START + i * 300, open=98, close=99, high=100, low=98)
          for i in range(-7, 0)]
    m5[-1].update(close=101, high=101.5)
    m1 = [dict(time=REPLAY_START, open=100.1, close=100.5, high=100.7, low=100)]
    quote = dict(time=now, bid=100.40, ask=100.48, available=True)
    snapshot = dict(now=now, bars=m15, frames={"M5": m5, "M1": m1}, quote=quote, ticks=[quote],
                    spec=demo_spec(now), cursor=now, closed=False)
    assert scalp_candidate({**snapshot, "now": now - 2}, m5, m1)[0] is None
    assert scalp_candidate(snapshot, m5, [{**m1[0], "time": REPLAY_START - 60}])[0] is None
    scalp, _ = scalp_candidate(snapshot, m5, m1)
    assert scalp["direction"] == "BUY" and scalp["expiry"] == REPLAY_START + 180
    assert gate(scalp, {**quote, "bid": 100.20}, now)[0] == "WAIT"

    class Source:
        def read(self, *args):
            return snapshot.copy()

    for revision in range(1, 3):
        worker.process(Source(), 0, None, {}, revision)
    with store.transaction() as data:
        saved = data.all("signal")
        assert len(saved) == 1 and saved[0]["strategy"] == "M5 setup / M1 entry"
        entry = [row for row in data.all("alert") if row["kind"] == "ENTRY"]
        assert len(entry) == 1 and "M5/M1 scalp" in entry[0]["title"] and "frame=M1" in entry[0]["url"]


def test_shared_alerts_require_only_push_opt_in(db):
    with TestClient(app) as first, TestClient(app) as second:
        for index, client in enumerate((first, second)):
            subscription = {"endpoint": f"https://fcm.googleapis.com/fcm/send/viewer-{index}",
                            "keys": {"p256dh": "A" * 87, "auth": "B" * 22}}
            assert client.put("/api/push", json=subscription).status_code == 200
        tick(0)
        with store.transaction() as data:
            assert len([a for a in data.all("alert") if a["delivery"] == "queued"]) == 2
        assert second.delete("/api/push").status_code == 200
        for step in range(1, 5):
            tick(step)
        with store.transaction() as data:
            tp1 = [a for a in data.all("alert") if a["kind"] == "TP1"]
            assert sorted(a["delivery"] for a in tp1) == ["preview", "queued"]
        assert first.get("/api/dashboard").json()["alerts"] == second.get("/api/dashboard").json()["alerts"]


def test_news_counterfactual(db):
    for step in range(24, 33):
        tick(step)
    with store.transaction() as data:
        assert not data.all("signal")
        assert data.all("candidate")[0]["calendar_reason"].startswith("Calendar pause")
        assert data.all("shadow")[0]["hits"] == 3


def test_expired_push_is_suppressed(db, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", "unused.pem")
    monkeypatch.setattr(alerts, "webpush", lambda *args, **kwargs: pytest.fail("Expired push sent"))
    with store.transaction() as data:
        data.put("push", "demo", {"endpoint": "fixture"})
    tick(0)
    with store.transaction() as data:
        signal = data.all("signal")[0]
        state = data.get("state", "market")
        data.put("state", "market", {**state, "now": signal["expiry"]})
    alerts.send_pending(signal["expiry"])
    with store.transaction() as data:
        assert next(a for a in data.all("alert") if a["profile"] == "demo")["delivery"] == "expired"


def test_push_transient_failure_retries_once_and_deduplicates(db, monkeypatch):
    from requests import Response

    monkeypatch.setenv("VAPID_PRIVATE_KEY_FILE", "fixture.pem")
    monkeypatch.setenv("VAPID_SUBJECT", "mailto:test@example.com")
    calls = []

    def send(*args, **kwargs):
        calls.append(kwargs["ttl"])
        if len(calls) == 1:
            response = Response()
            response.status_code = 503
            raise alerts.WebPushException("fixture", response=response)

    monkeypatch.setattr(alerts, "webpush", send)
    with store.transaction() as data:
        data.put("push", "demo", {"endpoint": "fixture"})
    tick(0)
    alerts.send_pending(REPLAY_START)
    alerts.send_pending(REPLAY_START)
    assert len(calls) == 1
    with store.transaction() as data:
        state = data.get("state", "market")
        data.put("state", "market", {**state, "now": state["now"] + 16})
    alerts.send_pending(REPLAY_START)
    alerts.send_pending(REPLAY_START)
    with store.transaction() as data:
        assert next(a for a in data.all("alert") if a["profile"] == "demo")["delivery"] == "sent"
    assert len(calls) == 2
