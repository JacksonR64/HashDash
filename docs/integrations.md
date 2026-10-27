# Feeds and integration limits

## The smallest feed

Write one JSON file per module, outside the repository, then point `--data-dir` at that directory:

```json
{"updated_at":"2026-10-27T12:00:00+00:00","lines":["Example reminder","Another example"]}
```

Files must be at most64 KiB and use a timezone-aware timestamp. A failed refresh must not advance `updated_at`. `collect_host.write_module` supplies private atomic writes. The renderer accepts text only, removes terminal controls and isolates invalid files. Do not put credentials inside a display feed.

Modules are `shift`, `printers`, `agenda`, `claude`, `alarm`, `reminders`, `mail` and `health`. Their filenames/limits are in `dashboard/layout.json`. No source is required to run the clock. Layout slots remain configurable.

## Host adapters

- `collect_host.py`: GET requests to BamBuddy, using a **Read Status only** key. Optional PrintGuard inspection reads the existing service/log/state through LXC; it never runs a new model/camera check or sends a printer command. `HASHDASH_PRINTGUARD_CT` selects the guest (example default222). Missing guard coverage stays unknown.
- Claude metadata is an optional LXC/proc adapter. Set `HASHDASH_CLAUDE_CT` (example default240) and `HASHDASH_CLAUDE_SESSIONS` (guest-relative path, example `home/operator/.claude/sessions`). A live process is not proof that an agent is working; the original status-report age stays visible.
- `collect_health.py`: read-only Proxmox resources/tasks with PVEAuditor credentials and CA validation, HA manifest response, OpenWrt heartbeat/WAN JSON and Tailscale status. All sources are bounded by timeouts; no new speed test or device wake-up. HA response means HTTP responding, not that every integration is healthy. Backup checks scan recent failures, not proof of a recent successful backup. Sleeping laptop is normal.

Copy `examples/sources.example.json` and `examples/health-sources.example.json` to private config locations and replace placeholders. Use mode600. The example endpoints are intentionally invalid. Existing service units use `/etc/console-dashboard/` and `/var/lib/console-clock/dashboard/`.

## macOS reference adapter

`collect_macos.py` contains the integration boundary used by a private installation. It does not ship personal provider implementations or roster files. Configure:

| Variable | Meaning |
| --- | --- |
| `HASHDASH_PROVIDER_DIR` | Local provider directory; expects `tools/brain_calendar.py` with read-only `fetch_events()` / `fetch_reminders()` |
| `HASHDASH_ROTA_DIR` | Optional local rota adapter containing `publish.py`, `shifts_on()` / `crew_lists()`, and weekly files |
| `HASHDASH_PERSON` | Exact roster person identifier |
| `HASHDASH_VENUE` | Venue label for the display |
| `HASHDASH_HA_HOST` | Existing SSH alias for a read-only HA alarm query |
| `HASHDASH_DISPLAY_HOST` | Existing SSH alias for the display host |

`CalendarFeed.swift` is a native EventKit calendar reader. macOS Calendar/Reminders permissions and a locally signed helper must be configured by the operator. The Python provider can read that snapshot or provide events through its own approved adapter. Mail uses a bounded flagged-inbox count, without subjects or message bodies. Next shift is the next **known** shift; unavailable rota coverage is not a day off. Alarm display reports observed HA data and never sets an alarm.

Do not copy live calendar/reminder/crew output into the repository or use it for public screenshots. The renderer works with your own simpler JSON collectors if these deployment-specific adapters do not fit your setup.

