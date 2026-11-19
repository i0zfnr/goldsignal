"""Tests for trader PnL calendar API."""

from fastapi.testclient import TestClient
from goldsignal.api import app
from goldsignal import store


def test_pnl_crud_lifecycle(db):
    with TestClient(app) as client:
        # Default get on empty store
        res = client.get("/api/pnl?month=2026-11")
        assert res.status_code == 200
        data = res.json()
        assert data["month"] == "2026-11"
        assert data["entries"] == []
        assert data["total_pnl"] == 0
        assert data["total_trades"] == 0

        # Invalid date format on PUT
        bad = client.put("/api/pnl", json={"date": "bad-date", "pnl": 15.0, "trades": 2})
        assert bad.status_code == 422

        # Add valid entry
        put1 = client.put("/api/pnl", json={
            "date": "2026-11-16",
            "pnl": 42.50,
            "trades": 3,
            "note": "2 TP hits, 1 SL",
        })
        assert put1.status_code == 200

        # Add another entry in same month
        put2 = client.put("/api/pnl", json={
            "date": "2026-11-17",
            "pnl": -12.00,
            "trades": 1,
            "note": "Stopped at SL",
        })
        assert put2.status_code == 200

        # Query month
        res2 = client.get("/api/pnl?month=2026-11")
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["entries"]) == 2
        assert abs(data2["total_pnl"] - 30.50) < 1e-6
        assert data2["total_trades"] == 4

        # Delete entry
        del_res = client.delete("/api/pnl?date=2026-11-17")
        assert del_res.status_code == 200

        # Verify deletion
        res3 = client.get("/api/pnl?month=2026-11")
        data3 = res3.json()
        assert len(data3["entries"]) == 1
        assert abs(data3["total_pnl"] - 42.50) < 1e-6
        assert data3["total_trades"] == 3
