import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dashboard as d


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.config = d.load_config(d.HERE / "layout.json")
        self.now = datetime(2026, 10, 25, 14, tzinfo=timezone.utc)

    def test_all_views_keep_clock_when_every_feed_is_missing(self):
        for name in self.config["views"]:
            frame = d.render(self.config, {}, name, self.now, 180, 56)
            self.assertEqual(len(frame), 56)
            date = self.now.astimezone(d.LONDON).strftime("%a %d %b").upper() if self.config["views"][name].get("quiet_labels") else "Sunday 25 October 2026 / GMT"
            self.assertIn(date, "\n".join(frame))
            self.assertIn("Unavailable", "\n".join(frame))

    def test_stale_retains_old_data_and_its_age(self):
        record = {"updated_at": (self.now - timedelta(minutes=5)).isoformat(), "lines": ["A1 printing"]}
        lines = d.module_lines("printers", self.config["modules"]["printers"], record, self.now)
        self.assertIn("STALE - 5m old", lines[0])
        self.assertEqual(lines[1], "A1 printing")

    def test_bad_timestamp_does_not_turn_into_fresh_or_empty_data(self):
        for timestamp in ("bad", "2026-10-25T14:00:00", "2099-01-01T00:00:00Z"):
            lines = d.module_lines("shift", self.config["modules"]["shift"], {"updated_at": timestamp, "lines": []}, self.now)
            self.assertIn("invalid data", lines[-1])

    def test_control_characters_cannot_create_terminal_rows(self):
        self.assertEqual(d.clean("hello\nworld\x1b\t"), "hello world")

    def test_corrupt_source_does_not_hide_healthy_source(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "shift.json").write_text("not JSON")
            (directory / "printers.json").write_text('{"updated_at":"2026-10-25T14:00:00Z","lines":["A1 idle"]}')
            records = d.read_modules(self.config, directory)
            self.assertIsNone(records["shift"])
            self.assertEqual(records["printers"]["lines"], ["A1 idle"])

    def test_fleet_overflow_is_explicit(self):
        record = {"updated_at": self.now.isoformat(), "lines": [f"Printer {i}" for i in range(20)]}
        lines = d.module_lines("printers", self.config["modules"]["printers"], record, self.now)
        self.assertIn("more lines", lines[-1])

    def test_tiny_terminals_never_overflow(self):
        for width, height in ((1, 1), (40, 20), (80, 25), (180, 56)):
            frame = d.render(self.config, d.demo_records(self.now), "everyday", self.now, width, height, True)
            self.assertEqual(len(frame), height)
            self.assertTrue(all(len(line) <= width for line in frame))

    def test_clock_handles_both_sides_of_autumn_time_change(self):
        before = datetime(2026, 10, 25, 0, 30, tzinfo=timezone.utc)
        after = datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)
        self.assertIn("BST", "\n".join(d.render(self.config, {}, "night", before, 180, 56)))
        self.assertIn("GMT", "\n".join(d.render(self.config, {}, "night", after, 180, 56)))

    def test_panel_layout_keeps_live_sized_content_and_footer_visible(self):
        self.config["views"]["everyday"]["style"] = "panels"
        records = d.demo_records(self.now)
        records["shift"]["lines"].append("Example venue rota unavailable from Mon 26 Oct")
        records["reminders"]["lines"].append("+207 other incomplete reminders")
        records["claude"]["lines"].append("code-eb: idle / reported 627m ago")
        records["printers"]["items"][1]["checks"] = records["printers"]["items"][0]["checks"][:3]
        frame = d.render(self.config, records, "everyday", self.now, 180, 56)
        full = "\n".join(frame)
        for label in ("Printers / 2", "To do", "Flagged mail", "Claude Code", "AI confidence", "[1 Everyday]"):
            self.assertIn(label, full)
        self.assertNotIn("More content", full)
        # Every outer right edge stays on the same console column.
        borders = [line for line in frame if line.lstrip().startswith(("┌", "│", "└"))]
        self.assertTrue(all(line[6] in "┌│└" or line[92] in "┌│└" for line in borders))
        self.assertTrue(all(len(line) <= 180 for line in frame))

    def test_six_printer_fleet_uses_whole_cards_in_two_columns(self):
        records = d.demo_records(self.now)
        sample = records["printers"]["items"][0]
        records["printers"]["items"] = [dict(sample, name=f"Printer {i}") for i in range(1, 8)]
        frame = "\n".join(d.render(self.config, records, "fleet", self.now, 180, 56))
        for i in range(1, 7):
            self.assertIn(f"Printer {i}", frame)
        self.assertIn("+1 more printers", frame)
        self.assertNotIn("Printer 7", frame)
        self.assertNotIn("More content", frame)

    def test_rich_items_do_not_bypass_invalid_source_timestamp(self):
        records = d.demo_records(self.now)
        records["printers"]["updated_at"] = "bad"
        frame = "\n".join(d.render(self.config, records, "everyday", self.now, 180, 56))
        self.assertIn("invalid data", frame)
        self.assertNotIn("suspicion score", frame)

    def test_legacy_lines_still_render_and_malformed_rich_items_fall_back(self):
        for items in (None, [None], [{"name": "bad", "summary": "bad", "checks": 42}]):
            records = {"printers": {"updated_at": self.now.isoformat(), "lines": ["Legacy printer summary"], "items": items}}
            frame = "\n".join(d.render(self.config, records, "everyday", self.now, 180, 56))
            self.assertIn("Legacy printer summary", frame)

    def test_terminal_geometry_and_controls_in_printer_names(self):
        records = d.demo_records(self.now)
        records["printers"]["items"][0]["name"] = "Test\n\x1b[2J😀printer"
        frame = d.render(self.config, records, "everyday", self.now, 180, 56)
        self.assertEqual(len(frame), 56)
        self.assertNotIn("\x1b", "\n".join(frame))
        self.assertNotIn("😀", "\n".join(frame))


if __name__ == "__main__":
    unittest.main()
