"""Conservative display states, using existing read-only summaries only."""
from datetime import datetime
import math

from terminal_layout import text, valid_items


def fresh(record, now, max_age):
    try:
        stamp = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
        return -5 <= (now - stamp).total_seconds() <= max_age
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def worst(states):
    values = list(states)
    return next((state for state in ("fault", "warning", "unknown", "ok") if state in values), "unknown")


def printer_condition(item):
    if item.get("connected") is not True:
        return "unknown", "Printer: offline / unavailable"
    state = str(item.get("state", "")).upper()
    if state == "FAILED":
        return "fault", "Last print failed"
    if state in ("PAUSE", "PAUSED"):
        return "warning", "Paused / inspect in Fleet"
    if state in ("IDLE", "FINISH", "COMPLETED"):
        return "ok", "No active print"
    if state not in ("RUNNING", "PRINTING", "PREPARE", "PREPARING"):
        return "unknown", "Printer: state unavailable"
    checks = [text(line) for line in item.get("checks", [])]
    guard = next((line for line in checks if line.startswith(("PG ", "PrintGuard"))), "")
    detector = next((line for line in checks if line.startswith("Obico: ")), "")
    if "STOPPED" in guard:
        ai = ("warning", "Guard: stopped")
    elif "earlier-job AI" in guard:
        ai = ("unknown", "Guard: earlier-job result")
    elif "AI STALE" in guard:
        ai = ("unknown", "Guard: stale AI result")
    elif "last AI: suspected failure" in guard:
        ai = ("warning", "Guard: suspected failure")
    elif "last AI: uncertain" in guard:
        ai = ("warning", "Guard: unsure")
    elif "last AI: looks OK" in guard:
        ai = ("ok", "Guard: looks OK")
    else:
        ai = ("unknown", "Guard: AI unavailable")
    try:
        score = float(detector.rsplit(" / suspicion score ", 1)[1])
        valid_detector = math.isfinite(score) and not detector.startswith("Obico: unclassified ")
    except (ValueError, IndexError):
        valid_detector = False
    if valid_detector:
        obico = ("ok", "") if detector.startswith("Obico: safe / ") else ("warning", "Obico: detector alert")
    else:
        obico = ("unknown", "Obico: unavailable")
    level = worst((ai[0], obico[0]))
    return next(value for value in (ai, obico) if value[0] == level)


def printer_status(record, now, max_age):
    items = valid_items(record)
    if not fresh(record, now, max_age) or not items:
        return "unknown"
    return worst(printer_condition(item)[0] for item in items)
