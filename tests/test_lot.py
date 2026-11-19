from fastapi.testclient import TestClient

from goldsignal.api import app


def post(body):
    with TestClient(app) as client:
        return client.post("/api/lot-size", json=body)


def test_lot_size_floors_to_broker_step(db):
    response = post({"capital": 1000, "risk_pct": 1, "stop_pips": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["stop_price"] == 1.0 and body["loss_per_lot_unit"] == 110.0
    assert body["lot"] == 0.09 and body["risk_cash"] == 10.0


def test_lot_size_reports_minimum_capital_when_unaffordable(db):
    body = post({"capital": 100, "risk_pct": 1, "stop_pips": 10}).json()
    assert body["lot"] == 0.0
    assert body["min_capital"] == 110.0
    assert body["warnings"] and "minimum" in body["warnings"][0].lower()


def test_lot_size_scales_with_stop_distance(db):
    body = post({"capital": 1000, "risk_pct": 1, "stop_pips": 3}).json()
    assert body["lot"] == 0.25 and body["loss_per_lot_unit"] == 40.0


def test_lot_size_rejects_invalid_input(db):
    assert post({"capital": 0, "risk_pct": 1, "stop_pips": 10}).status_code == 422
