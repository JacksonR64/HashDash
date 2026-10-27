#!/usr/bin/env python3
"""Minimal private Apple/rota display summaries; never changes source apps."""
import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from collect_host import write_module

LONDON = ZoneInfo("Europe/London")
APP = Path.home() / "Library/Application Support/ConsoleDashboard"
VAULT = Path(os.environ.get("HASHDASH_PROVIDER_DIR", str(Path.home() / ".local/share/hashdash/provider")))
ROTA = Path(os.environ.get("HASHDASH_ROTA_DIR", str(Path.home() / ".local/share/hashdash/rota")))
PERSON = os.environ.get("HASHDASH_PERSON", "Example Person")
VENUE = os.environ.get("HASHDASH_VENUE", "Example venue")
HA_HOST = os.environ.get("HASHDASH_HA_HOST", "home-assistant")
DISPLAY_HOST = os.environ.get("HASHDASH_DISPLAY_HOST", "clock-display")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rota_candidates(repo, now):
    rota = load_module("dashboard_rota", repo / "publish.py")
    weeks = {}
    for path in (repo / "weeks").glob("*.json"):
        if path.stem >= (now.date() - timedelta(days=8)).isoformat():
            week = json.loads(path.read_text())
            weeks[week["week_starting"]] = week
    today = now.date()
    candidates = []
    today_known = False
    for offset in range(-1, 15):
        day = today + timedelta(days=offset)
        monday = day - timedelta(days=day.weekday())
        week = weeks.get(monday.isoformat())
        if not week or PERSON not in week["staff"]:
            continue
        i = day.weekday()
        pieces = rota.shifts_on(week, PERSON, i)
        if day == today:
            today_known = not any(isinstance(p, str) and p == "unknown" for p in pieces)
        for piece in pieces:
            if isinstance(piece, str):
                continue
            (sh, sm), (eh, em, next_day) = piece
            start = datetime(day.year, day.month, day.day, sh, sm, tzinfo=LONDON)
            end = datetime(day.year, day.month, day.day, eh, em, tzinfo=LONDON) + timedelta(days=int(next_day))
            if end <= now:
                continue
            finish = "close" if getattr(piece, "close", False) else f"{eh:02d}:{em:02d}"
            label = "Today" if day == today else ("Tomorrow" if day == today + timedelta(days=1) else f"{day:%a %d %b}")
            on, _, _ = rota.crew_lists(week, PERSON, i)
            uncertain = week.get("date_uncertain") or any(u.get("person") == PERSON and u.get("day") == week["days"][i] for u in week.get("uncertain", []) if isinstance(u, dict))
            candidates.append((start, [f"{label} {sh:02d}:{sm:02d}-{finish} / {VENUE}" + (" / check rota" if uncertain else ""),
                                       "On that day: " + (" / ".join(f"{name} {cell}" for name, cell in on) or "crew not listed")]))
    return candidates, today_known


def rota_lines(repo, now, events=None):
    candidates, today_known = rota_candidates(repo, now)
    for event in events or []:
        if not is_work_event(event):
            continue
        start = event_time(event["start"])
        end = event_time(event["end"])
        if end <= now:
            continue
        label = "Today" if start.date() == now.date() else ("Tomorrow" if start.date() == now.date() + timedelta(days=1) else f"{start:%a %d %b}")
        end_label = f"{end:%H:%M}" + (" next day" if end.date() > start.date() else "")
        candidates.append((start, [f"{label} {start:%H:%M}-{end_label} / {event['title']}", "Crew details not supplied by this calendar"]))
    if candidates:
        start, lines = min(candidates, key=lambda pair: pair[0])
        if start.date() > now.date():
            lines[0] = "Next known: " + lines[0]
        monday = now.date() - timedelta(days=now.weekday())
        while monday <= start.date():
            if not (repo / "weeks" / (monday.isoformat() + ".json")).exists():
                lines.append(f"{VENUE} rota unavailable from {monday:%a %d %b}")
                break
            monday += timedelta(days=7)
        return lines
    return ["No shift today" if today_known else "Today's rota unavailable", "Next shift: not present in available rota"]


def collect_rota(directory, now, events):
    if events is None and (directory / "shift.json").exists():
        raise RuntimeError("calendar work coverage unavailable")
    write_module(directory, "shift", rota_lines(ROTA, now, events))


def event_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=LONDON) if result.tzinfo is None else result.astimezone(LONDON)


def is_work_event(event):
    calendar = event.get("calendar", "").lower()
    title = event.get("title", "")
    if event.get("allday") or re.search(r"leave|holiday|time off|absence|request", title, re.I):
        return False
    return (("workforce" in calendar or calendar == "work")
            and bool(re.match(r"(?:work\s*@|shift\b)", title, re.I)))


def calendar_events(brain):
    app = Path.home() / "Applications/ConsoleDashboard Calendar.app"
    if app.exists():
        subprocess.run(["open", "-g", "-W", "-a", str(app)], check=True, timeout=25, capture_output=True)
        feed = json.loads((APP / "calendar-feed.json").read_text())
        if (datetime.now(LONDON) - event_time(feed["updated_at"])).total_seconds() > 900:
            raise RuntimeError("Calendar helper feed is stale")
        return feed["events"]
    return brain.fetch_events()


