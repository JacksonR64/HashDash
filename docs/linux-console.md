# Optional Linux console setup

The demo needs no service installation. A dedicated console installation needs administrator access and hardware-specific review.

1. Back up the current console/font/service configuration.
2. Copy `console-clock.py` to `/usr/local/lib/console-clock/console-clock.py` and the runtime files from `dashboard/` to `/usr/local/lib/console-clock/dashboard/`.
3. Create private config/data directories at `/etc/console-dashboard/` and `/var/lib/console-clock/dashboard/`. Copy the layout and your private source configurations there. Config/data files containing personal information or credentials should be mode600; data directory mode700.
4. Review the supplied `.service` and `.timer` files before installation. The display example uses tty8 and the Debian Terminus12×24 console font at `/usr/share/consolefonts/Lat15-Terminus24x12.psf.gz`. Save the previous console font to `/usr/local/lib/console-clock/previous-console-font.psf` before starting it; the unit restores that font on stop. Do not change other consoles unnecessarily.
5. Install the reviewed units, reload systemd and enable only the display/collector timers you have configured. Keep the previous display available as recovery. The original setup uses a30-second host collector and60-second health collector; macOS feeds are independent.

The 12×24 font gives120×37 text cells on a1440×900 display. Other font/screen combinations vary; the renderer has a small-terminal fallback. The backlight helper only targets the documented Linux interface when present.

Stopping the dashboard returns to tty1 and restores the saved font. A restore of the previous source/layout plus a display-service restart is enough to undo a code change. Do not restart HA, printers, monitoring agents or network services to refresh this UI.

Some raw framebuffer captures on the original hardware omit unchanged pixels even while the physical display and text buffer are complete. Validate the physical display/text buffer; do not add recurring VT switching merely to improve screenshots.

