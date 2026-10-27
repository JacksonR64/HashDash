import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import dashboard as d
from around_layout import health_items, health_summary, short_printer, clock_geometry, seconds_art, clock_style_spans, service_status
from status_indicators import printer_condition, printer_status
from collect_health import internet_check, resource_problems, pve_check, tailnet_checks


class AroundLayoutTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 26, 17, 30, 8, tzinfo=timezone.utc)
        self.config = d.load_config(d.HERE / "layout.json")
        self.records = d.demo_records(self.now)
        self.records["health"] = {"updated_at": self.now.isoformat(), "lines": [],
                                  "items": [{"label": "i7/PVE", "status": "warning", "detail": "go2rtc-flat stopped"},
                                            {"label": "HAflat", "status": "ok", "detail": "HTTP endpoint responding"}]}

    def test_everyday_and_fleet_keep_identical_hash_clock_and_small_seconds(self):
        frames = [d.render(self.config, self.records, mode, self.now, 120, 37) for mode in ("everyday", "fleet", "night", "servers")]
        clocks = [[(i, line.index("#"), line.rfind("#")) for i, line in enumerate(frame) if "#" in line] for frame in frames]
        self.assertTrue(all(clock == clocks[0] for clock in clocks))
        self.assertEqual(len(clocks[0]), 14)
        self.assertTrue(all(len(frame) == 37 and all(len(line) == 120 for line in frame) for frame in frames))
        art, x, y = clock_geometry(self.now, d.CLOCK["FONT"], 120, 37)
        for row, value in enumerate(seconds_art(self.now)):
            self.assertEqual(frames[0][y + 9 + row][x + len(art[0]) + 2:x + len(art[0]) + 9], value)
        self.assertNotIn("█", "\n".join(frames[0]))

    def test_seconds_only_change_small_side_display(self):
        a = d.render(self.config, self.records, "everyday", self.now, 120, 37)
        b = d.render(self.config, self.records, "everyday", self.now + timedelta(seconds=1), 120, 37)
        art, x, y = clock_geometry(self.now, d.CLOCK["FONT"], 120, 37)
        edge = x + len(art[0]) + 2
        self.assertNotEqual(a, b)
        for row, (before, after) in enumerate(zip(a, b)):
            self.assertEqual(before[:edge], after[:edge])
            if before != after:
                self.assertIn(row, range(y + 9, y + 14))
                self.assertEqual(before[edge + 7:], after[edge + 7:])

    def test_modules_surround_clock_and_health_is_only_a_short_footer(self):
        frame = d.render(self.config, self.records, "everyday", self.now, 120, 37)
        full = "\n".join(frame)
        for label in ("Mail /", "Claude /", "Collect parcel", "[1 Everyday]", "4 Servers", "Services [!] / 4"):
            self.assertIn(label, full)
        self.assertIn("Collect parcel", frame[2])
        self.assertIn("A1 mini", frame[29])
        self.assertIn("Appointment", "\n".join(frame[29:35]))
        self.assertIn("Guard: looks OK", full)
        for label in ("i7/PVE", "go2rtc-flat stopped", "updated", "conf 80%"):
            self.assertNotIn(label, full)
        self.assertEqual(sum("Services " in line for line in frame), 1)
        self.assertTrue(all("#" not in line for line in frame[29:]))

    def test_old_and_invalid_health_cannot_show_live_ticks(self):
        for record in (None, {}, {"updated_at": "bad"}, dict(self.records["health"], updated_at=(self.now - timedelta(minutes=5)).isoformat()),
                       dict(self.records["health"], items=[{"label": "broken"}])):
            summary = health_summary(record, self.now, 180)
            self.assertIn("[?]", summary)
            self.assertNotIn("[+]", summary)
            self.assertIsNone(health_items(record, self.now, 180))
            self.records["health"] = record
            servers = "\n".join(d.render(self.config, self.records, "servers", self.now, 120, 37))
            self.assertIn("Services [?] unknown", servers)
            self.assertNotIn("go2rtc-flat stopped", servers)

    def test_servers_show_all_checks_and_reasons_without_everyday_modules(self):
        checks = [("i7", "i7/PVE", "warning", "go2rtc-flat stopped"),
                  ("i5", "i5/PVE", "warning", "TLS certificate expired"),
                  ("ha_flat", "HAflat", "ok", "HTTP endpoint responding"),
                  ("ha_house", "HAhouse", "ok", "HTTP endpoint responding"),
                  ("router", "OpenWrt", "ok", "Heartbeat current"),
                  ("internet", "Net", "ok", "5G / loss 0%"),
                  ("m5", "M5", "offline", "M5 offline/asleep"),
                  ("tailscale", "TS", "warning", "Routes not accepted")]
        self.records["health"]["items"] = [dict(key=key, label=label, status=status, detail=detail) for key, label, status, detail in checks]
        frame = d.render(self.config, self.records, "servers", self.now, 120, 37)
        full = "\n".join(frame)
        for label in ("i7 / Proxmox", "i5 / Proxmox", "HA / Flat", "HA / House", "OpenWrt", "Internet", "M5 MacBook", "Tailscale",
                      "TLS certificate expired", "go2rtc-flat stopped", "Routes not accepted", "[4 Servers]"):
            self.assertIn(label, full)
        self.assertNotIn("Printers", full)
        self.assertNotIn("To do", full)
        self.assertTrue(all(len(line) == 120 for line in frame))
        self.assertIn("M5 offline/asleep", full)

    def test_sleeping_m5_is_normal_but_unknown_checks_never_get_all_clear(self):
        self.records["health"]["items"] = [{"label": "HAflat", "status": "ok", "detail": "responding"},
                                          {"key": "m5", "label": "M5", "status": "offline", "detail": "asleep"}]
        self.assertIn("[+] healthy", health_summary(self.records["health"], self.now, 180))
        self.records["health"]["items"][0]["status"] = "unknown"
        self.assertIn("[?] partly unknown", health_summary(self.records["health"], self.now, 180))

    def test_reminder_names_and_remaining_count_keep_their_own_lines(self):
        self.records["reminders"]["lines"] = ["Overdue: Buy packing paper [To-Do]", "Overdue: Check and order a bike light [To-Do]", "+207 other incomplete reminders"]
        frame = d.render(self.config, self.records, "everyday", self.now, 120, 37)
        self.assertIn("Late: Buy packing paper", frame[2])
        self.assertIn("Late: Check and order a bike light", frame[3])
        self.assertIn("+207 other incomplete reminders", frame[4])

    def test_compact_guard_keeps_confidence_and_age_without_a_health_probability(self):
        item = self.records["printers"]["items"][0]
        lines = short_printer(item, 66)
        self.assertIn("[>]", lines[0])
        self.assertIn("72%", lines[1])
        self.assertIn("conf 80% / 2m ago", lines[2])
        self.assertTrue(all(len(line) <= 66 for line in lines))

    def test_existing_monitor_criteria_keep_stopped_required_guests_and_backup_failures(self):
        resources = [{"type": "node", "node": "host", "status": "online", "mem": 95, "maxmem": 100},
                     {"type": "lxc", "name": "optional camera", "status": "stopped", "tags": "optional"},
                     {"type": "lxc", "name": "go2rtc-flat", "status": "stopped"},
                     {"type": "storage", "storage": "ssd", "status": "available", "disk": 86, "maxdisk": 100}]
        tasks = [{"type": "vzdump", "endtime": self.now.timestamp() - 100, "status": "ERROR", "node": "host"}]
        problems = resource_problems(resources, tasks, self.now.timestamp())
        self.assertEqual(len(problems), 4)
        self.assertTrue(any("go2rtc-flat" in p for p in problems))
        self.assertFalse(any("optional camera" in p for p in problems))
        with self.assertRaises(ValueError):
            resource_problems([], [], self.now.timestamp())

    def test_six_printer_fleet_fits_above_the_clock(self):
        item = self.records["printers"]["items"][0]
        self.records["printers"]["items"] = [dict(item, name=f"Printer {i}") for i in range(1, 7)]
        frame = d.render(self.config, self.records, "fleet", self.now, 120, 37)
        before_clock = "\n".join(frame[:10])
        for i in range(1, 7):
            self.assertIn(f"Printer {i}", before_clock)

    def test_micro_seconds_and_colon_spans_fit_every_digit_and_view(self):
        for second in range(60):
            now = self.now.replace(second=second)
            self.assertEqual(len(seconds_art(now)), 5)
            self.assertTrue(all(len(line) == 7 for line in seconds_art(now)))
            for columns, rows in ((90, 35), (120, 37)):
                for view in self.config["views"]:
                    frame = d.render(self.config, self.records, view, now, columns, rows)
                    spans = clock_style_spans(self.config, self.records, view, now, columns, rows, d.CLOCK["FONT"])
                    for y, x, length, level in spans:
                        self.assertEqual(frame[y][x:x + length], "#" * length)
                        self.assertIn(level, ("ok", "warning", "fault", "unknown"))
                    self.assertTrue(all(len(line) == columns for line in frame))
                    if view == "night":
                        self.assertEqual(spans, [])
                    else:
                        self.assertEqual(len(spans), 8)

    def test_active_guard_unknown_and_suspected_failure_never_look_all_clear(self):
        item = self.records["printers"]["items"][0]
        for guard, expected in (("last AI: looks OK", "ok"), ("last AI: uncertain", "warning"),
                                ("last AI: suspected failure", "warning"), ("AI STALE: looks OK", "unknown"),
                                ("earlier-job AI: suspected failure", "unknown"), ("AI unavailable / 2m ago", "unknown")):
            candidate = dict(item, checks=["PG armed / " + guard, "Obico: safe / suspicion score 0.020"])
            self.assertEqual(printer_condition(candidate)[0], expected)
        for score in ("nan", "bad"):
            candidate = dict(item, checks=["PG armed / last AI: looks OK", "Obico: safe / suspicion score " + score])
            self.assertEqual(printer_condition(candidate)[0], "unknown")
        candidate = dict(item, checks=["PG armed / last AI: looks OK", "Obico: unsafe / suspicion score 0.800"])
        self.assertEqual(printer_condition(candidate)[0], "warning")

    def test_printer_failed_paused_offline_idle_and_stale_priorities(self):
        item = self.records["printers"]["items"][0]
        for changes, expected in (({"state": "FAILED"}, "fault"), ({"state": "PAUSED"}, "warning"),
                                  ({"connected": False}, "unknown"), ({"state": "IDLE", "checks": []}, "ok")):
            candidate = dict(item, **changes)
            self.assertEqual(printer_condition(candidate)[0], expected)
        record = dict(self.records["printers"], items=[dict(item, state="FAILED")])
        self.assertEqual(printer_status(record, self.now, 90), "fault")
        record["updated_at"] = (self.now - timedelta(minutes=5)).isoformat()
        self.assertEqual(printer_status(record, self.now, 90), "unknown")
        failed = short_printer(dict(item, state="FAILED"), 66, quiet=True)
        self.assertNotIn("72%", "\n".join(failed))
        self.assertNotIn("38m", "\n".join(failed))

    def test_service_colour_and_two_colon_dots_are_independent(self):
        self.records["printers"]["items"] = [dict(self.records["printers"]["items"][0], state="FAILED")]
        self.records["health"]["items"] = [{"key": "m5", "label": "M5", "status": "offline", "detail": "asleep"}]
        self.assertEqual(service_status(self.records["health"], self.now, 180), "ok")
        spans = clock_style_spans(self.config, self.records, "everyday", self.now, 120, 37, d.CLOCK["FONT"])
        self.assertTrue(all(level == "fault" for *_, level in spans[:4]))
        self.assertTrue(all(level == "ok" for *_, level in spans[4:]))
        self.records["health"]["items"] = [{"key": "ha_flat", "label": "HA", "status": "offline", "detail": "confirmed offline"}]
        self.assertEqual(service_status(self.records["health"], self.now, 180), "fault")
        self.assertIn("[x] fault", health_summary(self.records["health"], self.now, 180))
        self.assertNotIn("[+]", health_summary(self.records["health"], self.now, 180))
        self.records["health"]["items"][0]["status"] = "unknown"
        self.assertEqual(service_status(self.records["health"], self.now, 180), "unknown")

    def test_stale_labels_return_in_quiet_sections_and_claude_age_is_preserved(self):
        self.records["reminders"]["updated_at"] = (self.now - timedelta(hours=1)).isoformat()
        self.records["claude"]["lines"] = ["i7 / CT240: 1 live CLI session(s)", "code-eb: idle / reported 20m ago"]
        frame = d.render(self.config, self.records, "everyday", self.now, 120, 37)
        self.assertIn("To do", frame[2])
        self.assertIn("STALE", frame[2])
        self.assertIn("reported 20m ago", "\n".join(frame[:9]))

    def test_confirmed_service_failures_differ_from_missing_or_starting_status(self):
        for backend, expected in (("Running", "ok"), ("Stopped", "fault"), ("NeedsLogin", "fault"),
                                  ("Starting", "unknown"), (None, "unknown")):
            with patch("collect_health.subprocess.run") as run:
                run.return_value.stdout = json.dumps({"BackendState": backend, "Peer": {}})
                self.assertEqual(tailnet_checks("EXAMPLE")[0][0], expected)
        with patch("collect_health.get_json", side_effect=[{"data": [{"type": "node", "node": "host", "status": "offline"}]}, {"data": []}]):
            self.assertEqual(pve_check({"url": "https://example.invalid/cluster/resources", "auth": "EXAMPLE", "ca": "EXAMPLE"})[0], "fault")

    def test_help_explains_dot_colours_and_current_warning_causes(self):
        self.records["printers"]["items"][0]["state"] = "PAUSED"
        frame = d.render(self.config, self.records, "help", self.now, 120, 37)
        full = "\n".join(frame)
        for label in ("UPPER DOT / PRINTERS", "LOWER DOT / SERVICES", "AMBER / needs attention",
                      "Paused / inspect in Fleet", "go2rtc-flat stopped", "WHITE / OK",
                      "AMBER / ATTENTION", "RED / FAULT", "GREY / UNKNOWN", "[5 Help]",
                      "not the chance a print will succeed"):
            self.assertIn(label, full)
        self.assertTrue(all(len(line) == 120 for line in frame))

    def test_missing_stale_or_lossy_wan_results_do_not_get_a_tick(self):
        data = {"ts": datetime.now(timezone.utc).isoformat(), "preferred": "5G", "wan_state": "online", "loss_5g": 0}
        for changes, expected in (({}, "ok"), ({"preferred": None}, "unknown"), ({"loss_5g": None}, "unknown"), ({"loss_5g": 50}, "warning"), ({"ts": "2000-01-01T00:00:00"}, "unknown")):
            with patch("collect_health.get_json", return_value=dict(data, **changes)):
                self.assertEqual(internet_check("unused")[0], expected)


if __name__ == "__main__":
    unittest.main()
