from goldsignal import scalp_grid as grid
from goldsignal import scalp_research as replay
import json
from types import SimpleNamespace
import pytest


def test_grid_is_canonical_distinct_and_bounded():
    configs = grid.configurations()
    assert len(configs) == 880
    assert len({row["id"] for row in configs}) == 880
    assert len(grid.configurations(17)) == 17
    assert all(row["lot"] == .01 and row["exit_policy"] == "single" for row in configs)
    assert not any(row["family"] == "trend_pullback" and row["confirmation"] == "close_break" for row in configs)


def test_fixed_minimum_lot_uses_executable_side_costs_and_separate_partial_constraint():
    item = dict(direction="BUY", initial_stop=99.3, entry=[99.5, 100])
    quote = dict(bid=99.9, ask=100)
    costs = dict(minimum=.01, step=.01, contract=100, conversion=1, commission=7,
                 slippage=.1, margin_rate=.0005)
    profile = dict(equity=100, free_margin=100, units_per_currency=1, risk_pct=1)
    fit, volume = replay.quote_risk(item, quote, costs, profile, 100, .01, "single")
    assert fit["decision"] == "FIT"
    assert abs(fit["loss"] - .87) < 1e-9
    partial, _ = replay.quote_risk(item, quote, costs, profile, 100, .01, "split")
    assert "Invalid exit volume" in partial["reason"]
    blocked, _ = replay.quote_risk(item, {**quote, "ask": 100.2}, costs, profile, 100, .01, "single")
    assert blocked["reason"] == "Minimum lot exceeds your risk limit"
    margin, _ = replay.quote_risk(item, quote, costs, {**profile, "free_margin": .001}, 100, .01, "single")
    assert margin["reason"] == "Insufficient margin"
    assert volume["three_exit_minimum_lots"] == .03


def test_zero_fills_never_pass_selection():
    result = dict(completed=0, mean_net=None, closed_trade_drawdown=0,
                  worst_losing_streak=0, executable_per_session=0)
    assert not grid.passes(result, 0)


def test_action_risk_is_rechecked_after_an_alert_was_submitted(monkeypatch):
    monkeypatch.setattr(replay, "ny_window", lambda stamp: {"open": True})
    item = dict(direction="BUY", close_time=100, expiry=180, reference=100.2,
                entry=[99.5, 100.2], initial_stop=99.3, stop=99.3, targets=[101])
    ticks = [dict(time=100, bid=99.9, ask=100, available=True),
             dict(time=105, bid=100.1, ask=100.2, available=True)]
    costs = dict(minimum=.01, step=.01, contract=100, conversion=1, commission=7,
                 slippage=.1, margin_rate=.0005)
    profile = dict(equity=100, free_margin=100, units_per_currency=1, risk_pct=1)
    result = replay.execute(item, ticks, [100, 105], 5, [], costs, profile,
                            fixed_lot=.01, exit_policy="single")
    assert result["submission_risk"]["decision"] == "FIT"
    assert result["outcome"] == "risk_blocked" and result["blocked_stage"] == "action"
    assert result["timing"]["submission"] == 100
    assert replay.summary([result], 1)["alerts"] == 1


def test_prospective_run_refuses_to_replace_missing_phone_measurements(tmp_path):
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "manifest.json").write_text(json.dumps(dict(symbol=replay.SYMBOL, broker_hours=replay.BROKER_HOURS)))
    (archive / "candles.json").write_text("{}")
    study = tmp_path / "study.json"
    study.write_text(json.dumps(dict(measured_entry_pairs_required=20)))
    timing = tmp_path / "timing.json"
    timing.write_text(json.dumps(dict(usable_for_grid=False, paired_count=0)))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="Insufficient real"):
        grid.run(SimpleNamespace(archive=archive, output=output, limit=960, study=study, timing=timing))
    assert not output.exists()


def test_timing_fit_cannot_use_validation_or_final_opens(tmp_path):
    from datetime import datetime, timedelta
    from goldsignal.config import NY
    dates = []
    day = datetime(2026, 11, 19)
    while len(dates) < 40:
        if day.weekday() < 5:
            dates.append(day.date().isoformat())
        day += timedelta(days=1)
    archive = tmp_path / "archive"
    archive.mkdir()
    (archive / "manifest.json").write_text(json.dumps(dict(symbol=replay.SYMBOL, broker_hours=replay.BROKER_HOURS,
                                                          sessions=[dict(day=day) for day in dates])))
    (archive / "candles.json").write_text("{}")
    study = tmp_path / "study.json"
    study.write_text(json.dumps(dict(measured_entry_pairs_required=20, configurations=grid.configurations(),
                                    criteria=grid.CRITERIA, start=dates[0], development_sessions=20, validation_sessions=[10, 10])))
    timing = tmp_path / "timing.json"
    timing.write_text(json.dumps(dict(usable_for_grid=True, paired_count=20,
                                     pairs=[dict(submitted_at=datetime.fromisoformat(dates[20 + i % 3]).replace(hour=9, tzinfo=NY).timestamp()) for i in range(20)])))
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="exclude validation and final"):
        grid.run(SimpleNamespace(archive=archive, output=output, limit=960, study=study, timing=timing))
    assert not output.exists()
