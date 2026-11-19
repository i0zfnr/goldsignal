"""Tests for Strategy B v2 (Katana-inspired scalping logic)."""

import pytest
from goldsignal import scalp_v2 as b2


def make_bar(time, open_, high, low, close):
    return dict(time=time, open=float(open_), high=float(high), low=float(low), close=float(close))


def test_confirmed_swing_timing():
    # 5 bars: i=0, 1, 2, 3, 4. Center at i=2 (time 1800)
    # High at i=2 (price 105), others have lower high.
    # Swing at i=2 is confirmed when the second candle on the right (i=4) closes.
    # For M15 (period 900), i=4 starts at 3600, closes at 3600 + 900 = 4500.
    bars = [
        make_bar(0, 100, 101, 99, 100),
        make_bar(900, 100, 102, 99, 101),
        make_bar(1800, 101, 105, 100, 104),  # Swing high here
        make_bar(2700, 104, 102, 98, 99),
        make_bar(3600, 99, 100, 97, 98),
    ]
    sw = b2.swings(bars, size=2, period=900)
    highs = [s for s in sw if s["kind"] == "high"]
    assert len(highs) == 1
    assert highs[0]["price"] == 105
    assert highs[0]["time"] == 1800
    # Available ONLY when second candle on right closes (3600 + 900 = 4500)
    assert highs[0]["confirmed"] == 4500

    # For H1 (period 3600), second candle on right at 3600*4 closes at 3600*4 + 3600 = 18000
    h1_bars = [
        make_bar(i * 3600, 100, 101 if i != 2 else 110, 99, 100)
        for i in range(5)
    ]
    h1_sw = b2.swings(h1_bars, size=2, period=3600)
    assert h1_sw[0]["confirmed"] == 4 * 3600 + 3600


def test_structure_classification_bias():
    # Bullish: last two confirmed highs rise AND last two confirmed lows rise
    # Let's create a series of swings
    # Low1 at 100, High1 at 110, Low2 at 102, High2 at 115
    bull_bars = []
    # Bar 0, 1 (left of L1)
    t = 0
    bull_bars.append(make_bar(t, 104, 105, 103, 104)); t += 900
    bull_bars.append(make_bar(t, 104, 105, 102, 103)); t += 900
    # L1 at t (low=100)
    bull_bars.append(make_bar(t, 103, 104, 100, 103)); t += 900
    # right of L1 / left of H1
    bull_bars.append(make_bar(t, 103, 106, 102, 105)); t += 900
    bull_bars.append(make_bar(t, 105, 108, 104, 107)); t += 900
    # H1 at t (high=110)
    bull_bars.append(make_bar(t, 107, 110, 106, 109)); t += 900
    # right of H1 / left of L2
    bull_bars.append(make_bar(t, 109, 108, 104, 105)); t += 900
    bull_bars.append(make_bar(t, 105, 106, 103, 104)); t += 900
    # L2 at t (low=102) -> 102 > 100 (rising low!)
    bull_bars.append(make_bar(t, 104, 105, 102, 104)); t += 900
    # right of L2 / left of H2
    bull_bars.append(make_bar(t, 104, 108, 103, 107)); t += 900
    bull_bars.append(make_bar(t, 107, 112, 106, 111)); t += 900
    # H2 at t (high=115) -> 115 > 110 (rising high!)
    bull_bars.append(make_bar(t, 111, 115, 110, 114)); t += 900
    # right of H2 (2 bars)
    bull_bars.append(make_bar(t, 114, 113, 109, 110)); t += 900
    bull_bars.append(make_bar(t, 110, 111, 108, 109)); t += 900

    b = b2.bias(bull_bars, period=900)
    assert b["direction"] == "bullish"
    assert b["highs"][1] > b["highs"][0]
    assert b["lows"][1] > b["lows"][0]


