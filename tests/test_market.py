from types import SimpleNamespace

import pytest

from goldsignal import market
from goldsignal.worker import failure_message


def build():
    source = object.__new__(market.MT5)
    shutdowns = []
    source.mt5 = SimpleNamespace(shutdown=lambda: shutdowns.append(1))
    source.connected = True
    return source, shutdowns


def test_read_reconnects_once_after_ipc_failure(monkeypatch):
    source, shutdowns = build()
    calls = []

    def fake(self, cursor, step, now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("MT5 connection or quote unavailable: (-10001, 'IPC send failed')")
        return "snapshot"

    monkeypatch.setattr(market.MT5, "_read", fake)
    monkeypatch.setattr(market, "utc_now", lambda: 105)
    assert source.read(None, 0, 100) == "snapshot"
    assert len(calls) == 2 and source.connected is False and shutdowns == [1]
    assert calls == [100, 105]


def test_read_propagates_when_reconnect_also_fails(monkeypatch):
    source, _ = build()
    calls = []

    def always(self, cursor, step, now):
        calls.append(1)
        raise RuntimeError("still down")

    monkeypatch.setattr(market.MT5, "_read", always)
    with pytest.raises(RuntimeError, match="still down"):
        source.read(None, 0, 100)
    assert len(calls) == 2


def test_read_does_not_retry_non_runtime_failures(monkeypatch):
    source, shutdowns = build()
    calls = []

    def invalid(self, cursor, step, now):
        calls.append(1)
        raise ValueError("invalid broker data")

    monkeypatch.setattr(market.MT5, "_read", invalid)
    with pytest.raises(ValueError, match="invalid broker data"):
        source.read(None, 0, 100)
    assert len(calls) == 1 and shutdowns == []


def test_admin_failure_message_keeps_mt5_cause_without_generic_payloads():
    message = failure_message(RuntimeError("MT5 connection or quote unavailable: (-10001, 'IPC send failed')\nprivate payload"))
    assert "-10001" in message and "IPC send failed" in message
    assert "private payload" not in message
    generic = failure_message(ValueError("token=fixture-secret"))
    assert "ValueError" in generic and "fixture-secret" not in generic
