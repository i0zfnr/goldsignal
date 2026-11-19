from goldsignal import news, store, worker, workers
from goldsignal.market import Replay


def test_blank_has_kuro_and_three_lanes():
    state = workers.blank()
    assert state["kuro"]["label"] == "Kuro"
    assert [state["lanes"][lane]["id"] for lane in ("A", "B", "C")] == ["A", "B", "C"]
    for lane in ("A", "B", "C"):
        assert set(state["lanes"][lane]["stages"]) == {"kaze", "mizu", "nanao", "hikari"}


def test_mark_and_snapshot_report_age_per_lane():
    state = workers.blank()
    workers.mark(state, "running", at=100)
    workers.mark_lane(state, "A", "kaze", "setup", reason="Breakout found", at=90)
    report = workers.snapshot(state, now=100, heartbeat=99.5)
    lane_a = next(lane for lane in report["lanes"] if lane["id"] == "A")
    kaze = next(row for row in lane_a["stages"] if row["name"] == "kaze")
    assert kaze["age_seconds"] == 10.0 and kaze["reason"] == "Breakout found"
    assert report["kuro"]["status"] == "running"
    assert report["heartbeat_age"] == 0.5 and report["error"] is None


def test_worker_cycle_records_every_lane(db):
    snapshot = Replay().read(None, 0, 0)
    worker.process(Replay(), 0, None, news.refresh(True, snapshot["now"], {}), 1)
    with store.transaction() as data:
        state = data.get("state", "market", {})
    recorded = state["workers"]
    assert recorded["kuro"]["status"] == "idle"
    assert recorded["lanes"]["A"]["stages"]["kaze"]["status"] in ("setup", "waiting")
    assert recorded["lanes"]["B"]["stages"]["kaze"]["status"] in ("setup", "waiting")
    for stage in ("kaze", "mizu", "nanao", "hikari"):
        assert recorded["lanes"]["C"]["stages"][stage]["status"] == "disabled"
