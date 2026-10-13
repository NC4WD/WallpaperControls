# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a login entry only while automatic display rebuilding is enabled."""

import os
from pathlib import Path
import sys

from monitor_state import uses_generated_wallpaper


APP_ID = "io.github.nc4wd.WallpaperControls"


def stop_running_app():
    """Stop an existing helper without starting a GTK process at uninstall."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call_sync(APP_ID, "/" + APP_ID.replace(".", "/"), "org.gtk.Actions", "Activate",
                      GLib.Variant("(sava{sv})", ("quit", [], {})), None,
                      Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    except (ImportError, ValueError):
        return
    except Exception:
        # No session bus or no running copy is a normal uninstall case.
        return


def _exec_quote(value):
    value = str(value).replace("%", "%%")
    for character in ('\\', '"', '$', '`'):
        value = value.replace(character, '\\' + character)
    return '"' + value + '"'


def sync_autostart(config, script=None):
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / "autostart" / f"{APP_ID}.desktop"
    enabled = config["auto_rebuild"] and uses_generated_wallpaper(config)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    if script is None:
        script = Path(__file__).resolve().with_name("wallpaper_controls.py")
    text = ("[Desktop Entry]\nType=Application\nName=Wallpaper Controls Display Helper\n"
            "Comment=Keep applied wallpapers aligned when displays change\n"
            f"Exec={_exec_quote(sys.executable)} {_exec_quote(script)} --watch-displays\n"
            "NoDisplay=true\nOnlyShowIn=GNOME;Unity;\nX-GNOME-Autostart-enabled=true\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".desktop.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
