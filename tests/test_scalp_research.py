import gzip

import pytest

from goldsignal import scalp_research as research


def test_tick_import_preserves_equal_timestamp_order_and_rejects_bad_rows(tmp_path):
    path = tmp_path / "ticks.csv.gz"
    with gzip.open(path, "wt") as file:
        file.write("time,bid,ask\n1,100,101\n1,99,100\n1,99,100\n2,0,1\n")
    ticks, coverage = research.load_ticks(path)
    assert [tick["bid"] for tick in ticks] == [100, 99, 99]
    assert coverage["exact_duplicates"] == 1 and coverage["invalid"] == 1
    with gzip.open(path, "wt") as file:
        file.write("time,bid,ask\n2,100,101\n1,99,100\n")
    with pytest.raises(ValueError, match="ascending"):
        research.load_ticks(path)


def test_actionable_quote_and_account_risk_gate(monkeypatch):
    monkeypatch.setattr(research, "ny_window", lambda stamp: {"open": True})
    item = dict(direction="BUY", close_time=100, expiry=200, reference=100,
                entry=[99.5, 100], initial_stop=98, stop=98, targets=[102, 103, 104], hold_seconds=1800)
    ticks = [dict(time=t, bid=b, ask=a, available=True) for t, b, a in
             [(100, 99.5, 99.8), (105, 99.6, 99.9), (130, 100.2, 100.5), (140, 103.9, 104.1),
              (141, 104.2, 104.4)]]
    costs = dict(symbol=research.SYMBOL, account_currency="USD", units_per_currency=1, conversion=1,
                 minimum=.01, step=.01, maximum=10, contract=100, commission=0, slippage=.1,
                 margin_rate=.01, max_age=1, demo=False)
    times = [tick["time"] for tick in ticks]
    fast = research.execute(item, ticks, times, 5, [], costs)
    assert fast["outcome"] == "filled" and fast["net"] > 0
    slow = research.execute(item, ticks, times, 30, [], costs)
    assert slow["outcome"] == "missed"
    profile = dict(symbol=research.SYMBOL, currency="USD", units_per_currency=1,
                   equity=100, free_margin=100, risk_pct=1, daily_loss_pct=3, exit_policy="split", max_age=1)
    blocked = research.execute(item, ticks, times, 5, [], costs, profile)
    assert blocked["outcome"] == "risk_blocked" and "Minimum lot" in blocked["reason"]
    assert blocked["alert_time"] is None and blocked["blocked_stage"] == "before_submission"
    assert blocked["action_gate"]["decision"] == "CONFIRM"
    assert blocked["volume_audit"]["minimum_lot_loss"] > blocked["volume_audit"]["budget"]
    split = research.execute(item, ticks, times, 5, [], costs, {**profile, "equity": 300, "free_margin": 300})
    assert split["outcome"] == "risk_blocked" and "split" in split["reason"]
    assert split["volume_audit"]["minimum_lot_loss"] <= split["volume_audit"]["budget"]
    assert split["volume_audit"]["three_exit_risk_fits"] is False


def test_publication_check_does_not_wait_for_a_later_reentry(monkeypatch):
    monkeypatch.setattr(research, "gate", lambda item, quote, now: (
        ("CONFIRM", "inside") if quote["bid"] < 101 else ("WAIT", "outside")))
    signal = dict(created=100)
    ticks = [dict(time=130, bid=102), dict(time=140, bid=100)]
    assert research.publication_check(signal, ticks, 30)["inside"] is False


def test_closed_slice_excludes_forming_and_future_candles():
    frames = {"M1": [{"time": 0}, {"time": 60}, {"time": 120}]}
    closes = {"M1": [60, 120, 180]}
    assert research.closed_slice(frames, closes, "M1", 119, 10) == [{"time": 0}]
    assert research.closed_slice(frames, closes, "M1", 120, 1) == [{"time": 60}]


def test_risk_rejections_are_not_counted_as_published_alerts():
    rows = [dict(outcome="risk_blocked", reason="minimum lot", alert_time=100),
            dict(outcome="missed", reason="outside", alert_time=110)]
    result = research.summary(rows, 1)
    assert result["alerts"] == 1
    assert result["outcomes"] == {"risk_blocked": 1, "missed": 1}


def test_late_eligibility_does_not_erase_phone_reaction_delay(monkeypatch):
    monkeypatch.setattr(research, "ny_window", lambda stamp: {"open": True})
    item = dict(direction="BUY", close_time=100, expiry=180, reference=100,
                entry=[99.5, 100], initial_stop=98, stop=98, targets=[102, 103, 104], hold_seconds=1800)
    ticks = [dict(time=t, bid=b, ask=a, available=True) for t, b, a in
             [(100, 100.2, 100.5), (120, 99.6, 99.9), (123, 100.2, 100.5),
              (125, 100.2, 100.5), (130, 99.6, 99.9), (140, 104, 104.2)]]
    costs = dict(contract=100, conversion=1, commission=0, slippage=.1)
    result = research.execute(item, ticks, [row["time"] for row in ticks], 5, [], costs)
    assert result["outcome"] == "missed"
    assert result["timing"]["submission"] == 120
    assert result["timing"]["action_scheduled"] == 125
    assert result["timing"]["action_quote"]["time"] == 125
    assert "outside" in result["reason"]
    # Reproduce the original failure: its max(confirmation + delay, eligibility) fills at 120.
    assert research.execute_legacy(item, ticks, [row["time"] for row in ticks], 5, [], costs)["outcome"] == "filled"


def test_processing_rechecks_submission_and_review_is_counted_once(monkeypatch):
    monkeypatch.setattr(research, "ny_window", lambda stamp: {"open": True})
    item = dict(direction="BUY", close_time=100, expiry=140, reference=100,
                entry=[99.5, 100], initial_stop=98, stop=98, targets=[102, 103, 104], hold_seconds=1800)
    ticks = [dict(time=t, bid=b, ask=a, available=True) for t, b, a in
             [(100, 99.6, 99.9), (110, 99.6, 99.9), (112, 100.2, 100.5), (140, 104, 104.2)]]
    result = research.execute(item, ticks, [row["time"] for row in ticks], 5, [], {}, review=10, processing=2)
    assert result["alert_time"] is None
    assert result["timing"]["review_finished"] == 110
    assert result["timing"]["submission_attempts"][0]["checked"] == 112
    assert result["timing"]["submission_attempts"][0]["result"] == "WAIT"
