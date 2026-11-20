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
    ("B", "Strategy B · Liquidity scalp"),
    ("C", "Strategy C · Asian range fade"),
)
CORE_ROLES = {
    "kuro": ("Kuro", "Feed and orchestration"),
    "hayate": ("Hayate", "Parallel compute engine"),
    "ryu": ("Ryu", "Zero-latency dispatcher"),
    "shinra": ("Shinra", "Quantitative research director"),
}
SHINRA_STAFF = {
    "taka": ("Taka", "Geometric pattern scanner"),
    "ren": ("Ren", "FVG & imbalance profiler"),
    "kai": ("Kai", "Historical match engine"),
}


def _row(name, label, role):
    return dict(name=name, label=label, role=role, status="idle", reason=None, at=None)


def blank():
    state = {
        "kuro": _row("kuro", "Kuro", "Feed and orchestration"),
        "hayate": _row("hayate", "Hayate", "Parallel compute engine"),
        "ryu": _row("ryu", "Ryu", "Zero-latency dispatcher"),
        "shinra": _row("shinra", "Shinra", "Quantitative research director"),
        "division": {
            staff: _row(staff, *SHINRA_STAFF[staff]) for staff in SHINRA_STAFF
        },
        "lanes": {},
    }
    for lane, label in LANES:
        state["lanes"][lane] = dict(id=lane, label=label, stages={
            stage: _row(stage, *STAGE_ROLES[stage]) for stage in STAGES})
    return state


def mark(workers, status, reason=None, at=None, name="kuro"):
    row = workers.get(name)
    if row is not None:
        row.update(status=status, reason=reason, at=at)
    return workers


def mark_division(workers, staff, status, reason=None, at=None):
    row = workers.get("division", {}).get(staff)
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
    hayate = state.get("hayate", _row("hayate", "Hayate", "Parallel compute engine"))
    ryu = state.get("ryu", _row("ryu", "Ryu", "Zero-latency dispatcher"))
    shinra = state.get("shinra", _row("shinra", "Shinra", "Quantitative research director"))
    division_data = state.get("division", {})
    division = [_aged(division_data.get(staff, _row(staff, *SHINRA_STAFF[staff])), now) for staff in SHINRA_STAFF]
    lanes = []
    for lane, label in LANES:
        stages = state.get("lanes", {}).get(lane, {}).get("stages", {})
        lanes.append({"id": lane, "label": label,
                      "stages": [_aged(stages.get(stage, _row(stage, *STAGE_ROLES[stage])), now)
                                 for stage in STAGES]})
    return {
        "kuro": _aged(kuro, now),
        "hayate": _aged(hayate, now),
        "ryu": _aged(ryu, now),
        "shinra": _aged(shinra, now),
        "division": division,
        "lanes": lanes,
        "heartbeat_age": round(now - heartbeat, 1) if heartbeat else None,
        "error": error
    }
