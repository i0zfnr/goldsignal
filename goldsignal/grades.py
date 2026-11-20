PUBLISHABLE_GRADES = ("A", "A+")
LOW_GRADES = ("B", "B+")


def signal_grade(item):
    evidence = item.get("evidence") or {}
    raw = str(item.get("grade") or evidence.get("grade") or evidence.get("entry_grade") or "").upper()
    if raw == "ALIGNED" or "A+" in raw:
        return "A+"
    if raw == "M5/M1 SCALP":
        return "A"
    if raw.startswith("A"):
        return "A"
    if "B+" in raw:
        return "B+"
    if raw.startswith("B"):
        return "B"
    if raw.startswith("C"):
        return "C"
    return ""


def is_low_grade(item):
    return signal_grade(item) in LOW_GRADES


def publishable_grade(item):
    return signal_grade(item) in PUBLISHABLE_GRADES
