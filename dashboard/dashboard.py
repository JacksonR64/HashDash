#!/usr/bin/env python3
"""Small cached-data terminal dashboard. No network requests or service control."""
import argparse
import curses
import json
import re
import runpy
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from terminal_layout import compose
from around_layout import compose as compose_around, clock_style_spans

HERE = Path(__file__).resolve().parent
CLOCK = runpy.run_path(str(HERE.parent / "console-clock.py"))
LONDON = ZoneInfo("Europe/London")
MAX_BYTES = 65536


def clean(value):
    # Feed text must not inject terminal controls, tabs or additional rows.
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())


def read_json(path):
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("file exceeds 64 KiB")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def load_config(path):
    config = read_json(path)
    modules = config["modules"]
    views = config["views"]
    if not isinstance(modules, dict) or not isinstance(views, dict) or not views:
        raise ValueError("modules and views must be objects; at least one view is required")
    for spec in modules.values():
        filename = spec["file"]
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ValueError("module file must be a filename inside the data directory")
        if not 1 <= spec["max_lines"] <= 30 or spec["max_age_seconds"] <= 0:
            raise ValueError("invalid module limits")
    for view in views.values():
        if any(name not in modules for name in view.get("slots", {}).values()):
            raise ValueError("each slot must name a configured module")
        if view.get("hero") and view["hero"] not in modules:
            raise ValueError("hero must name a configured module")
        stacks = view.get("columns")
        if stacks is not None and (not isinstance(stacks, list) or not 1 <= len(stacks) <= 2
                                  or any(not isinstance(stack, list) or not stack or any(name not in modules for name in stack) for stack in stacks)):
            raise ValueError("columns must contain one or two nonempty module lists")
        if not 1 <= view.get("printer_columns", 1) <= 3 or not 1 <= view.get("printer_limit", 2) <= 12:
            raise ValueError("invalid printer layout limits")
        if not isinstance(view["rows"], list):
            raise ValueError("view rows must be a list")
        for row in view["rows"]:
            if not isinstance(row, list) or not 1 <= len(row) <= 2 or any(x not in modules for x in row):
                raise ValueError("each row must name one or two configured modules")
    if config["initial_view"] not in views:
        raise ValueError("initial_view is not configured")
    return config


def read_modules(config, directory):
    records = {}
    for name, spec in config["modules"].items():
        try:
            records[name] = read_json(directory / spec["file"])
        except (OSError, ValueError, UnicodeError):
            records[name] = None
    return records


def module_lines(name, spec, record, now):
    title = clean(spec.get("title", name)).upper()
    if record is None:
        return [title, "Unavailable - waiting for data"]
    try:
        stamp = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("timestamp needs timezone")
        age = (now - stamp).total_seconds()
        if age < -300:
            raise ValueError("timestamp is in the future")
        lines = record["lines"]
        if not isinstance(lines, list) or any(not isinstance(x, str) for x in lines):
            raise ValueError("lines must be text")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return [title, "Unavailable - invalid data"]
    age = max(0, int(age))
    if age > spec["max_age_seconds"]:
        status = f"STALE - {age // 60}m old" if age >= 60 else f"STALE - {age}s old"
    else:
        status = f"updated {age}s ago" if age < 60 else f"updated {age // 60}m ago"
    limit = spec["max_lines"]
    body = [clean(x) for x in lines] or ["No items in this feed"]
    if len(body) > limit:
        body = body[:limit - 1] + [f"+{len(body) - limit + 1} more lines - open full source"]
    return [f"{title} / {status}", *body]


def render(config, records, view_name, now, columns, rows, demo=False):
    if config["views"][view_name].get("style") == "around" and columns >= 90 and rows >= 35:
        return compose_around(config, records, view_name, now.astimezone(LONDON), columns, rows, module_lines, CLOCK["FONT"], demo)
    if columns >= 100 and rows >= 40:
        return compose(config, records, view_name, now.astimezone(LONDON), columns, rows, module_lines, demo)
    return render_compact(config, records, view_name, now, columns, rows, demo)


