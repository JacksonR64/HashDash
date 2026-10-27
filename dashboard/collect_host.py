#!/usr/bin/env python3
"""Read cached BamBuddy status and existing Claude session metadata. GET only."""
import argparse
import concurrent.futures
import json
import os
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def write_module(directory, name, lines, items=None):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {"updated_at": datetime.now(timezone.utc).isoformat(), "lines": lines}
    if items is not None:
        data["items"] = items
    fd, temporary = tempfile.mkstemp(prefix="." + name, dir=directory)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(temporary, directory / (name + ".json"))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def request_json(config, path):
    request = urllib.request.Request(config["bambuddy_url"].rstrip("/") + path,
                                     headers={"X-API-Key": config["bambuddy_key"]})
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def printer_lines(name, status, now):
    if not status.get("connected"):
        return [f"{name}: OFFLINE"]
    state = str(status.get("state", "unknown")).upper()
    if state in ("RUNNING", "PRINTING", "PAUSE", "PAUSED", "PREPARE"):
        progress = float(status.get("progress") or 0)
        line = f"{name}: {state.lower()} / {progress:.0f}%"
        remaining = status.get("remaining_time")
        if state in ("RUNNING", "PRINTING") and remaining is not None and float(remaining) > 0:
            minutes = float(remaining)
            finish = (now + timedelta(minutes=minutes)).astimezone(ZoneInfo("Europe/London"))
            line += f" / ~{minutes:.0f} min left / ~{finish:%H:%M}"
        return [line]
    label = {"FINISH": "last print completed", "FAILED": "last print failed", "IDLE": "idle"}.get(state, state.lower())
    return [f"{name}: connected / {label}"]


def collect_printers(config, directory):
    # Host-only dependency: the Mac helper also imports write_module from this file.
    from printguard_display import read_guard, guard_lines
    printers = request_json(config, "/api/v1/printers/")
    if not isinstance(printers, list):
        raise ValueError("unexpected printer list")
    lines, items = [], []
    now = datetime.now(timezone.utc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        guard_result = pool.submit(read_guard)
        obico_result = pool.submit(request_json, config, "/api/v1/obico/status")
        pending = [(p, pool.submit(request_json, config, f"/api/v1/printers/{int(p['id'])}/status")) for p in printers]
        try:
            guard = guard_result.result()
        except Exception:
            guard = {"unavailable": True}
        try:
            obico = obico_result.result()
        except Exception:
            obico = None
        for printer, result in pending:
            name = str(printer.get("name") or printer["id"])
            try:
                status = result.result()
                summary = printer_lines(name, status, now)
                checks = guard_lines(int(printer["id"]), status, guard, obico, now)
                lines.extend(summary)
                lines.extend(checks)
                lines.append("")
                items.append({"name": name, "connected": bool(status.get("connected")),
                              "state": str(status.get("state", "unknown")).upper(),
                              "progress": status.get("progress"), "summary": summary[0][len(name) + 2:],
                              "checks": checks})
            except Exception:
                lines.append(f"{name}: status unavailable")
                items.append({"name": name, "connected": False, "state": "unavailable",
                              "summary": "status unavailable", "checks": []})
    write_module(directory, "printers", lines or ["No printers returned by BamBuddy"], items=items)


def collect_claude(directory):
    # lxc-info avoids loading Proxmox's much larger Perl stack every refresh.
    result = subprocess.run(["lxc-info", "-n", os.environ.get("HASHDASH_CLAUDE_CT", "240"), "-pH"],
                            capture_output=True, text=True, timeout=6, check=True)
    guest = Path(f"/proc/{int(result.stdout.strip())}/root")
    sessions = []
    for path in (guest / os.environ.get("HASHDASH_CLAUDE_SESSIONS", "home/operator/.claude/sessions")).glob("*.json"):
        try:
            data = json.loads(path.read_text())
            process = guest / f"proc/{int(data['pid'])}/comm"
            if process.read_text().strip() != "claude":
                continue
            sessions.append({"name": data.get("name", "CLI"), "status": data.get("status", "unknown"),
                             "statusUpdatedAt": data.get("statusUpdatedAt")})
        except (OSError, ValueError, KeyError):
            continue
    lines = [f"i7 / CT240: {len(sessions)} live CLI session(s)"]
    for session in sessions[:2]:
        stamp = session.get("statusUpdatedAt")
        age = (datetime.now(timezone.utc).timestamp() - float(stamp) / 1000) if stamp else None
        age_text = f" / reported {max(0, int(age // 60))}m ago" if age is not None else " / age unknown"
        lines.append(f"{session['name']}: {session['status']}{age_text}")
    write_module(directory, "claude", lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("/etc/console-dashboard/sources.json"))
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/console-clock/dashboard"))
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {"printers": pool.submit(collect_printers, config, args.data_dir),
                "claude": pool.submit(collect_claude, args.data_dir)}
        for name, result in jobs.items():
            try:
                result.result()
                print(name + ": refreshed")
            except Exception as error:
                # Keep the previous timestamp/value; the renderer will mark it stale.
                print(name + ": unavailable (" + type(error).__name__ + ")")


if __name__ == "__main__":
    main()
