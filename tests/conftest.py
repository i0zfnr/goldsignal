import os

import pytest
from sqlalchemy import create_engine

os.environ["MARKET_SOURCE"] = "demo"
os.environ["BROKER_HOURS"] = ""
os.environ["SIGNAL_REVIEW_MODE"] = "rules"
os.environ["ADMIN_PASSWORD_HASH"] = ""
os.environ["ADMIN_EMAIL"] = ""
os.environ["GOLDSIGNAL_SECRET_KEY"] = ""


@pytest.fixture
def db(tmp_path, monkeypatch):
    from goldsignal import store

    engine = create_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    monkeypatch.setattr(store, "engine", engine)
    store.migrate()
    yield
    engine.dispose()
