#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu
export WALLPAPER_CONTROLS_SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 - <<'PY'
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

source = Path(os.environ["WALLPAPER_CONTROLS_SOURCE_DIR"])
sys.path.insert(0, str(source))
from runtime_requirements import check_schemas, check_versions
from desktop_integration import desktop_exec_quote, desktop_string_escape

try:
    import gi
    from PIL import Image  # noqa: F401
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_foreign("cairo")
    from gi.repository import Adw, Gio, Gtk
    check_versions((Gtk.get_major_version(), Gtk.get_minor_version()),
                   (Adw.get_major_version(), Adw.get_minor_version()))
    check_schemas(Gio.SettingsSchemaSource.get_default())
except (ImportError, ValueError) as error:
    sys.exit(
        f"Missing dependency: {error}\n"
        "On Ubuntu 24.04 or newer run: sudo apt install python3-gi python3-gi-cairo python3-pil "
        "gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 gsettings-desktop-schemas "
        "librsvg2-common webp-pixbuf-loader"
    )

home = Path(os.environ.get("WALLPAPER_CONTROLS_INSTALL_HOME", Path.home()))
data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
app = data / "wallpaper-controls"
bin_dir = home / ".local/bin"
desktop_dir = data / "applications"
icon_dir = data / "icons/hicolor/scalable/apps"
png_icon_dir = data / "icons/hicolor/256x256/apps"
metainfo_dir = data / "metainfo"
for directory in (app, bin_dir, desktop_dir, icon_dir, png_icon_dir, metainfo_dir):
    directory.mkdir(parents=True, exist_ok=True)

app_id = "io.github.nc4wd.WallpaperControls"
for filename in ("wallpaper_controls.py", "monitor_wallpaper.py", "monitor_state.py",
                 "wallpaper_backend.py", "desktop_integration.py", "runtime_requirements.py", "LICENSE"):
    shutil.copy2(source / filename, app / filename)
shutil.copy2(source / f"{app_id}.svg", icon_dir / f"{app_id}.svg")
png_icon = png_icon_dir / f"{app_id}.png"
shutil.copy2(source / f"{app_id}.png", png_icon)
shutil.copy2(source / f"{app_id}.metainfo.xml", metainfo_dir / f"{app_id}.metainfo.xml")

launcher = bin_dir / "wallpaper-controls"
launcher.write_text(
    "#!/bin/sh\nexec /usr/bin/python3 "
    + shlex.quote(str(app / "wallpaper_controls.py")) + ' "$@"\n',
    encoding="utf-8",
)
launcher.chmod(0o755)

for filename in (f"{app_id}.desktop", f"{app_id}.SetWallpaper.desktop"):
    template = (source / f"{filename}.in").read_text(encoding="utf-8")
    (desktop_dir / filename).write_text(
        template.replace("@EXEC@", desktop_exec_quote(launcher))
                .replace(f"Icon={app_id}\n", f"Icon={desktop_string_escape(png_icon)}\n"),
        encoding="utf-8")

# Remove launcher entries from the pre-release application ID.
for path in (
    desktop_dir / "org.wallpapercontrols.WallpaperControls.desktop",
    desktop_dir / "org.wallpapercontrols.SetWallpaper.desktop",
    icon_dir / "org.wallpapercontrols.WallpaperControls.svg",
):
    path.unlink(missing_ok=True)

if shutil.which("update-desktop-database"):
    subprocess.run(["update-desktop-database", str(desktop_dir)], check=True)
print("Wallpaper-Controls installed. Open it from your app launcher.")
print("In Files, choose Open With → Set as Wallpaper, then press Apply.")
print("If the app is already running, choose Quit from its menu, then reopen it to load the update.")
sys.path.insert(0, str(app))
from desktop_integration import sync_autostart
from monitor_state import EDITABLE_KEYS, load_config
from gi.repository import Gio
settings = Gio.Settings.new("org.gnome.desktop.background")
sync_autostart(load_config({key: settings.get_string(key) for key in EDITABLE_KEYS}),
               script=app / "wallpaper_controls.py")
PY