def collect_calendar(directory, now, events):
    if events is None:
        raise RuntimeError("Calendar access unavailable")
    upcoming = []
    for event in events:
        start = event_time(event["start"])
        end = event_time(event["end"])
        calendar = event.get("calendar", "").lower()
        if is_work_event(event) or any(word in calendar for word in ("full staff", "bh shifts", "work shifts", "holiday", "birthday")):
            continue
        if event.get("allday"):
            if start.date() <= now.date() <= end.date():
                upcoming.append((start, "Today: " + event["title"]))
        elif end > now and start.date() == now.date():
            label = "Now" if start <= now else f"{start:%H:%M}"
            upcoming.append((start, label + ": " + event["title"]))
    lines = list(dict.fromkeys(text for _, text in sorted(upcoming)))[:3]
    write_module(directory, "agenda", lines or ["No more events in today's calendar snapshot"])


def collect_reminders(directory, now, brain):
    reminders = [r for r in brain.fetch_reminders() if not r["done"]]
    def rank(reminder):
        due = reminder.get("due") or "9999"
        return (due, reminder.get("priority") or 99)
    reminders.sort(key=rank)
    lines = []
    for reminder in reminders[:2]:
        due = reminder.get("due", "")
        prefix = ""
        if due:
            day = datetime.fromisoformat(due.replace("Z", "+00:00")).astimezone(LONDON).date()
            prefix = "Overdue: " if day < now.date() else ("Today: " if day == now.date() else f"{day:%d %b}: ")
        lines.append(prefix + reminder["title"] + " [" + reminder["list"] + "]")
    if len(reminders) > 2:
        lines.append(f"+{len(reminders) - 2} other incomplete reminders")
    write_module(directory, "reminders", lines or ["No incomplete reminders returned"])


MAIL = r'''
const mail=Application('Mail');
if(!mail.running()) JSON.stringify({available:false});
else {
 const count=mail.inbox.messages.whose({flaggedStatus:true}).length;
 JSON.stringify({available:true,count:count});
}
'''


def collect_mail(directory):
    result = subprocess.run(["osascript", "-l", "JavaScript", "-e", MAIL], capture_output=True, text=True, timeout=25, check=True)
    data = json.loads(result.stdout)
    line = f"{data['count']} flagged inbox emails" if data["available"] else "Flagged mail: Mail app is not running on the M5"
    write_module(directory, "mail", [line])


def collect_alarm(directory, now):
    command = "sudo -n /config/patches/ha_api.sh GET states/input_datetime.wake_alarm_next"
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", HA_HOST, command], capture_output=True, text=True, timeout=10, check=True)
    state = json.loads(result.stdout)["state"]
    alarm = datetime.fromisoformat(state).replace(tzinfo=LONDON)
    lines = [f"HA next alarm: {alarm:%a %H:%M}" if alarm > now else "Next alarm: not confirmed by Home Assistant"]
    try:
        shift = json.loads((directory / "shift.json").read_text())["lines"]
        lines.append(shift[0])
    except (OSError, ValueError, KeyError):
        pass
    write_module(directory, "alarm", lines)


PUSH = r'''
import sys,json,pathlib,tempfile,os
root=pathlib.Path('/var/lib/console-clock/dashboard')
allowed={'shift','agenda','reminders','mail','alarm'}
for name,data in json.load(sys.stdin).items():
 if name not in allowed:raise ValueError('unknown module')
 fd,p=tempfile.mkstemp(prefix='.'+name,dir=root)
 with os.fdopen(fd,'w') as handle:json.dump(data,handle)
 os.replace(p,root/(name+'.json'))
print('Private display summaries delivered')
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=APP / "data")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    args.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    now = datetime.now(LONDON)
    brain = load_module("dashboard_brain_calendar", VAULT / "tools/brain_calendar.py")
    try:
        events = calendar_events(brain)
    except Exception as error:
        events = None
        print("calendar access: unavailable (" + type(error).__name__ + ")", flush=True)
    jobs = {"shift": lambda: collect_rota(args.data_dir, now, events),
            "agenda": lambda: collect_calendar(args.data_dir, now, events),
            "reminders": lambda: collect_reminders(args.data_dir, now, brain),
            "mail": lambda: collect_mail(args.data_dir)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        pending = {name: pool.submit(function) for name, function in jobs.items()}
        for name, result in pending.items():
            try:
                result.result()
                print(name + ": refreshed", flush=True)
            except Exception as error:
                print(name + ": unavailable (" + type(error).__name__ + ")", flush=True)
                if not (args.data_dir / (name + ".json")).exists():
                    write_module(args.data_dir, name, [name.capitalize() + ": source access unavailable"])
    try:
        collect_alarm(args.data_dir, now)
        print("alarm: refreshed", flush=True)
    except Exception as error:
        print("alarm: unavailable (" + type(error).__name__ + ")", flush=True)
    if not args.no_push:
        import shlex
        data = {p.stem: json.loads(p.read_text()) for p in args.data_dir.glob("*.json") if p.stem in {"shift", "agenda", "reminders", "mail", "alarm"}}
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", DISPLAY_HOST, "python3 -c " + shlex.quote(PUSH)], input=json.dumps(data), capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise SystemExit("Display delivery unavailable; cached summaries retained on M5")
        print(result.stdout.strip(), flush=True)


if __name__ == "__main__":
    main()
