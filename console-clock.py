#!/usr/bin/python3
"""Large local-console clock; Q returns to the ordinary console."""
import curses
import signal
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


FONT = {
    "0": ("01110", "11011", "11011", "11011", "11011", "11011", "01110"),
    "1": ("00110", "01110", "00110", "00110", "00110", "00110", "01111"),
    "2": ("01110", "11011", "00011", "00110", "01100", "11000", "11111"),
    "3": ("11110", "00011", "00011", "01110", "00011", "00011", "11110"),
    "4": ("11011", "11011", "11011", "11111", "00011", "00011", "00011"),
    "5": ("11111", "11000", "11000", "11110", "00011", "00011", "11110"),
    "6": ("01110", "11000", "11000", "11110", "11011", "11011", "01110"),
    "7": ("11111", "00011", "00011", "00110", "00110", "01100", "01100"),
    "8": ("01110", "11011", "11011", "01110", "11011", "11011", "01110"),
    "9": ("01110", "11011", "11011", "01111", "00011", "00011", "01110"),
    ":": ("0", "1", "1", "0", "1", "1", "0"),
}
BRIGHTNESS = Path("/var/lib/console-clock/brightness")


def set_brightness(percent):
    percent = max(5, min(100, percent))
    try:
        panel = Path("/sys/class/backlight/acpi_video0")
        maximum = int((panel / "max_brightness").read_text())
        (panel / "brightness").write_text(str(max(1, round(maximum * percent / 100))))
        BRIGHTNESS.write_text(str(percent))
    except (OSError, ValueError) as error:
        print("Backlight adjustment failed:", error, file=sys.stderr)
        return None
    return percent


def big_time(text, horizontal, vertical):
    lines = []
    for row in range(7):
        pixels = "0".join(FONT[character][row] for character in text)
        line = "".join(("#" if pixel == "1" else " ") * horizontal for pixel in pixels)
        lines.extend([line] * vertical)
    return lines


def clock(screen):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    ink = 0
    if curses.has_colors():
        curses.start_color()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
        ink |= curses.color_pair(1)
    try:
        level = int(BRIGHTNESS.read_text())
    except (OSError, ValueError):
        level = 30
    level = set_brightness(level)
    screen.timeout(200)
    previous = None
    while True:
        now = datetime.now(ZoneInfo("Europe/London"))
        rows, columns = screen.getmaxyx()
        signature = (now.strftime("%Y-%m-%d %H:%M:%S"), rows, columns)
        if signature != previous:
            previous = signature
            screen.erase()
            text = now.strftime("%H:%M:%S" if columns >= 43 else "%H:%M")
            width = sum(len(FONT[character][0]) for character in text) + len(text) - 1
            horizontal = max(1, min(4, (columns - 4) // width))
            vertical = max(1, min(3, (rows - 10) // 7))
            art = big_time(text, horizontal, vertical)
            top = max(2, (rows - len(art) - 5) // 2)

            def write(row, line, style=0):
                if 0 <= row < rows and columns > 1:
                    line = line[: columns - 1]
                    try:
                        screen.addstr(row, max(0, (columns - len(line)) // 2), line, style)
                    except curses.error:
                        pass

            write(top - 2, "I 7   M A C B O O K", ink)
            for offset, line in enumerate(art):
                write(top + offset, line, ink)
            write(top + len(art) + 2, now.strftime("%A  %d %B %Y"))
            write(top + len(art) + 4, "LONDON  /  " + now.tzname())
            footer = "Q: CONSOLE"
            if level is not None:
                footer = f"-/+: BRIGHTNESS {level}%    " + footer
            write(rows - 2, footer)
            screen.refresh()
        key = screen.getch()
        if key in (ord("q"), ord("Q")):
            return
        if level is not None and key in (ord("-"), ord("_"), ord("+"), ord("=")):
            level = set_brightness(level + (5 if key in (ord("+"), ord("=")) else -5))
            previous = None


if __name__ == "__main__":
    def stop(_signal, _frame):
        raise SystemExit(0)

    for stop_signal in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(stop_signal, stop)
    curses.wrapper(clock)
