"""Named pipeline stages. Logical workers in one process: one feed, one writer."""

STAGES = ("kaze", "mizu", "nanao", "hikari")
STAGE_ROLES = {
    "kaze": ("Kaze", "Market analysis"),
    "mizu": ("Mizu", "Risk and economics"),
    "nanao": ("Nanao", "AI confirmation"),
    "hikari": ("Hikari", "Delivery"),
}
LANES = (
    ("A", "Strategy A · M15 baseline"),
    ("B", "Strategy B · M5/M1 scalping"),
    ("C", "Strategy C · reserved"),
)


def _row(name, label, role):
    return dict(name=name, label=label, role=role, status="idle", reason=None, at=None)


def blank():
    state = {"kuro": _row("kuro", "Kuro", "Feed and orchestration"), "lanes": {}}
    for lane, label in LANES:
        state["lanes"][lane] = dict(id=lane, label=label, stages={
            stage: _row(stage, *STAGE_ROLES[stage]) for stage in STAGES})
    return state


def mark(workers, status, reason=None, at=None):
    row = workers.get("kuro")
    if row is not None:
        row.update(status=status, reason=reason, at=at)
    return workers


def mark_lane(workers, lane, stage, status, reason=None, at=None):
    row = workers.get("lanes", {}).get(lane, {}).get("stages", {}).get(stage)
    if row is not None:
        row.update(status=status, reason=reason, at=at)
    return workers


def _aged(row, now):
    age = round(now - row["at"], 1) if row.get("at") else None
    return {**row, "age_seconds": age}


def snapshot(workers, now, heartbeat, error=None):
    state = workers or blank()
    kuro = state.get("kuro", _row("kuro", "Kuro", "Feed and orchestration"))
    lanes = []
    for lane, label in LANES:
        stages = state.get("lanes", {}).get(lane, {}).get("stages", {})
        lanes.append({"id": lane, "label": label,
                      "stages": [_aged(stages.get(stage, _row(stage, *STAGE_ROLES[stage])), now)
                                 for stage in STAGES]})
    return {"kuro": _aged(kuro, now), "lanes": lanes,
            "heartbeat_age": round(now - heartbeat, 1) if heartbeat else None, "error": error}
