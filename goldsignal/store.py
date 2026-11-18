from contextlib import contextmanager

from sqlalchemy import JSON, BigInteger, Column, Integer, MetaData, String, Table, create_engine, select

from .config import DB, MODE, SYMBOL

engine = create_engine(DB, pool_pre_ping=True)
metadata = MetaData()
records = Table(
    "records", metadata,
    Column("scope", String(100), primary_key=True),
    Column("kind", String(24), primary_key=True),
    Column("id", String(128), primary_key=True),
    Column("payload", JSON, nullable=False),
)
schema = Table("schema_versions", metadata, Column("version", Integer, primary_key=True))
candles = Table(
    "candles", metadata, Column("scope", String(100), primary_key=True),
    Column("time", BigInteger, primary_key=True), Column("revision", BigInteger, nullable=False, index=True),
    Column("payload", JSON, nullable=False),
)
scope = f"{MODE}:{SYMBOL}"


def migrate():
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.scalar(select(schema.c.version).where(schema.c.version == 1)) is None:
            conn.execute(schema.insert().values(version=1))


class Store:
    def __init__(self, connection):
        self.conn = connection

    def where(self, kind, key=None):
        match = (records.c.scope == scope) & (records.c.kind == kind)
        return match if key is None else match & (records.c.id == str(key))

    def get(self, kind, key, fallback=None):
        value = self.conn.scalar(select(records.c.payload).where(self.where(kind, key)))
        return fallback if value is None else value

    def all(self, kind):
        return list(self.conn.scalars(select(records.c.payload).where(self.where(kind))))

    def items(self, kind):
        return self.conn.execute(select(records.c.id, records.c.payload).where(self.where(kind))).all()

    def put(self, kind, key, value):
        result = self.conn.execute(records.update().where(self.where(kind, key)).values(payload=value))
        if result.rowcount == 0:
            self.conn.execute(records.insert().values(scope=scope, kind=kind, id=str(key), payload=value))

    def delete(self, kind, key):
        self.conn.execute(records.delete().where(self.where(kind, key)))

    def chart(self, after=None, frame="M15", limit=250):
        candle_scope = scope if frame == "M15" else f"{scope}:{frame}"
        query = select(candles.c.payload).where(candles.c.scope == candle_scope)
        if after is not None:
            return list(self.conn.scalars(query.where(candles.c.revision > after).order_by(candles.c.time)))
        return list(reversed(list(self.conn.scalars(query.order_by(candles.c.time.desc()).limit(limit)))))

    def save_bars(self, bars, revision, frame="M15"):
        if not bars:
            return
        candle_scope = scope if frame == "M15" else f"{scope}:{frame}"
        query = select(candles.c.time, candles.c.payload).where(
            candles.c.scope == candle_scope, candles.c.time.between(bars[0]["time"], bars[-1]["time"]),
        )
        current = dict(self.conn.execute(query).all())
        new = []
        for bar in bars:
            stamp = bar["time"]
            if stamp not in current:
                new.append(dict(scope=candle_scope, time=stamp, revision=revision, payload=bar))
            elif bar != current[stamp]:
                self.conn.execute(candles.update().where(candles.c.scope == candle_scope, candles.c.time == stamp)
                                  .values(revision=revision, payload=bar))
        if new:
            self.conn.execute(candles.insert(), new)


@contextmanager
def transaction():
    with engine.begin() as conn:
        yield Store(conn)


if __name__ == "__main__":
    migrate()
