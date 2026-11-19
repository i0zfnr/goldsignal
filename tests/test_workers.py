from goldsignal import news, store, worker, workers
from goldsignal.market import Replay


def test_blank_and_mark_track_stage_state():
    state = workers.blank()
    assert set(state) == {"kuro", "kaze", "mizu", "nanao", "hikari"}
    workers.mark(state, "kaze", "setup", reason="Breakout found", at=100)
    assert state["kaze"]["status"] == "setup" and state["kaze"]["reason"] == "Breakout found"


def test_snapshot_reports_age_and_missing_stage():
    state = workers.blank()
    workers.mark(state, "kaze", "waiting", at=90)
    report = workers.snapshot(state, now=100, heartbeat=99.5)
    rows = {row["name"]: row for row in report["workers"]}
    assert rows["kaze"]["age_seconds"] == 10.0
    assert rows["mizu"]["status"] == "idle"
    assert report["heartbeat_age"] == 0.5 and report["error"] is None


def test_worker_cycle_records_every_stage(db):
    snapshot = Replay().read(None, 0, 0)
    worker.process(Replay(), 0, None, news.refresh(True, snapshot["now"], {}), 1)
    with store.transaction() as data:
        state = data.get("state", "market", {})
    recorded = {row["name"]: row for row in state["workers"].values()}
    assert {"kuro", "kaze", "mizu", "nanao", "hikari"} <= set(recorded)
    assert recorded["kuro"]["status"] == "idle"
    assert recorded["kaze"]["status"] in ("setup", "waiting")
    assert recorded["nanao"]["status"] in ("disabled", "waiting", "CONFIRM", "WAIT", "REJECT")
    assert recorded["hikari"]["status"] in ("published", "waiting")
