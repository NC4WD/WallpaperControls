# SPDX-License-Identifier: GPL-3.0-or-later
"""Install a login entry only while automatic display rebuilding is enabled."""

import os
from pathlib import Path
import sys


APP_ID = "io.github.nc4wd.WallpaperControls"


def stop_running_app(*, force=False, application_id=APP_ID):
    """Stop an existing helper without starting a GTK process at uninstall."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        path = "/" + application_id.replace(".", "/")
        actions = bus.call_sync(application_id, path, "org.gtk.Actions", "DescribeAll",
                                None, None, Gio.DBusCallFlags.NO_AUTO_START, 1000, None).unpack()[0]
        action = "force-quit" if force and "force-quit" in actions else "quit"
        if action in actions:
            bus.call_sync(application_id, path, "org.gtk.Actions", "Activate",
                          GLib.Variant("(sava{sv})", (action, [], {})), None,
                          Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    except (ImportError, ValueError):
        return
    except Exception:
        # No session bus or no running copy is a normal uninstall case.
        return


def desktop_exec_quote(value):
    """Escape both the Exec argument quoting and desktop-file string layers."""
    value = str(value).replace("%", "%%")
    for character in ('\\', '"', '$', '`'):
        value = value.replace(character, '\\' + character)
    value = desktop_string_escape(value)
    return '"' + value + '"'


def desktop_string_escape(value):
    return (str(value).replace('\\', '\\\\').replace('\n', '\\n')
            .replace('\r', '\\r').replace('\t', '\\t'))


def sync_autostart(config, script=None):
    from monitor_state import uses_generated_wallpaper
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = root / "autostart" / f"{APP_ID}.desktop"
    enabled = config["auto_rebuild"] and uses_generated_wallpaper(config)
    if not enabled:
        path.unlink(missing_ok=True)
        return
    if script is None:
        script = Path(__file__).resolve().with_name("wallpaper_controls.py")
    text = ("[Desktop Entry]\nType=Application\nName=Wallpaper-Controls Display Helper\n"
            "Comment=Keep applied wallpapers aligned when displays change\n"
            f"TryExec={desktop_string_escape(script)}\n"
            f"Exec={desktop_exec_quote(sys.executable)} {desktop_exec_quote(script)} --watch-displays\n"
            "NoDisplay=true\nOnlyShowIn=GNOME;Unity;\nX-GNOME-Autostart-enabled=true\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".desktop.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
