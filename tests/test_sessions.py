from datetime import datetime, timezone

from fastapi.testclient import TestClient

from goldsignal import sessions, store
from goldsignal.api import app


def ts(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp()


def test_session_labels_follow_local_windows():
    assert sessions.label(ts(2026, 11, 19, 14)) == "New York"
    assert sessions.label(ts(2026, 11, 19, 9)) == "London"
    assert sessions.label(ts(2026, 11, 19, 1)) == "Tokyo"
    assert sessions.label(ts(2026, 11, 21, 12)) is None


def test_wilson_interval_and_status_thresholds():
    low, high = sessions.wilson(8, 10)
    assert 48 <= low <= 50 and 93 <= high <= 95
    assert sessions.wilson(0, 0) == (None, None)
    assert sessions.status(0, 0) == "No closed trades"
    assert sessions.status(9, 9).startswith("Collecting evidence (9/30)")
    assert sessions.status(40, 32) == "Provisional"
    assert sessions.status(200, 180) == "Historical sample; uncalibrated"
    assert sessions.status(200, 120) == "Historical sample; uncalibrated"


def test_summary_attributes_detection_and_closed_outcome():
    stamp = ts(2026, 11, 19, 14)
    signals = [dict(created=stamp, status="STOPPED", direction="BUY", fill=100,
                    exits=[dict(time=stamp + 60, price=101, fraction=1)], session=None)]
    candidates = [dict(created=stamp, evaluated=stamp, decision="CONFIRM"),
                  dict(created=stamp, evaluated=stamp, decision="WAIT")]
    rows = sessions.summary(signals, candidates, lambda value: True,
                            ["Sydney", "Tokyo", "London", "New York"])
    row = next(item for item in rows if item["session"] == "New York")
    assert row["detected"] == 2 and row["published"] == 1
    assert row["closed"] == 1 and row["wins"] == 1 and row["pips"] == 10.0
    assert row["win_rate"] == 100.0 and row["low"] is not None
    assert all(item["status"] == "No closed trades" for item in rows if item["session"] != "New York")


def test_summary_counts_partial_tp_as_win_while_trade_is_active():
    stamp = ts(2026, 11, 19, 14)
    signals = [dict(created=stamp, status="FILLED", hits=1, direction="BUY", fill=100,
                    exits=[dict(time=stamp + 60, price=101, fraction=1 / 3)], session=None)]
    rows = sessions.summary(signals, [], lambda value: True,
                            ["Sydney", "Tokyo", "London", "New York"])
    row = next(item for item in rows if item["session"] == "New York")
    assert row["closed"] == 1 and row["wins"] == 1 and row["pips"] > 0
    assert row["win_rate"] == 100.0


def test_sessions_endpoint_reports_each_session(db):
    stamp = ts(2026, 11, 19, 14)
    with store.transaction() as data:
        data.put("state", "market", {"now": stamp})
        data.put("signal", "one", {
            "created": stamp, "status": "STOPPED", "direction": "BUY", "fill": 100,
            "exits": [dict(time=stamp + 30, price=99, fraction=1)],
        })
    with TestClient(app) as client:
        report = client.get("/api/sessions?period=day").json()["sessions"]
    assert [row["session"] for row in report] == ["Sydney", "Tokyo", "London", "New York"]
    new_york = next(row for row in report if row["session"] == "New York")
    assert new_york["closed"] == 1 and new_york["losses"] == 1 and new_york["pips"] == -10.0


def test_confirmed_candidate_is_not_a_published_alert():
    stamp = ts(2026, 11, 19, 14)
    rows = sessions.summary([], [dict(created=stamp, decision="CONFIRM")], lambda value: True, ["New York"])
    assert rows[0]["detected"] == 1 and rows[0]["published"] == 0
