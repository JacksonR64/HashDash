"""Clock-centered text layout. Positions use fractions so modules remain movable."""
import math
import re
import textwrap
from datetime import datetime

from terminal_layout import fit, pair, text, valid_items, printer_card
from status_indicators import fresh, printer_condition, printer_status, worst


def clock_art(now, font, width):
    value = now.strftime("%H:%M")
    size = sum(len(font[c][0]) for c in value) + len(value) - 1
    stretch = max(1, min(4, (width - 10) // size))
    return ["".join(("#" if bit == "1" else " ") * stretch for bit in "0".join(font[c][r] for c in value))
            for r in range(7) for _ in range(2)]


def seconds_art(now):
    digits = (
        ("111", "101", "101", "101", "111"), ("010", "110", "010", "010", "111"),
        ("111", "001", "111", "100", "111"), ("111", "001", "111", "001", "111"),
        ("101", "101", "111", "001", "001"), ("111", "100", "111", "001", "111"),
        ("111", "100", "111", "101", "111"), ("111", "001", "010", "010", "010"),
        ("111", "101", "111", "101", "111"), ("111", "101", "111", "001", "111"))
    return ["0".join(digits[int(c)][row] for c in now.strftime("%S")).replace("1", "#").replace("0", " ")
            for row in range(5)]


def clock_geometry(now, font, columns, rows, show_seconds=True):
    art = clock_art(now, font, columns - 4)
    x = max(2, (columns - len(art[0]) - (9 if show_seconds else 0)) // 2)
    y = max(9, round(rows * .27))
    return art, x, y


def progress(item, width, compact=False):
    state = str(item.get("state", "")).upper()
    if not item.get("connected") or state not in ("RUNNING", "PRINTING", "PAUSED", "PAUSE", "PREPARE"):
        return "" if compact else fit(item["summary"], width)
    try:
        value = float(item["progress"])
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise ValueError("invalid progress")
    except (KeyError, ValueError, TypeError):
        return "Progress unavailable"
    detail = " / ".join(item["summary"].split(" / ")[2:]).replace(" min left", "m").replace(" / ", " ")
    label = f"{value:.0f}%" + (" / " + detail if detail and not compact else "")
    bar_width = max(2, width - len(label) - 2)
    filled = round(value / 100 * bar_width)
    return "▓" * filled + "░" * (bar_width - filled) + "  " + label


def short_printer(item, width, quiet=False):
    state = str(item.get("state", "")).upper()
    connected = item.get("connected") is True
    symbol = "[>]" if state in ("RUNNING", "PRINTING", "PREPARE") else ("[||]" if state in ("PAUSE", "PAUSED") else ("[x]" if state == "FAILED" else "[ ]"))
    label = {"RUNNING": "Printing", "PRINTING": "Printing", "PREPARE": "Preparing", "PAUSE": "Paused", "PAUSED": "Paused", "FAILED": "Last failed", "FINISH": "Completed", "IDLE": "Idle"}.get(state, state.title())
    if not connected:
        symbol, label = "[?]", "Offline / unavailable"
    checks = [text(line) for line in item["checks"]]
    guard = next((line for line in checks if line.startswith(("PG ", "PrintGuard"))), "Guard: no current check")
    guard = guard.replace("PG armed / ", "Guard: ").replace("PG watch-only / ", "Guard watch-only: ")
    guard = guard.replace("PrintGuard: ", "Guard: ")
    confidence = next((re.search(r"AI confidence (\d+%) / checked (.+)", line) for line in checks if line.startswith("AI confidence ")), None)
    if confidence:
        guard += " / conf " + confidence[1] + " / " + confidence[2]
    if not connected:
        guard = "Guard: current printer view unavailable"
    if quiet:
        _, guard = printer_condition(item)
        if connected and state in ("RUNNING", "PRINTING", "PREPARE"):
            eta = next((part.strip() for part in item["summary"].split("/") if "min left" in part), "")
            label = eta.replace(" min left", "m") or label
        if not connected or state in ("IDLE", "FINISH", "COMPLETED", "FAILED"):
            guard = ""
    return [pair(symbol + " " + item["name"], label, width), progress(item, width, compact=quiet), fit(guard, width)]


def health_items(record, now, max_age):
    try:
        stamp = datetime.fromisoformat(record["updated_at"].replace("Z", "+00:00"))
        age = (now - stamp).total_seconds()
        items = record["items"]
        if not -5 <= age <= max_age or not isinstance(items, list) or not items:
            raise ValueError("stale health")
        if any(not isinstance(item, dict) or not isinstance(item.get("label"), str)
               or item.get("status") not in ("ok", "warning", "unknown", "offline", "fault")
               or not isinstance(item.get("detail"), str) for item in items):
            raise ValueError("invalid health items")
        return items
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def service_status(record, now, max_age):
    items = health_items(record, now, max_age)
    if items is None:
        return "unknown"
    return worst("fault" if item["status"] == "offline" and item.get("key") != "m5"
                 else "ok" if item["status"] == "offline" else item["status"] for item in items)


def clock_style_spans(config, records, view_name, now, columns, rows, font):
    view = config["views"][view_name]
    if view.get("style") != "around" or columns < 90 or rows < 35 or view_name == "night":
        return []
    _, x, y = clock_geometry(now, font, columns, rows, config.get("show_seconds", True))
    value = now.strftime("%H:%M")
    base = sum(len(font[c][0]) for c in value) + len(value) - 1
    stretch = max(1, min(4, (columns - 14) // base))
    colon_x = x + (len(font[value[0]][0]) + len(font[value[1]][0]) + 2) * stretch
    slots = view.get("slots", {})
    printer_name = slots.get("printers", slots.get("top_left", "printers"))
    health_name = slots.get("health", slots.get("footer", "health"))
    printers = printer_status(records.get(printer_name), now, config["modules"][printer_name]["max_age_seconds"])
    services = service_status(records.get(health_name), now, config["modules"][health_name]["max_age_seconds"])
    return [(y + row * 2 + repeat, colon_x, len(font[":"][row]) * stretch, printers if row < 3 else services)
            for row in range(7) if "1" in font[":"][row] for repeat in range(2)]


def health_summary(record, now, max_age):
    level = service_status(record, now, max_age)
    if level == "fault":
        return "Services [x] fault / 4"
    if level == "warning":
        return "Services [!] need attention / 4"
    if level == "unknown":
        state = "unknown" if health_items(record, now, max_age) is None else "partly unknown"
        return "Services [?] " + state + " / 4"
    return "Services [+] healthy / 4"


def compose(config, records, view_name, now, columns, rows, module_lines, font, demo=False):
    view = config["views"][view_name]
    slots = view.get("slots", {})
    frame = [" " * columns for _ in range(rows)]
    margin, width = 2, columns - 4

    def put(y, x, value, available=None):
        if 0 <= y < rows:
            value = fit(value, columns - x if available is None else available)
            frame[y] = frame[y][:x] + value + frame[y][x + len(value):]

    def centered(y, value):
        value = fit(value, width)
        put(y, max(margin, (columns - len(value)) // 2), value)

    def content(name):
        return module_lines(name, config["modules"][name], records.get(name), now)

    def section(name, x, y, available, capacity, quiet=False):
        if not name:
            return
        lines = content(name)
        heading = config["modules"][name].get("title", name)
        status = lines[0].rpartition(" / ")[2] if " / " in lines[0] else "unavailable"
        show_heading = not quiet or not fresh(records.get(name), now, config["modules"][name]["max_age_seconds"]) or any(line.startswith("Unavailable") for line in lines[1:])
        if show_heading:
            put(y, x, pair(heading, status, available), available)
        values = list(lines[1:])
        if quiet and not show_heading and values:
            if name == "mail":
                values[0] = "Mail / " + values[0]
            elif name == "claude":
                values[0] = "Claude / " + values[0].replace("i7 / CT240: ", "").replace("live CLI session(s)", "live session(s)")
        if name == "reminders":
            body = [re.sub(r" \[[^\]\n]+\]$", "", text(line)).replace("Overdue: ", "Late: ", 1) for line in values]
        else:
            body = [part for line in values for part in (textwrap.wrap(text(line), available) or [""])]
        if len(body) > capacity:
            body = body[:capacity - 1] + [f"+{len(body) - capacity + 1} more lines / full source"]
        for offset, line in enumerate(body):
            put(y + int(show_heading) + offset, x, line, available)

    quiet = view.get("quiet_labels", False)
    heading = "DEMO / FICTIONAL DATA" if demo else ("" if quiet else "Bedroom / ") + view.get("title", view_name)
    date = now.strftime("%a %d %b").upper() if quiet else now.strftime("%A %d %B %Y / %Z")
    put(0, margin, pair(date, heading, width), width)
    art, clock_x, clock_y = clock_geometry(now, font, columns, rows, config.get("show_seconds", True))
    for offset, line in enumerate(art):
        put(clock_y + offset, clock_x, line)
    if config.get("show_seconds", True):
        for offset, line in enumerate(seconds_art(now)):
            put(clock_y + len(art) - 5 + offset, clock_x + len(art[0]) + 2, line)
    navigation = "  ".join(f"[{i + 1} {name.title()}]" if name == view_name else f"{i + 1} {name.title()}" for i, name in enumerate(config["views"]))
    if view_name == "help":
        printer_name = slots.get("printers", "printers")
        health_name = slots.get("health", "health")
        printer_record = records.get(printer_name)
        health_record = records.get(health_name)
        printer_age = config["modules"][printer_name]["max_age_seconds"]
        health_age = config["modules"][health_name]["max_age_seconds"]
        levels = {"ok": "WHITE / checks OK", "warning": "AMBER / needs attention",
                  "fault": "RED / confirmed fault", "unknown": "GREY / unknown or stale"}
        upper = printer_status(printer_record, now, printer_age)
        lower = service_status(health_record, now, health_age)
        printer_items = valid_items(printer_record)
        if not fresh(printer_record, now, printer_age) or not printer_items:
            printer_reasons = ["Unavailable - current printer data missing or stale"]
        else:
            printer_reasons = [item["name"] + ": " + printer_condition(item)[1] for item in printer_items
                               if printer_condition(item)[0] != "ok"] or ["Connected printers OK; no current alert"]
        services = health_items(health_record, now, health_age)
        service_reasons = (["Unavailable - service data missing or stale"] if services is None else
                           [item["label"] + ": " + item["detail"] for item in services
                            if item["status"] not in ("ok",) and not (item["status"] == "offline" and item.get("key") == "m5")]) or ["Current service checks OK; sleeping laptop is normal"]
        pane = (width - 4) // 2
        for x, title, level, reasons in ((margin, "UPPER DOT / PRINTERS", upper, printer_reasons),
                                          (margin + pane + 4, "LOWER DOT / SERVICES", lower, service_reasons)):
            put(2, x, title, pane)
            put(3, x, levels[level], pane)
            capacity = clock_y - 5
            shown = reasons if len(reasons) <= capacity else reasons[:capacity - 1] + [f"+{len(reasons) - capacity + 1} more / see detailed tab"]
            for index, reason in enumerate(shown):
                put(5 + index, x, reason, pane)
        legends = (("WHITE / OK", "Current checks passed", "Idle needs no AI verdict"),
                   ("AMBER / ATTENTION", "Paused / suspicious /", "service warning"),
                   ("RED / FAULT", "Reported failed print /", "confirmed service outage"),
                   ("GREY / UNKNOWN", "Missing / stale data /", "AI coverage unavailable"))
        pane = (width - 9) // 4
        for index, lines in enumerate(legends):
            for offset, line in enumerate(lines):
                put(clock_y + len(art) + 2 + offset, margin + index * (pane + 3), line, pane)
        centered(rows - 4, "AI confidence describes its verdict, not the chance a print will succeed.")
        put(rows - 2, margin, "2 Fleet: printer detail / 4 Servers: service detail / 1 Everyday: clock", width)
        put(rows - 1, margin, pair(navigation, "Tab switch / +/- light / Q console", width), width)
        return frame
    if view_name == "servers":
        health_name = slots.get("health", "health")
        spec = config["modules"][health_name]
        items = health_items(records.get(health_name), now, spec["max_age_seconds"])
        put(2, margin, content(health_name)[0], width)
        if items is None:
            centered(5, "Services [?] unknown")
            centered(6, "Unavailable - health feed stale or invalid")
        else:
            count = min(4, len(items))
            pane = (width - 3 * (count - 1)) // count
            symbols = {"ok": "[+]", "warning": "[!]", "unknown": "[?]", "offline": "[z]", "fault": "[x]"}
            labels = {"ok": "Check passed", "warning": "Needs attention", "unknown": "Check unavailable", "offline": "Offline / asleep", "fault": "Confirmed fault"}
            for index, item in enumerate(items[:count * 2]):
                x = margin + index % count * (pane + 3)
                y = 4 if index < count else clock_y + len(art) + 2
                name = view.get("health_labels", {}).get(item.get("key"), item["label"])
                put(y, x, pair(name, symbols[item["status"]], pane), pane)
                put(y + 1, x, labels[item["status"]], pane)
                detail = textwrap.wrap(text(item["detail"]), pane)
                capacity = min(4, (clock_y if index < count else rows - 2) - y - 2)
                for offset, line in enumerate(detail[:capacity]):
                    put(y + 2 + offset, x, line, pane)
            if len(items) > count * 2:
                put(rows - 2, margin, f"+{len(items) - count * 2} more checks / full source", width)
        put(rows - 1, margin, pair(navigation, "Tab switch / +/- light / Q console", width), width)
        return frame
    shift_y = clock_y + len(art) + 1
    center_name = slots.get("center", "alarm" if view_name == "night" else "shift")
    lines = content(center_name)
    body = lines[1:]
    stale = "STALE" in lines[0]
    for offset, line in enumerate(body[:3]):
        prefix = ("Work STALE / " if stale else ("" if quiet else "Work / ")) if offset == 0 and center_name == "shift" else ""
        centered(shift_y + offset, prefix + text(line))
    if quiet:
        pane = (width - 6) // 3
        for index, key in enumerate(("top_left", "top_middle", "top_right")):
            section(slots.get(key, ("reminders", "mail", "claude")[index]), margin + index * (pane + 3), 2, pane, clock_y - 4, quiet=True)
        bottom_y = max(shift_y + 4, rows - 8)
        left_width = round(width * .57)
        printer_name = slots.get("printers", "printers")
        spec = config["modules"][printer_name]
        record = records.get(printer_name)
        lines = content(printer_name)
        items = valid_items(record)
        items_valid = bool(items) and not any(line.startswith("Unavailable") for line in lines[1:])
        if not fresh(record, now, spec["max_age_seconds"]) or not items_valid:
            status = lines[0].rpartition(" / ")[2] if " / " in lines[0] else "unavailable"
            put(bottom_y - 1, margin, pair(spec.get("title", printer_name), status, left_width), left_width)
        if items_valid:
            selected = items[:view.get("printer_limit", 2)]
            for index, item in enumerate(selected):
                for offset, line in enumerate(short_printer(item, left_width, quiet=True)):
                    put(bottom_y + index * 3 + offset, margin, line, left_width)
            if len(items) > len(selected):
                put(rows - 2, margin, f"+{len(items) - len(selected)} more printers / Fleet", left_width)
        else:
            for offset, line in enumerate(lines[1:rows - 1 - bottom_y]):
                put(bottom_y + offset, margin, line, left_width)
        section(slots.get("bottom_right", "agenda"), margin + left_width + 4, bottom_y, width - left_width - 4, rows - 2 - bottom_y, quiet=True)
        name = slots.get("footer", "health")
        level = service_status(records.get(name), now, config["modules"][name]["max_age_seconds"])
        summary = "Services " + {"ok": "[+]", "warning": "[!]", "unknown": "[?]", "fault": "[x]"}[level] + " / 4"
        put(rows - 1, margin, pair(navigation, summary, width), width)
        return frame
    if view_name != "night":
        printer_name = slots.get("top_left", "printers")
        printer_spec = config["modules"][printer_name]
        printer_record = records.get(printer_name)
        printer_lines = content(printer_name)
        items = valid_items(printer_record)
        items_valid = items is not None and not any(line.startswith("Unavailable") for line in printer_lines[1:])
        top_capacity = clock_y - 3
        if view_name == "fleet" and items_valid:
            count = min(3, max(1, len(items)))
            pane = (width - 3 * (count - 1)) // count
            put(2, margin, pair("Printers / " + str(len(items)), printer_lines[0].rpartition(" / ")[2], width))
            selected = items[:view.get("printer_limit", 6)]
            for index, item in enumerate(selected):
                detail = printer_card(item, pane) if len(selected) <= 2 else short_printer(item, pane)
                x, y = margin + (index % count) * (pane + 3), 3 + (index // count) * 4
                for offset, line in enumerate(detail[:min(top_capacity, 7)]):
                    put(y + offset, x, line, pane)
            if len(items) > len(selected):
                put(clock_y - 1, margin, f"+{len(items) - len(selected)} more printers / full source")
        else:
            left_width = round(width * .57)
            put(2, margin, pair(printer_spec.get("title", printer_name) + (" / " + str(len(items)) if items_valid else ""), printer_lines[0].rpartition(" / ")[2], left_width))
            if items_valid:
                selected = items[:view.get("printer_limit", 2)]
                for index, item in enumerate(selected):
                    for offset, line in enumerate(short_printer(item, left_width)):
                        put(3 + index * 3 + offset, margin, line, left_width)
                if len(items) > len(selected):
                    put(clock_y - 1, margin, f"+{len(items) - len(selected)} more printers / Fleet")
            else:
                for offset, line in enumerate(printer_lines[1:top_capacity + 1]):
                    put(3 + offset, margin, line, left_width)
            section(slots.get("top_right", "agenda"), margin + left_width + 4, 2, width - left_width - 4, top_capacity)
        bottom_y = max(shift_y + 4, rows - 8)
        pane = (width - 6) // 3
        for index, key in enumerate(("bottom_left", "bottom_middle", "bottom_right")):
            section(slots.get(key, ("reminders", "mail", "claude")[index]), margin + index * (pane + 3), bottom_y, pane, max(1, rows - 5 - bottom_y))
        health_name = slots.get("footer", "health")
        spec = config["modules"].get(health_name, {"max_age_seconds": 180})
        summary = health_summary(records.get(health_name), now, spec["max_age_seconds"])
    else:
        summary = "Tab switch / +/- light / Q console"
    put(rows - 1, margin, pair(navigation, summary, width), width)
    return frame
