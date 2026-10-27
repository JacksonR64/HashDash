import json
import unittest
from datetime import datetime, timezone

from printguard_display import guard_lines, parse_records


NOW = datetime(2026, 10, 25, 15, tzinfo=timezone.utc)
STAMP = NOW.timestamp()


def row(message, timestamp=STAMP):
    return {"MESSAGE": message, "__REALTIME_TIMESTAMP": str(int(timestamp * 1_000_000))}


def verdict(pid=1, timestamp=STAMP - 30, result=None, job="current job"):
    result = result or {"verdict": "ok", "confidence": 0.8, "reason": "Layers look consistent"}
    return row(f"watch printer {pid} ({job} 20.0% layer 3, hits [False]): " + json.dumps(result), timestamp)


class PrintGuardTests(unittest.TestCase):
    def setUp(self):
        self.status = {"connected": True, "state": "RUNNING", "subtask_name": "current job"}
        records, errors = parse_records([verdict()])
        self.guard = {"active": True, "armed": True, "watched": [1, 2], "swap": [1],
                      "interval": 300, "verdicts": records, "errors": errors,
                      "first": {"1": {"job": "current job", "t0": STAMP - 100}}}
        self.obico = {"is_running": True, "per_printer": {"1": {"class": "safe", "score": 0.002}}}

    def display(self, guard=None, obico=None):
        return guard_lines(1, self.status, self.guard if guard is None else guard,
                           self.obico if obico is None else obico, NOW)

    def test_newest_per_printer_even_when_log_order_changes(self):
        records, _ = parse_records([verdict(2), verdict(timestamp=STAMP), verdict(timestamp=STAMP - 60)])
        self.assertEqual(set(records), {1, 2})
        self.assertEqual(records[1]["timestamp"], STAMP)
        self.assertEqual(records[1]["job"], "current job")

    def test_truncated_reason_recovers_only_intact_confidence(self):
        records, _ = parse_records([row('watch printer 1 (current job): {"verdict":"failure", "confidence":0.6,"reason":"cut')])
        self.assertEqual(records[1]["confidence"], 0.6)
        self.assertIn("truncated", records[1]["reason"])
        bad, _ = parse_records([row('watch printer 1 (current job): {"verdict":"failure", "confidence":0.')])
        self.assertEqual(bad, {})

    def test_malformed_rows_and_invalid_confidence_are_ignored(self):
        records, _ = parse_records([None, [], row([]), {}, verdict(result={"verdict": "ok", "confidence": 2}),
                                     verdict(result={"verdict": "ok", "confidence": float("nan")})])
        self.assertEqual(records, {})

    def test_newer_error_prevents_old_all_clear(self):
        self.guard["errors"] = {1: {"timestamp": STAMP - 5, "reason": "URLError: No route to host"}}
        lines = "\n".join(self.display())
        self.assertIn("AI unavailable", lines)
        self.assertIn("camera network unreachable", lines)
        self.assertNotIn("looks OK", lines)
        self.assertIn("Obico: safe", lines)

    def test_error_before_current_job_does_not_cover_current_result(self):
        self.guard["errors"] = {1: {"timestamp": STAMP - 200, "reason": "No route to host"}}
        self.assertIn("looks OK", "\n".join(self.display()))

    def test_stale_and_earlier_job_are_explicit(self):
        record = self.guard["verdicts"][1]
        record["timestamp"] = STAMP - 800
        self.guard["first"] = {}
        self.assertIn("AI STALE", "\n".join(self.display()))
        record["job"] = "previous job"
        self.assertIn("earlier-job AI", "\n".join(self.display()))

    def test_confidence_and_raw_detector_score_are_separate(self):
        self.guard["verdicts"][1].update(verdict="failure", confidence=0.6)
        lines = self.display()
        text = "\n".join(lines)
        self.assertIn("suspected failure", text)
        self.assertIn("AI confidence 60%", text)
        self.assertIn("suspicion score 0.002", text)
        self.assertNotIn("99.8%", text)
        self.assertTrue(all(len(line) <= 84 for line in lines))

    def test_missing_stopped_and_unconfigured_guard_are_explicit(self):
        self.assertIn("status unavailable", "\n".join(self.display(guard={})))
        self.guard["active"] = False
        self.assertIn("STOPPED", "\n".join(self.display()))
        self.guard["watched"] = []
        self.guard["swap"] = []
        self.assertIn("not configured", "\n".join(self.display()))

    def test_missing_detector_and_offline_printer_do_not_look_healthy(self):
        self.assertIn("no current result", "\n".join(self.display(obico={})))
        self.status["connected"] = False
        text = "\n".join(self.display())
        self.assertIn("offline", text)
        self.assertNotIn("looks OK", text)
        self.assertNotIn("Obico: safe", text)

    def test_idle_printer_has_no_live_detector_claim(self):
        self.status["state"] = "FAILED"
        text = "\n".join(self.display())
        self.assertIn("last AI", text)
        self.assertNotIn("Obico", text)


if __name__ == "__main__":
    unittest.main()