def test_m15_zone_creation_and_no_lookahead():
    # Setup: 20 previous bars with small body (median body ~ 1.0)
    # Swing low confirmed earlier at 2650.0
    # Bearish displacement bar: body >= 1.5 * median, closes below 2650.0
    # Preceded by bullish candle among 6 bars -> defines zone bounds
    bars = []
    t = 0
    # 5 bars around swing low at index 2
    bars.append(make_bar(t, 2655, 2656, 2654, 2655)); t += 900
    bars.append(make_bar(t, 2655, 2656, 2653, 2654)); t += 900
    bars.append(make_bar(t, 2654, 2655, 2650, 2652)); t += 900  # Swing low = 2650
    bars.append(make_bar(t, 2652, 2654, 2651, 2653)); t += 900
    bars.append(make_bar(t, 2653, 2655, 2652, 2654)); t += 900  # Confirmed here (t=3600+900=4500)

    # Add 18 more normal bars to exceed 20 bar median window
    for _ in range(18):
        bars.append(make_bar(t, 2654, 2655, 2653, 2654)); t += 900

    # Bullish candle before displacement (source candle: high=2656, low=2652)
    source_idx = len(bars)
    bars.append(make_bar(t, 2652, 2656, 2651, 2655)); t += 900

    # Bearish displacement candle: closes at 2645 (below swing low 2650), body = 9.0 (>> 1.5 * 1.0)
    disp_time = t
    bars.append(make_bar(t, 2654, 2655, 2644, 2645)); t += 900

    # Before displacement bar completes (now < disp_time + 900): no displacement sell zone
    assert len([z for z in b2.zones(bars, now=disp_time + 100) if z["direction"] == "SELL"]) == 0

    # When displacement completes (now >= disp_time + 900): zone is created!
    z = [x for x in b2.zones(bars, now=disp_time + 900) if x["direction"] == "SELL"]
    assert len(z) == 1
    sell_zone = z[0]
    assert sell_zone["direction"] == "SELL"
    assert sell_zone["top"] == 2656
    assert sell_zone["bottom"] == 2651
    assert sell_zone["created"] == disp_time + 900
    assert sell_zone["invalidated"] is None

    # Test zone invalidation: later candle closes above top (2656)
    later_t = t
    bars.append(make_bar(later_t, 2655, 2660, 2654, 2658)); later_t += 900
    z_after = [x for x in b2.zones(bars, now=later_t) if x["direction"] == "SELL"]
    assert z_after[0]["invalidated"] == later_t


def test_buy_zone_creation_and_invalidation():
    bars = []
    t = 0
    # Swing high at index 2 = 2660
    bars.append(make_bar(t, 2650, 2652, 2649, 2651)); t += 900
    bars.append(make_bar(t, 2651, 2654, 2650, 2653)); t += 900
    bars.append(make_bar(t, 2653, 2660, 2652, 2658)); t += 900  # Swing high = 2660
    bars.append(make_bar(t, 2658, 2659, 2655, 2656)); t += 900
    bars.append(make_bar(t, 2656, 2657, 2653, 2654)); t += 900  # Confirmed here

    # Fill median window
    for _ in range(18):
        bars.append(make_bar(t, 2654, 2655, 2653, 2654)); t += 900

    # Bearish source candle (high=2658, low=2652)
    bars.append(make_bar(t, 2657, 2658, 2652, 2653)); t += 900

    # Bullish displacement candle: closes at 2665 (> swing high 2660)
    disp_time = t
    bars.append(make_bar(t, 2654, 2666, 2653, 2665)); t += 900

    z = [x for x in b2.zones(bars, now=disp_time + 900) if x["direction"] == "BUY" and x.get("broken_at") == 2665]
    assert len(z) == 1
    buy_zone = z[0]
    assert buy_zone["direction"] == "BUY"
    assert buy_zone["top"] == 2658
    assert buy_zone["bottom"] == 2652

    # Invalidate by candle closing below lower boundary (2652)
    bars.append(make_bar(t + 900, 2653, 2654, 2648, 2650))
    z_inv = [x for x in b2.zones(bars, now=t + 1800) if x["id"] == buy_zone["id"]]
    assert z_inv[0]["invalidated"] == t + 1800


def test_m5_rejection_and_m1_confirmation():
    zone = dict(
        id="z_SELL_1000", direction="SELL", top=2656.0, bottom=2651.0,
        created=10000, expired=50000,
    )
    # M5 candle after zone creation: overlaps zone (high=2654, low=2648) and closes below bottom (close=2649)
    m5_bars = [
        make_bar(10200, 2653, 2654, 2648, 2649),  # closes at 10500
    ]
    rejections = b2._find_rejections(m5_bars, zone, now=10600)
    assert len(rejections) == 1
    rej = rejections[0]
    assert rej["time"] == 10500
    assert rej["high"] == 2654.0

    # M1 confirmation within 5 minutes (10500 to 10800):
    # Needs 3 prior M1 bars, then 1 bar closing below min of preceding 3
    m1_bars = [
        make_bar(10380, 2650, 2651, 2649, 2650),
        make_bar(10440, 2650, 2651, 2649, 2649.5),
        make_bar(10500, 2649.5, 2650, 2648.5, 2649),  # min low = 2648.5
        # Trigger candle: close=2648.0 (< 2648.5)
        make_bar(10560, 2649, 2649.5, 2647.5, 2648.0),
    ]
    trig = b2._confirmation(m1_bars, rej, now=10700, direction="SELL")
    assert trig is not None
    assert trig["close"] == 2648.0
    assert trig["time"] == 10560 + 60

    # Candidate calculation:
    # ref = 2648.0, stop = rej["high"] (2654.0) + 0.10 buffer = 2654.10
    # risk = 2654.10 - 2648.00 = 6.10
    # band: toward better price (higher for SELL) = 2648.00 to 2648.00 + 0.25 * 6.10 = 2649.52
    cand = b2._candidate(zone, rej, trig, dict(now=10700), m5_bars)
    assert cand["direction"] == "SELL"
    assert cand["reference"] == 2648.0
    assert cand["initial_stop"] == 2654.10
    assert cand["stop"] == 2654.10
    assert cand["entry"][0] == 2648.0
    assert cand["entry"][1] == 2649.53  # sorted band
    assert len(cand["targets"]) == 3  # 1.0R, 1.5R, 2.0R (TP1, TP2, TP3)
    # Deduplication ID check:
    assert cand["id"] == f"b2_{zone['id']}_{rej['time']}_SELL"


