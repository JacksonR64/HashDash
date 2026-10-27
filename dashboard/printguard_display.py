"""Read PrintGuard's existing status/logs. Never runs a check or printer action."""
import ast
import json
import math
import os
import re
import subprocess
import textwrap
from pathlib import Path


def parse_records(records):
    verdicts, errors = {}, {}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("MESSAGE"), str):
            continue
        message = row.get("MESSAGE", "")
        try:
            timestamp = float(row["__REALTIME_TIMESTAMP"]) / 1_000_000
        except (KeyError, TypeError, ValueError):
            continue
        error = re.search(r"watch thread printer (\d+): (.+)", message)
        if error:
            pid = int(error[1])
            if timestamp >= errors.get(pid, {}).get("timestamp", 0):
                errors[pid] = {"timestamp": timestamp, "reason": error[2]}
        check = re.search(r"(?:watch|obico pause) printer (\d+) \((.*?)\):\s*(\{.*)", message)
        if not check:
            continue
        pid = int(check[1])
        raw = check[3]
        try:
            result = json.loads(raw)
        except ValueError:
            # Guard logs truncate long JSON. Recover only intact verdict/confidence fields.
            verdict = re.search(r'"verdict"\s*:\s*"(ok|failure|unsure)"', raw)
            confidence = re.search(r'"confidence"\s*:\s*(0(?:\.\d+)?|1(?:\.0+)?)(?=\s*[,}])', raw)
            if not verdict or not confidence:
                continue
            result = {"verdict": verdict[1], "confidence": float(confidence[1]), "reason": "Reason truncated in source log"}
        if not isinstance(result, dict) or result.get("verdict") not in ("ok", "failure", "unsure"):
            continue
        try:
            confidence = float(result["confidence"])
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        job = re.split(r" [\d.]+% layer ", check[2])[0]
        if timestamp >= verdicts.get(pid, {}).get("timestamp", 0):
            verdicts[pid] = {"timestamp": timestamp, "job": job, "verdict": result["verdict"],
                             "confidence": confidence, "reason": str(result.get("reason", "No reason recorded"))}
    return verdicts, errors


def read_guard():
    process = subprocess.run(["lxc-info", "-n", os.environ.get("HASHDASH_PRINTGUARD_CT", "222"), "-pH"], capture_output=True, text=True, timeout=3, check=True)
    root = Path(f"/proc/{int(process.stdout.strip())}/root")
    directory = root / "etc/printguard"
    watched, swap = [], []
    with (root / "opt/printguard/printguard.py").open() as handle:
        for _, line in zip(range(100), handle):
            match = re.match(r"(WATCH_PRINTERS|SWAP_PRINTERS)\s*=\s*(\[[^]]*\])", line)
            if match:
                value = ast.literal_eval(match[2])
                if match[1] == "WATCH_PRINTERS":
                    watched = value
                else:
                    swap = value
    active = subprocess.run(["lxc-attach", "-n", os.environ.get("HASHDASH_PRINTGUARD_CT", "222"), "--", "systemctl", "is-active", "printguard"],
                            capture_output=True, text=True, timeout=3)
    journal = subprocess.run(["lxc-attach", "-n", os.environ.get("HASHDASH_PRINTGUARD_CT", "222"), "--", "journalctl", "-u", "printguard",
                              "-n", "250", "--no-pager", "-o", "json"], capture_output=True, text=True, timeout=5, check=True)
    rows = []
    for line in journal.stdout.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    verdicts, errors = parse_records(rows)
    try:
        state = json.loads((root / "var/lib/printguard/state.json").read_text())
    except (OSError, ValueError):
        state = {}
    try:
        interval = int((directory / "watch_every").read_text().strip())
    except (OSError, ValueError):
        interval = 300
    return {"active": active.stdout.strip() == "active", "armed": (directory / "armed").exists(),
            "watched": watched, "swap": swap, "interval": interval, "verdicts": verdicts,
            "errors": errors, "first": state.get("first", {}), "our_pause": state.get("our_pause", {})}


def age_text(timestamp, now):
    age = max(0, int(now.timestamp() - timestamp))
    return f"{age}s ago" if age < 60 else (f"{age // 60}m ago" if age < 3600 else f"{age // 3600}h ago")


def guard_lines(pid, status, guard, obico, now):
    lines = []
    if not status.get("connected"):
        return ["  PrintGuard: current view unavailable / printer offline"]
    if not guard or guard.get("unavailable"):
        lines.append("  PrintGuard: status unavailable")
    elif pid not in guard["watched"]:
        lines.append("  PrintGuard: queue only" if pid in guard["swap"] else "  PrintGuard: not configured for this printer")
    elif not guard["active"]:
        lines.append("  PrintGuard: STOPPED")
    else:
        armed = "armed" if guard["armed"] else "watch-only"
        record = guard["verdicts"].get(pid)
        error = guard["errors"].get(pid)
        printing = str(status.get("state", "")).upper() in ("RUNNING", "PRINTING", "PAUSE", "PAUSED")
        job = status.get("subtask_name") or status.get("gcode_file") or ""
        start = guard.get("first", {}).get(str(pid), {})
        start_time = start.get("t0", 0) if start.get("job") == job else 0
        if error and error["timestamp"] > (record or {}).get("timestamp", 0) and error["timestamp"] >= start_time:
            reason = error["reason"]
            if "No route to host" in reason:
                reason = "camera network unreachable"
            elif "timed out" in reason:
                reason = "check timed out"
            elif "Connection refused" in reason:
                reason = "camera/service connection refused"
            lines += [f"  PG {armed} / AI unavailable / {age_text(error['timestamp'], now)}", "  " + textwrap.shorten(reason, width=80, placeholder="...")]
        elif record:
            same_job = bool(job) and job.startswith(record["job"]) and record["timestamp"] >= start_time
            stale = now.timestamp() - record["timestamp"] > max(120, guard["interval"] * 2 + 120)
            prefix = "last AI" if not printing else ("AI STALE" if stale or not same_job else "last AI")
            if printing and not same_job:
                prefix = "earlier-job AI"
            verdict = {"ok": "looks OK", "failure": "suspected failure", "unsure": "uncertain"}[record["verdict"]]
            lines += [f"  PG {armed} / {prefix}: {verdict}",
                      f"  AI confidence {record['confidence']:.0%} / checked {age_text(record['timestamp'], now)}",
                      "  " + textwrap.shorten(record["reason"], width=80, placeholder="...")]
        else:
            lines.append(f"  PG {armed} / no AI verdict recorded for this printer")
    if str(status.get("state", "")).upper() in ("RUNNING", "PRINTING", "PAUSE", "PAUSED"):
        entry = (obico or {}).get("per_printer", {}).get(str(pid))
        if not obico or not obico.get("is_running") or not entry or entry.get("error"):
            lines.append("  Obico: detector unavailable / no current result")
        else:
            try:
                score = float(entry["score"])
                if not math.isfinite(score):
                    raise ValueError("invalid score")
                lines.append(f"  Obico: {entry.get('class', 'unclassified')} / suspicion score {score:.3f}")
            except (KeyError, TypeError, ValueError):
                lines.append("  Obico: score unavailable")
    return lines
