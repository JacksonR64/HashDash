#!/usr/bin/env python3
"""Render the real dashboard as SVG, with deterministic fictional data only."""
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard"))
import dashboard as app
from around_layout import clock_style_spans


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("everyday", "fleet", "night", "servers", "help"), default="everyday")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/preview.svg")
    args = parser.parse_args()
    now = datetime(2026, 10, 27, 19, 42, 8, tzinfo=timezone.utc)
    config = app.load_config(ROOT / "dashboard/layout.json")
    records = app.demo_records(now)
    records["printers"]["items"][0]["checks"][0] = "PG armed / last AI: uncertain"
    records["health"] = {"updated_at": now.isoformat(), "lines": ["Fictional service examples"], "items": [
        {"key": "i7", "label": "Host One", "status": "ok", "detail": "Example host checks passed"},
        {"key": "i5", "label": "Host Two", "status": "ok", "detail": "Example host checks passed"},
        {"key": "ha_flat", "label": "HA One", "status": "ok", "detail": "Example endpoint responding"},
        {"key": "ha_house", "label": "HA Two", "status": "ok", "detail": "Example endpoint responding"},
        {"key": "router", "label": "Router", "status": "ok", "detail": "Example heartbeat current"},
        {"key": "internet", "label": "Net", "status": "ok", "detail": "Example WAN check passed"},
        {"key": "m5", "label": "Laptop", "status": "offline", "detail": "Example laptop asleep"},
        {"key": "tailscale", "label": "Tailnet", "status": "ok", "detail": "Example backend running"}]}
    frame = app.render(config, records, args.view, now, 120, 37, demo=True)
    assert len(frame) == 37 and all(len(line) == 120 for line in frame)
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 900" role="img" aria-label="HashDash: fictional demo data">',
           '<rect width="1440" height="900" fill="#080808"/>',
           '<g fill="#eeeeee" font-family="Courier New,monospace" font-size="20" font-weight="400">']
    for row, line in enumerate(frame):
        for match in re.finditer(r"\S+", line):
            svg.append(f'<text x="{match.start() * 12}" y="{row * 24 + 20}" textLength="{len(match[0]) * 12}" lengthAdjust="spacingAndGlyphs">{escape(match[0])}</text>')
    colours = {"ok": "#eeeeee", "warning": "#e9bb6c", "fault": "#ef8585", "unknown": "#888888"}
    for row, col, length, status in clock_style_spans(config, records, args.view, now, 120, 37, app.CLOCK["FONT"]):
        svg.append(f'<text x="{col * 12}" y="{row * 24 + 20}" fill="{colours[status]}" textLength="{length * 12}" lengthAdjust="spacingAndGlyphs">{escape(frame[row][col:col + length])}</text>')
    svg.extend(("</g>", "</svg>"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(svg) + "\n")
    print(args.output)


if __name__ == "__main__":
    main()