def test_neutral_h1_blocks_entry_ready():
    # Test M15 mode:
    snapshot = dict(
        now=20000, symbol="XAUUSD.vx", quote=dict(bid=2650, ask=2650.3),
        bars=[], frames=dict(H1=[], M5=[], M1=[]),
    )
    report_m15 = b2.analyze(snapshot, mtf="M15")
    assert report_m15["next_step"] in ("WAITING FOR M15 DIRECTION", "WATCH BUY", "WATCH SELL")
    assert report_m15["candidate"] is None

    # Test H1 mode:
    report_h1 = b2.analyze(snapshot, mtf="H1")
    assert report_h1["next_step"] in ("WAITING FOR H1 DIRECTION", "WATCH BUY", "WATCH SELL")
    assert report_h1["candidate"] is None


def test_strategy_b_config_endpoint(db, monkeypatch):
    from fastapi.testclient import TestClient
    from cryptography.fernet import Fernet
    from goldsignal.api import app
    from goldsignal.access import password_hash

    password = "fixture-admin-password"
    salt = "00112233445566778899aabbccddeeff"
    monkeypatch.setenv("ADMIN_EMAIL", "fixture@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", f"{salt}:{password_hash(password, salt)}")
    monkeypatch.setenv("GOLDSIGNAL_SECRET_KEY", Fernet.generate_key().decode())

    with TestClient(app) as operator, TestClient(app) as viewer:
        # Non-admin cannot modify setting
        assert viewer.put("/api/admin/strategy-b/config", json={"mtf": "H1"}).status_code == 403

        # Admin logs in
        login = operator.post("/api/auth/admin", json={"email": "fixture@example.com", "credential": password})
        assert login.status_code == 200

        # Admin reads setting
        res = operator.get("/api/strategy-b/config")
        assert res.status_code == 200
        assert res.json()["mtf"] in ("M15", "H1")

        # Admin toggles to H1
        put_h1 = operator.put("/api/admin/strategy-b/config", json={"mtf": "H1"})
        assert put_h1.status_code == 200
        assert put_h1.json()["mtf"] == "H1"

        # Verify get returns H1
        res_h1 = operator.get("/api/strategy-b/config")
        assert res_h1.json()["mtf"] == "H1"

        # Admin toggles back to M15
        put_m15 = operator.put("/api/admin/strategy-b/config", json={"mtf": "M15"})
        assert put_m15.status_code == 200
        assert put_m15.json()["mtf"] == "M15"


def test_entry_grade_levels():
    # 4/4 points -> A+
    zone_high = {"direction": "SELL", "mitigated": None, "power": 9}
    rej_clean = {"high": 3720.0, "low": 3716.0, "close": 3717.0}  # wick = 3720-3717 = 3.0 / 4.0 = 75%
    trig = {"close": 3718.5}
    snap = {"quote": {"bid": 3718.0, "ask": 3718.25}}
    grade_aplus = b2.calculate_grade(zone_high, rej_clean, trig, snap, risk=1.5, mtf_aligned=True)
    assert grade_aplus == "A+"

    # 3/4 points -> A (e.g. not MTF aligned)
    grade_a = b2.calculate_grade(zone_high, rej_clean, trig, snap, risk=1.5, mtf_aligned=False)
    assert grade_a == "A"

    # 2/4 points -> B+
    zone_tested = {"direction": "SELL", "mitigated": 12345, "power": 6}
    grade_bplus = b2.calculate_grade(zone_tested, rej_clean, trig, snap, risk=1.5, mtf_aligned=False)
    assert grade_bplus == "B+"

    # 1/4 points -> B
    grade_b = b2.calculate_grade(zone_tested, {"high": 3720, "low": 3719, "close": 3719.9}, trig, snap, risk=3.5, mtf_aligned=False)
    assert grade_b == "B"

