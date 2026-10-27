import unittest

from terminal_layout import box, pair, printer_card


class TerminalLayoutTests(unittest.TestCase):
    def test_box_and_pair_preserve_exact_column_width(self):
        for width in (36, 82, 168):
            self.assertEqual(len(pair("Name", "Printing", width)), width)
            self.assertTrue(all(len(line) == width for line in box("Printers", "updated 2s ago", ["Left     Right", "x" * 300], width)))

    def test_progress_bar_uses_only_connected_active_telemetry(self):
        item = {"name": "Mini", "state": "RUNNING", "connected": True, "progress": 50,
                "summary": "running / 50% / ~38 min left / ~16:00", "checks": []}
        active = printer_card(item, 76)
        self.assertIn("50%", active[1])
        self.assertIn("█", active[1])
        self.assertIn("░", active[1])
        self.assertIn("~38 min left", active[2])
        for state in ("FAILED", "FINISH", "IDLE"):
            lines = "\n".join(printer_card(dict(item, state=state), 76))
            self.assertNotIn("50%", lines)
            self.assertNotIn("~38 min left", lines)
        self.assertNotIn("█", "\n".join(printer_card(dict(item, connected=False), 76)))

    def test_invalid_progress_cannot_become_a_fake_empty_or_full_bar(self):
        for value in (None, "bad", float("nan"), -1, 101):
            item = {"name": "Mini", "state": "RUNNING", "connected": True, "progress": value,
                    "summary": "running", "checks": []}
            self.assertIn("Progress unavailable", printer_card(item, 76))


if __name__ == "__main__":
    unittest.main()
