#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu
exec /usr/bin/python3 - <<'PY'
import os
from pathlib import Path
import shutil
import subprocess
import sys

home = Path(os.environ.get("WALLPAPER_CONTROLS_INSTALL_HOME", Path.home()))
data = Path(os.environ.get("XDG_DATA_HOME", home / ".local/share"))
app_id = "io.github.nc4wd.WallpaperControls"
app = data / "wallpaper-controls"
if (app / "desktop_integration.py").is_file() and "WALLPAPER_CONTROLS_INSTALL_HOME" not in os.environ:
    sys.path.insert(0, str(app))
    from desktop_integration import stop_running_app
    stop_running_app(force=True)
desktop_dir = data / "applications"
paths = [
    home / ".local/bin/wallpaper-controls",
    desktop_dir / f"{app_id}.desktop",
    desktop_dir / f"{app_id}.SetWallpaper.desktop",
    data / "icons/hicolor/scalable/apps" / f"{app_id}.svg",
    data / "icons/hicolor/256x256/apps" / f"{app_id}.png",
    data / "metainfo" / f"{app_id}.metainfo.xml",
    Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "autostart" / f"{app_id}.desktop",
    *(app / filename for filename in (
        "wallpaper_controls.py", "monitor_wallpaper.py", "monitor_state.py",
        "wallpaper_backend.py", "desktop_integration.py", "runtime_requirements.py", "LICENSE")),
]
for path in paths:
    path.unlink(missing_ok=True)
if shutil.which("update-desktop-database") and desktop_dir.exists():
    subprocess.run(["update-desktop-database", str(desktop_dir)], check=True)
print("Wallpaper Controls removed. Wallpaper images and preferences were kept.")
PY
