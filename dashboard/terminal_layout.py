"""Panel layout for the Linux console; cached data only, no terminal side effects."""
import math
import textwrap
import unicodedata

# Single-stroke digits stay legible when console cells become solid pixels.
DIGITS = {
    "0": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00110", "01000", "10000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("10010", "10010", "10010", "11111", "00010", "00010", "00010"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    ":": ("0", "1", "1", "0", "1", "1", "0"),
}


def safe(value):
    # One console cell per character keeps borders aligned with accented names too.
    value = unicodedata.normalize("NFC", str(value))
    return "".join(c if c.isprintable() and unicodedata.east_asian_width(c) not in ("W", "F")
                   and not unicodedata.combining(c) else " " for c in value)


def text(value):
    return " ".join(safe(value).split())


def fit(value, width):
    value = safe(value)
    return value if len(value) <= width else (value[:width - 3] + "..." if width >= 3 else value[:width])


def pair(left, right, width):
    right = fit(text(right), max(0, width // 2))
    left = fit(text(left), max(0, width - len(right) - 2))
    return left + " " * max(0, width - len(left) - len(right)) + right


def box(title, status, body, width, centered=False):
    inside = width - 6
    heading = " " + pair(title, status, width - 6) + " "
    frame = ["┌─" + heading + "─┐", "│" + " " * (width - 2) + "│"]
    for line in body:
        line = fit(line, inside)
        line = line.center(inside) if centered else line.ljust(inside)
        frame.append("│  " + line + "  │")
    frame += ["│" + " " * (width - 2) + "│", "└" + "─" * (width - 2) + "┘"]
    return frame


def valid_items(record):
    if not isinstance(record, dict) or not isinstance(record.get("items"), list):
        return None
    items = record["items"]
    if any(not isinstance(item, dict) or not isinstance(item.get("name"), str)
           or not isinstance(item.get("summary"), str) or not isinstance(item.get("checks"), list)
           or any(not isinstance(line, str) for line in item["checks"]) for item in items):
        return None
    return items


def printer_card(item, width):
    state = str(item.get("state", "unknown")).upper()
    connected = item.get("connected") is True
    active = connected and state in ("RUNNING", "PRINTING", "PAUSE", "PAUSED", "PREPARE")
    label = {"RUNNING": "Printing", "PRINTING": "Printing", "PAUSE": "Paused", "PAUSED": "Paused",
             "PREPARE": "Preparing", "FAILED": "Last print failed", "FINISH": "Completed", "IDLE": "Idle"}.get(state, state.title())
    if not connected:
        label = "Unavailable" if state == "UNAVAILABLE" else "Offline"
    lines = [pair(item["name"], label, width)]
    if active:
        try:
            progress = float(item["progress"])
            if not math.isfinite(progress) or not 0 <= progress <= 100:
                raise ValueError("invalid progress")
            bar_width = max(1, width - 7)
            filled = round(progress / 100 * bar_width)
            lines.append("█" * filled + "░" * (bar_width - filled) + f"  {progress:3.0f}%")
        except (KeyError, TypeError, ValueError):
            lines.append("Progress unavailable")
        detail = " / ".join(item["summary"].split(" / ")[2:])
        if detail:
            lines.append(fit(detail, width))
    elif not connected:
        lines.append(fit(item["summary"], width))
    for line in item["checks"]:
        line = text(line)
        if line.startswith("PG "):
            line = "Guard " + line[3:]
        if line.startswith("HTTPError: HTTP Error 503"):
            line = "AI check service unavailable (HTTP 503)"
        lines.append(fit(line, width))
    return lines


def printer_body(items, width, columns, limit):
    # Keep whole printers together, with an explicit overflow count.
    selected = items[:limit]
    card_width = (width - 4 * (columns - 1)) // columns
    body = []
    for offset in range(0, len(selected), columns):
        cards = [printer_card(item, card_width) for item in selected[offset:offset + columns]]
        if body:
            body += ["", "─" * width, ""]
        for row in range(max(map(len, cards))):
            body.append("    ".join((card[row] if row < len(card) else "").ljust(card_width) for card in cards).rstrip())
    if len(items) > limit:
        body += ["", f"+{len(items) - limit} more printers / use Fleet or increase this view's printer limit"]
    return body or ["No printers returned by BamBuddy"]


def compose(config, records, view_name, now, columns, rows, module_lines, demo=False):
    view = config["views"][view_name]
    margin, gap = 6, 4
    width = columns - margin * 2
    frame = ["", " " * margin + pair(now.strftime("%A %d %B %Y / %Z"),
                                      "Bedroom / " + text(view.get("title", view_name)), width), ""]
    time_text = now.strftime("%H:%M:%S" if config.get("show_seconds") else "%H:%M")
    glyph_width = sum(len(DIGITS[c][0]) for c in time_text) + len(time_text) - 1
    horizontal = max(1, min(4, (width - 8) // glyph_width))
    vertical = 3 if view_name == "night" else (1 if view.get("compact_clock") else 2)
    art = []
    for row in range(7):
        pixels = "0".join(DIGITS[c][row] for c in time_text)
        line = "".join(("█" if pixel == "1" else " ") * horizontal for pixel in pixels)
        art.extend([line] * vertical)
    if view_name == "night":
        frame += [""] * max(0, (rows - len(art) - 13) // 2)
    frame += [line.center(columns) for line in art] + [""]
    if demo:
        frame += ["DEMO - FICTIONAL DATA".center(columns), ""]

    def panel(name, panel_width, hero=False):
        spec = config["modules"][name]
        record = records.get(name)
        content = module_lines(name, spec, record, now)
        title = spec.get("title", name)
        status = content[0].rpartition(" / ")[2] or "Unavailable"
        body = content[1:]
        items = valid_items(record) if spec.get("format") == "printers" else None
        # Invalid source timestamps/lines must not be bypassed by richer items.
        if items is not None and not any(line.startswith("Unavailable") for line in body):
            title = f"{title} / {len(items)}"
            body = printer_body(items, panel_width - 6, view.get("printer_columns", 1), view.get("printer_limit", 2))
        elif hero:
            body = [part for line in body for part in textwrap.wrap(text(line), panel_width - 12)]
        else:
            body = [part for line in body for part in (textwrap.wrap(text(line), panel_width - 6) or [""])]
        return box(title, status, body, panel_width, centered=hero)

    if view.get("hero"):
        frame += [" " * margin + line for line in panel(view["hero"], width, True)] + [""]
    stacks = view.get("columns")
    if stacks:
        pane_width = (width - gap * (len(stacks) - 1)) // len(stacks)
        panes = []
        for stack in stacks:
            pane = []
            for name in stack:
                if pane:
                    pane.append("")
                pane += panel(name, pane_width)
            panes.append(pane)
        for row in range(max(map(len, panes))):
            frame.append(" " * margin + (" " * gap).join((pane[row] if row < len(pane) else "").ljust(pane_width) for pane in panes).rstrip())
        frame.append("")
    for names in view.get("rows", []):
        pane_width = (width - gap * (len(names) - 1)) // len(names)
        panes = [panel(name, pane_width, view_name == "night") for name in names]
        frame += [" " * margin + (" " * gap).join((pane[i] if i < len(pane) else "").ljust(pane_width) for pane in panes).rstrip()
                  for i in range(max(map(len, panes)))] + [""]
    footer = "   ".join((f"[{i + 1} {text(key).title()}]" if key == view_name else f"{i + 1} {text(key).title()}")
                        for i, key in enumerate(config["views"]))
    footer = pair(footer, "Tab switch / +/- brightness / Q console", width)
    if len(frame) > rows - 3:
        frame = frame[:rows - 4] + [" " * margin + "More content / switch to Fleet or reduce the modules in this view"]
    frame += [""] * max(0, rows - 3 - len(frame))
    frame += [" " * margin + "─" * width, " " * margin + footer, ""]
    return [line[:columns] for line in frame[:rows]]
