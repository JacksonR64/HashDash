import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import collect_host as host
import collect_macos as mac


class CollectorTests(unittest.TestCase):
    def test_terminal_print_status_does_not_reuse_old_eta(self):
        now = datetime.now(timezone.utc)
        for state in ("FAILED", "FINISH"):
            line = host.printer_lines("A1", {"connected": True, "state": state, "remaining_time": 81}, now)[0]
            self.assertNotIn("min left", line)
        self.assertIn("OFFLINE", host.printer_lines("A1", {"connected": False}, now)[0])

    def test_active_print_has_progress_and_estimate(self):
        now = datetime(2026, 10, 25, 14, tzinfo=timezone.utc)
        line = host.printer_lines("Mini", {"connected": True, "state": "RUNNING", "progress": 72, "remaining_time": 38}, now)[0]
        self.assertIn("72%", line)
        self.assertIn("14:38", line)

    def test_leave_requests_are_never_shifts(self):
        base = {"calendar": "Carpet Shop - Jackson (Workforce)", "allday": False}
        for title in ("Leave request for carpet shop", "Holiday", "Time off", "Work @ Leave request"):
            self.assertFalse(mac.is_work_event(dict(base, title=title)))
        self.assertTrue(mac.is_work_event(dict(base, title="Work @ Bartender Club")))

    def test_earliest_shift_across_calendar_and_rota_and_overnight_end(self):
        now = datetime(2026, 10, 25, 14, tzinfo=mac.LONDON)
        events = [{"calendar": "Workforce", "allday": False, "title": "Work @ Club", "start": "2026-10-31T22:00:00Z", "end": "2026-11-01T05:00:00Z"}]
        with patch.object(mac, "rota_candidates", return_value=([(now + timedelta(days=10), ["Later rota shift"])], True)):
            lines = mac.rota_lines(Path("unused"), now, events)
        self.assertIn("22:00-05:00 next day", lines[0])
        self.assertIn("not supplied", lines[1])

    def test_failed_calendar_access_does_not_overwrite_previous_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shift.json"
            path.write_text('{"previous":"valid"}')
            with self.assertRaises(RuntimeError):
                mac.collect_rota(Path(directory), datetime.now(mac.LONDON), None)
            self.assertEqual(json.loads(path.read_text()), {"previous": "valid"})

    def test_atomic_private_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            host.write_module(Path(directory), "test", ["Safe display line"])
            path = Path(directory) / "test.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["lines"], ["Safe display line"])
            self.assertEqual(len(list(Path(directory).iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
