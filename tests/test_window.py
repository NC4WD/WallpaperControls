# SPDX-License-Identifier: GPL-3.0-or-later
"""GTK integration checks; use a disposable settings backend and user folders."""
from uuid import uuid4

import pytest
from PIL import Image

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk

import wallpaper_controls as wc
from monitor_state import load_config
from monitor_wallpaper import MonitorSpec, layout_signature
from wallpaper_backend import rebuild_for_layout


def drain_events():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


@pytest.fixture
def window(tmp_path, monkeypatch):
    Gtk.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("GTK integration requires a display (or xvfb-run).")
    monkeypatch.setenv("GSETTINGS_BACKEND", "memory")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(wc, "APP_ID", f"io.github.nc4wd.WallpaperControls.Test{uuid4().hex}")
    source = tmp_path / "source.png"
    image = Image.new("RGB", (40, 20), "red")
    image.paste("blue", (20, 0, 40, 20))
    image.save(source)
    settings = Gio.Settings.new(wc.BACKGROUND_SCHEMA)
    settings.delay()
    values = {"picture-uri": source.as_uri(), "picture-uri-dark": source.as_uri(),
              "picture-options": "zoom", "primary-color": "#000000",
              "secondary-color": "#000000", "color-shading-type": "solid"}
    for key, value in values.items():
        settings.set_string(key, value)
    settings.apply()
    app = wc.WallpaperApp()
    app.register(None)
    window = wc.WallpaperWindow(app)
    window.set_title("Wallpaper Controls — Verification")
    window.monitor_specs = [MonitorSpec("one", "One", 0, 0, 10, 20)]
    window.rebuild_monitor_rows()
    window.render_draft()
    window.present()
    drain_events()
    yield window
    window.close_identification()
    window.destroy()
    app.do_shutdown()
    drain_events()


def test_drop_alignment_apply_and_undo_use_real_gtk(window, tmp_path):
    original = window.read_settings()
    dropped = tmp_path / "dropped.png"
    source = Image.new("RGB", (40, 20), "red")
    source.paste("blue", (20, 0, 40, 20))
    source.save(dropped)
    file_list = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(dropped))])
    target = window.add_drop_target(window.preview, window.on_preview_drop)
    assert target.emit("drop", file_list, 50.0, 50.0)
    assert window.draft[window.selected_key] == dropped.as_uri()
    assert window.read_settings() == original, "Drops must remain staged until Apply."
    window.alignment_dropdown.set_selected(4)  # Right
    assert window.config_draft["alignment"] == "right"
    assert window.apply_button.get_sensitive()
    window.on_apply(None)
    assert not window.error_message
    assert not window.has_changes()
    assert window.undo_action.get_enabled()
    assert load_config(window.read_settings())["alignment"] == "right"
    window.on_undo(None)
    assert not window.error_message
    assert window.read_settings() == original
    assert not window.undo_action.get_enabled()


def test_invalid_and_multiple_file_drops_leave_selection_unchanged(window, tmp_path):
    original = window.draft.copy()
    text = tmp_path / "text.txt"
    text.write_text("This is not an image.")
    assert not window.drop_file(Gio.File.new_for_path(str(text)))
    assert window.draft == original
    assert "image" in window.error_message
    files = Gdk.FileList.new_from_list([Gio.File.new_for_path(str(text))] * 2)
    assert not window.drop_file(files)
    assert "one image" in window.error_message
    assert not window.drop_file(Gio.File.new_for_uri("https://example.com/wallpaper.png"))
    assert window.draft == original


def test_display_rebuild_preserves_pending_image_and_color(window, tmp_path):
    window.monitor_switch.set_active(True)
    window.on_apply(None)
    assert not window.error_message
    pending = tmp_path / "pending.png"
    Image.new("RGB", (40, 20), "green").save(pending)
    assert window.stage_file(Gio.File.new_for_path(str(pending)), window.selected_key, "one")
    window.draft["primary-color"] = "#ffffff"
    window.monitor_specs = [MonitorSpec("one", "One", 0, 0, 20, 20)]
    window.layout_dirty = True
    window.get_application().updating_wallpaper = True
    result = rebuild_for_layout(window.settings, window.monitor_specs)
    window.accept_applied_state(*result)
    window.get_application().updating_wallpaper = False
    assert window.config_draft["images"][window.selected_key]["one"] == pending.as_uri()
    assert window.draft["primary-color"] == "#ffffff"
    assert window.saved["primary-color"] == "#000000"
    assert window.has_changes()
    window.on_revert(None)
    assert not window.has_changes()
    assert window.config_draft["images"][window.selected_key]["one"] != pending.as_uri()


def test_monitor_drop_targets_the_correct_display_and_identification_closes(window, tmp_path):
    window.monitor_specs.append(MonitorSpec("two", "Two", 10, 0, 10, 20))
    window.rebuild_monitor_rows()
    window.monitor_switch.set_active(True)
    dropped = tmp_path / "second-display.png"
    Image.new("RGB", (10, 20), "green").save(dropped)
    file = Gio.File.new_for_path(str(dropped))
    assert window.on_monitor_row_drop(None, file, 0, 0, "two")
    assert window.config_draft["images"][window.selected_key]["two"] == dropped.as_uri()
    assert window.config_draft["images"][window.selected_key]["one"] != dropped.as_uri()
    window.on_identify()
    assert len(window._identify_windows) == window.monitor_model.get_n_items()
    window.close_identification()
    assert window._identify_windows == []
    assert window._identify_timeout == 0


def test_application_coalesces_display_events_and_runs_after_window_closes(window, monkeypatch):
    original = window.read_settings()
    window.monitor_switch.set_active(True)
    window.on_apply(None)
    app = window.get_application()
    assert app.background_held
    changed = [MonitorSpec("one", "One", 0, 0, 20, 20),
               MonitorSpec("two", "Two", 20, 0, 20, 20)]
    monkeypatch.setattr(wc, "monitors_from_display", lambda _display: changed)
    app.on_display_event()
    app.on_display_event()
    loop = GLib.MainLoop()
    GLib.timeout_add(1500, lambda: (loop.quit(), GLib.SOURCE_REMOVE)[1])
    loop.run()
    assert app._layout_timeout == 0
    assert window.config_saved["layout"] == layout_signature(changed)
    assert not window.has_changes()
    assert window.config_saved["undo"]["settings"] == original
    window.destroy()
    assert app.main_window() is None
    changed[1] = MonitorSpec("two", "Two", 20, 0, 30, 20)
    app.rebuild_applied_layout()
    current = {key: app.desktop_settings.get_string(key) for key in wc.EDITABLE_KEYS}
    assert load_config(current)["layout"] == layout_signature(changed)
