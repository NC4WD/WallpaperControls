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

try:
    import gi
    from PIL import Image  # noqa: F401
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401
except (ImportError, ValueError) as error:
    sys.exit(
        f"Missing dependency: {error}\n"
        "On Ubuntu run: sudo apt install python3-gi python3-pil "
        "gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0"
    )

source = Path(os.environ["WALLPAPER_CONTROLS_SOURCE_DIR"])
home = Path.home()
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
for filename in ("wallpaper_controls.py", "monitor_wallpaper.py", "monitor_state.py", "LICENSE"):
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

def desktop_quote(path):
    escaped = str(path)
    for character in ('\\', '"', '$', '`'):
        escaped = escaped.replace(character, '\\' + character)
    return '"' + escaped + '"'

for filename in (f"{app_id}.desktop", f"{app_id}.SetWallpaper.desktop"):
    template = (source / f"{filename}.in").read_text(encoding="utf-8")
    (desktop_dir / filename).write_text(
        template.replace("@EXEC@", desktop_quote(launcher))
                .replace(f"Icon={app_id}\n", f"Icon={png_icon}\n"),
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
print("Wallpaper Controls installed. Open it from your app launcher.")
print("In Files, choose Open With → Set as Wallpaper, then press Apply.")
PY
