# HashDash

Read README.md and docs/integrations.md before changes. This is a Python standard-library console dashboard.

- Keep the large hash-built clock, small hash seconds, quiet Everyday layout and matching clock geometry across views.
- The upper colon dot is printers; the lower is services. White OK, amber attention, red confirmed fault, grey unknown. Do not turn missing/stale data into an all-clear or AI suspicion into a confirmed failure.
- Keep detailed status and the colour key on Servers/Help, away from the main clock.
- Collectors and the renderer remain separate. No printer control, camera captures, new AI checks, reminder changes or email changes as part of displaying status.
- Never commit private configuration, live caches, real reminder/calendar/crew data, tokens, network addresses or live screenshots. Use the fictional demo for public images.
- Run `python3 -m unittest discover -s dashboard` and `python3 tools/render_preview.py` after relevant changes.
- Personal deployments may use additional private providers. Do not overwrite their configuration or collectors without inspecting and backing them up.

