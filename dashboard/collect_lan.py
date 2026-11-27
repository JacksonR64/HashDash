#!/usr/bin/env python3
"""Record whether this host can reach its own LAN gateway. One ping, one small feed; no control.

Settings come from the environment (a private EnvironmentFile on a real install):
LAN_GATEWAY (required), LAN_INTERFACE (optional, e.g. a bridge), LAN_LABEL (clock text).
"""
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FEED = Path(os.environ.get("LAN_FEED", "/var/lib/console-clock/dashboard/lan.json"))
CARRY_SECONDS = 120  # keep an outage start only if the previous run was this recent


def reachable(gateway, interface=""):
    command = ["ping", "-q", "-c", "2", "-W", "1"] + (["-I", interface] if interface else []) + [gateway]
    try:
        return subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=8).returncode == 0
    except subprocess.TimeoutExpired:
        return False
    # OSError (no ping binary) propagates: unknown must not become "offline".


def next_record(previous, ok, now, label):
    since = None
    if not ok:
        since = now.isoformat()
        try:
            age = (now - datetime.fromisoformat(previous["updated_at"])).total_seconds()
            if previous.get("reachable") is False and 0 <= age <= CARRY_SECONDS:
                since = previous["down_since"]
        except (KeyError, TypeError, ValueError, AttributeError):
            pass
    line = "Gateway reachable" if ok else "Gateway unreachable since " + since[11:16] + " UTC"
    return {"updated_at": now.isoformat(), "lines": [line], "reachable": ok, "down_since": since, "label": label}


def main():
    gateway = os.environ.get("LAN_GATEWAY", "").strip()
    if not gateway:
        raise SystemExit("LAN_GATEWAY is not set; nothing written")
    try:
        previous = json.loads(FEED.read_text())
    except (OSError, ValueError):
        previous = {}
    ok = reachable(gateway, os.environ.get("LAN_INTERFACE", "").strip())
    record = next_record(previous, ok, datetime.now(timezone.utc), os.environ.get("LAN_LABEL", "Network offline").strip())
    FEED.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".lan", dir=FEED.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(record, handle)
        os.chmod(temporary, 0o644)
        os.replace(temporary, FEED)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    main()
