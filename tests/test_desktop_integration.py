# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from desktop_integration import desktop_exec_quote, stop_running_app


def test_desktop_launcher_runs_literal_paths_with_special_characters(tmp_path):
    gi = pytest.importorskip("gi")
    from gi.repository import Gio
    script = tmp_path / 'space % slash\\ quote" dollar$ backtick`.py'
    output = tmp_path / "argv.json"
    script.write_text("import json,sys\nfrom pathlib import Path\n"
                      "Path(sys.argv[1]).write_text(json.dumps(sys.argv))\n")
    path = tmp_path / "test.desktop"
    path.write_text("[Desktop Entry]\nType=Application\nName=Test\nTerminal=false\n"
                    f"Exec={desktop_exec_quote(sys.executable)} {desktop_exec_quote(script)} "
                    f"{desktop_exec_quote(output)}\n")
    app = Gio.DesktopAppInfo.new_from_filename(str(path))
    assert app is not None
    assert app.launch([], None)
    deadline = time.monotonic() + 3
    while not output.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert output.is_file()
    assert json.loads(output.read_text()) == [str(script), str(output)]


@pytest.mark.parametrize("force", [False, True])
def test_running_helper_stops_through_its_application_action(tmp_path, force):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk
    Gtk.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("Helper lifecycle check requires a display.")
    app_id = f"io.github.nc4wd.WallpaperControls.HelperTest{uuid4().hex}"
    ready = tmp_path / "ready"
    script = tmp_path / "helper.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "sys.path.insert(0,sys.argv[1])\n"
        "import wallpaper_controls as wc\nfrom gi.repository import GLib\n"
        "wc.APP_ID=sys.argv[2]\napp=wc.WallpaperApp()\n"
        "ready=Path(sys.argv[3])\n"
        "def started(app):\n"
        "    app.hold()\n"
        "    GLib.idle_add(lambda: (ready.write_text('ready'),False)[1])\n"
        "app.connect('startup',started)\n"
        "raise SystemExit(app.run(['helper','--watch-displays']))\n")
    env = {**os.environ, "GSETTINGS_BACKEND": "memory",
           "XDG_CONFIG_HOME": str(tmp_path / "config"),
           "XDG_DATA_HOME": str(tmp_path / "data")}
    process = subprocess.Popen([sys.executable, str(script), str(Path(__file__).resolve().parents[1]),
                                app_id, str(ready)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.is_file(), "The isolated helper must start before testing its shutdown."
        stop_running_app(application_id=app_id, force=force)
        assert process.wait(timeout=3) == 0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=3)