def render_compact(config, records, view_name, now, columns, rows, demo=False):
    columns, rows = max(1, columns), max(1, rows)
    view = config["views"][view_name]
    frame = [clean(view.get("title", view_name)).upper().center(columns), ""]
    text = now.astimezone(LONDON).strftime("%H:%M:%S" if config.get("show_seconds") and columns >= 43 else "%H:%M")
    width = sum(len(CLOCK["FONT"][c][0]) for c in text) + len(text) - 1
    horizontal = max(1, min(4, (columns - 4) // width))
    vertical = 3 if view_name == "night" and rows >= 45 else (2 if rows >= 44 else 1)
    if columns >= 29 and rows >= 20:
        frame += [line.center(columns) for line in CLOCK["big_time"](text, horizontal, vertical)]
    else:
        frame.append(text.center(columns))
    frame += ["", now.astimezone(LONDON).strftime("%A %d %B %Y / %Z").center(columns), ""]
    if demo:
        frame += ["DEMO - FICTIONAL DATA".center(columns), ""]
    layout_rows = ([[view["hero"]]] if view.get("hero") else [])
    layout_rows += [[name] for stack in view.get("columns", []) for name in stack] + view["rows"]
    for layout_row in layout_rows:
        # Narrow terminals stack modules; the real i7 console is 180 x 56.
        groups = [layout_row] if columns >= 80 else [[name] for name in layout_row]
        for names in groups:
            panes = [module_lines(name, config["modules"][name], records.get(name), now) for name in names]
            pane_width = (columns - 4 * (len(names) - 1)) // len(names)
            for i in range(max(map(len, panes))):
                cells = [(pane[i] if i < len(pane) else "")[:pane_width].ljust(pane_width) for pane in panes]
                frame.append("    ".join(cells).rstrip())
            frame.append("")
    view_keys = " / ".join(f"{i + 1}:{clean(key)}" for i, key in enumerate(config["views"]))
    footer = f"{view_keys}  Tab:next  +/-:brightness  Q:console"
    if len(frame) > rows - 2:
        frame = frame[:max(0, rows - 3)] + ["[More content - use another view or a larger terminal]"]
    frame += [""] * max(0, rows - 1 - len(frame))
    frame.append(footer)
    return [line[:columns] for line in frame[:rows]]


def demo_records(now):
    stamp = now.isoformat()
    records = {name: {"updated_at": stamp, "lines": lines} for name, lines in {
        "shift": ["EXAMPLE: Today 16:00-close / Example venue", "On today: Alex 12-6 / Jamie 4-close / Morgan 6-close"],
        "printers": ["EXAMPLE: A1 mini / printing 72% / about 38 min left", "EXAMPLE: A1 / idle"],
        "agenda": ["EXAMPLE: 12:00 Appointment"],
        "claude": ["EXAMPLE: 1 running / 1 waiting for input"],
        "alarm": ["EXAMPLE: Next alarm 08:30 / Work today 16:00-close"],
        "reminders": ["EXAMPLE: Collect parcel", "EXAMPLE: Order packing supplies"],
        "mail": ["EXAMPLE: 3 flagged inbox emails"],
    }.items()}
    records["printers"]["items"] = [
        {"name": "A1 mini", "connected": True, "state": "RUNNING", "progress": 72,
         "summary": "printing / 72% / ~38 min left / ~08:20",
         "checks": ["PG armed / last AI: looks OK", "AI confidence 80% / checked 2m ago", "EXAMPLE: layers look consistent", "Obico: safe / suspicion score 0.020"]},
        {"name": "A1", "connected": True, "state": "IDLE", "summary": "connected / idle",
         "checks": ["PG armed / no AI verdict recorded for this printer"]}]
    return records


def display(screen, config, directory, demo):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    screen.timeout(1000)
    ink, rule, bright = 0, curses.A_DIM, curses.A_BOLD
    palette = {"ok": bright, "warning": bright, "fault": bright, "unknown": rule}
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_BLACK)
        ink = curses.color_pair(1)
        rule = curses.color_pair(2) | curses.A_BOLD
        bright = ink | curses.A_BOLD
        curses.init_pair(3, curses.COLOR_YELLOW, curses.COLOR_BLACK)
        curses.init_pair(4, curses.COLOR_RED, curses.COLOR_BLACK)
        palette = {"ok": bright, "warning": curses.color_pair(3) | curses.A_BOLD,
                   "fault": curses.color_pair(4) | curses.A_BOLD, "unknown": rule}
        screen.bkgd(" ", ink)
    names = list(config["views"])
    selected = names.index(config["initial_view"])
    next_read = 0
    records = {}
    previous = None
    level = 30
    try:
        level = int(CLOCK["BRIGHTNESS"].read_text())
    except (OSError, ValueError):
        pass
    if Path("/sys/class/backlight/acpi_video0/brightness").exists():
        level = CLOCK["set_brightness"](level) or level
    while True:
        now = datetime.now(timezone.utc)
        if time.monotonic() >= next_read:
            records = demo_records(now) if demo else read_modules(config, directory)
            next_read = time.monotonic() + 5
        rows, columns = screen.getmaxyx()
        frame = render(config, records, names[selected], now, columns, rows, demo)
        spans = clock_style_spans(config, records, names[selected], now.astimezone(LONDON), columns, rows, CLOCK["FONT"])
        render_state = (frame, spans)
        if render_state != previous:
            if previous is None:
                screen.clear()
            else:
                screen.erase()
            for row, line in enumerate(frame):
                try:
                    screen.addnstr(row, 0, line, max(0, columns - 1), ink)
                    for match in re.finditer(r"[┌┐└┘│─░]+|[█▓#]+|\[[1-9] [^]]+\]", line):
                        style = bright if match[0][0] in "█▓#[" else rule
                        screen.addnstr(row, match.start(), match[0], max(0, columns - 1 - match.start()), style)
                except curses.error:
                    pass
            for row, column, length, status in spans:
                try:
                    screen.addnstr(row, column, frame[row][column:column + length], length, palette[status])
                except curses.error:
                    pass
            screen.refresh()
            previous = render_state
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return
        if key in (9, curses.KEY_RIGHT, ord("n")):
            selected = (selected + 1) % len(names)
        elif key == curses.KEY_LEFT:
            selected = (selected - 1) % len(names)
        elif ord("1") <= key <= ord("9") and key - ord("1") < len(names):
            selected = key - ord("1")
        elif key in (ord("+"), ord("="), ord("-"), ord("_")):
            changed = CLOCK["set_brightness"](level + (5 if key in (ord("+"), ord("=")) else -5))
            if changed is not None:
                level = changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "layout.json")
    parser.add_argument("--data-dir", type=Path, default=HERE / "data")
    parser.add_argument("--demo", action="store_true", help="clearly labelled fictional example data")
    parser.add_argument("--preview", action="store_true", help="print one frame without changing the display")
    parser.add_argument("--view", help="initial view name")
    parser.add_argument("--columns", type=int, default=180)
    parser.add_argument("--rows", type=int, default=56)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if args.view:
            if args.view not in config["views"]:
                raise ValueError("unknown view")
            config["initial_view"] = args.view
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))
    if args.preview:
        now = datetime.now(timezone.utc)
        records = demo_records(now) if args.demo else read_modules(config, args.data_dir)
        print("\n".join(render(config, records, config["initial_view"], now, args.columns, args.rows, args.demo)))
    else:
        curses.wrapper(display, config, args.data_dir, args.demo)


if __name__ == "__main__":
    main()
