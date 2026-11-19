"""Named pipeline stages. Logical workers, not separate processes: one feed, one writer."""

ROSTER = (
    ("kuro", "Kuro", "Feed and orchestration"),
    ("kaze", "Kaze", "Market analysis"),
    ("mizu", "Mizu", "Risk and economics"),
    ("nanao", "Nanao", "AI confirmation"),
    ("hikari", "Hikari", "Delivery"),
)


def blank():
    return {name: dict(name=name, label=label, role=role, status="idle", reason=None, at=None)
            for name, label, role in ROSTER}


def mark(workers, name, status, reason=None, at=None):
    row = workers.get(name)
    if row is not None:
        row.update(status=status, reason=reason, at=at)
    return workers


def snapshot(workers, now, heartbeat, error=None):
    rows = []
    for name, label, role in ROSTER:
        row = (workers or {}).get(name, dict(name=name, label=label, role=role,
                                            status="unknown", reason=None, at=None))
        age = round(now - row["at"], 1) if row.get("at") else None
        rows.append({**row, "age_seconds": age})
    return {"workers": rows, "heartbeat_age": round(now - heartbeat, 1) if heartbeat else None,
            "error": error}
