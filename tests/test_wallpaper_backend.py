# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest
from PIL import Image

from desktop_integration import sync_autostart
from monitor_state import (config_path, default_config, generated_dir, load_config,
                           merge_pending, save_config)
from monitor_wallpaper import MonitorSpec
from wallpaper_backend import apply_wallpaper, rebuild_for_layout, undo_last_apply


class Settings:
    """A transactional settings store with injectable failed/locked writes."""
    def __init__(self, values):
        self.values = values.copy()
        self.pending = None
        self.locked = self.failed = None

    def get_string(self, key):
        return (self.pending if self.pending is not None else self.values)[key]

    def is_writable(self, key):
        return key != self.locked

    def delay(self):
        self.pending = self.values.copy()

    def set_string(self, key, value):
        if key == self.failed:
            return False
        self.pending[key] = value
        return True

    def apply(self):
        self.values = self.pending
        self.pending = None

    def revert(self):
        self.pending = None


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    source = tmp_path / "original.png"
    Image.new("RGB", (40, 20), "red").save(source)
    values = {"picture-uri": source.as_uri(), "picture-uri-dark": source.as_uri(),
              "picture-options": "zoom", "primary-color": "#000000",
              "secondary-color": "#000000", "color-shading-type": "solid"}
    return Settings(values), [MonitorSpec("one", "One", 0, 0, 40, 20)], values


def path_from_uri(uri):
    return Path(unquote(urlparse(uri).path))


def test_undo_retains_old_generated_files_and_restores_color_and_choices(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.06
    first, first_config = apply_wallpaper(settings, monitors, original, config)
    first_path = path_from_uri(first["picture-uri"])
    second_config = load_config(settings.values)
    second_config["alignment"] = "right"
    second_config["single"]["picture-options"] = "centered"
    second_values = {**first, "primary-color": "#0000ff", "secondary-color": "#0000ff"}
    second, _ = apply_wallpaper(settings, monitors, second_values, second_config)
    assert first_path.is_file(), "Cleanup must retain the previous desktop for Undo."
    assert load_config(settings.values)["undo"]["settings"] == first
    restored, restored_config = undo_last_apply(settings, monitors)
    assert restored == first
    assert restored_config["single"] == first_config["single"]
    assert restored_config["alignment"] == "center"
    assert restored_config["undo"] is None
    assert not path_from_uri(second["picture-uri"]).exists()
    assert first_path.is_file()


def test_rebuild_reuses_saved_images_and_does_not_replace_undo(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["enabled"] = True
    config["images"] = {key: {"one": original[key]} for key in ("picture-uri", "picture-uri-dark")}
    apply_wallpaper(settings, monitors, original, config)
    changed = [MonitorSpec("one", "One", -40, 0, 40, 20),
               MonitorSpec("two", "Two", 0, 0, 30, 20)]
    values, rebuilt = rebuild_for_layout(settings, changed)
    with Image.open(path_from_uri(values["picture-uri"])) as image:
        assert image.size == (70, 20)
    assert rebuilt["images"]["picture-uri"]["two"] == original["picture-uri"]
    assert rebuilt["undo"]["settings"] == original
    assert load_config(values)["undo"] is not None
    restored, _ = undo_last_apply(settings, changed)
    assert restored == original


def test_undo_rebuilds_previous_generated_choices_after_layout_change(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.03
    apply_wallpaper(settings, monitors, original, config)
    config = load_config(settings.values)
    config["border"] = 0.1
    apply_wallpaper(settings, monitors, settings.values, config)
    changed = [MonitorSpec("one", "One", 0, 0, 30, 20)]
    rebuild_for_layout(settings, changed)
    values, restored = undo_last_apply(settings, changed)
    assert restored["border"] == 0.03
    with Image.open(path_from_uri(values["picture-uri"])) as image:
        assert image.size == (30, 20)


@pytest.mark.parametrize("failure", ["locked", "failed"])
def test_failed_apply_keeps_desktop_and_undo_unchanged(desktop, failure):
    settings, monitors, original = desktop
    config = default_config(original)
    save_config(config)
    config["alignment"] = "top"
    setattr(settings, failure, "picture-uri-dark")
    with pytest.raises(ValueError):
        apply_wallpaper(settings, monitors, original, config)
    assert settings.values == original
    assert load_config(original)["undo"] is None
    assert not list(generated_dir().glob("*.png"))


def test_second_image_failure_removes_incomplete_generation(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.06
    config["single"]["picture-uri-dark"] = Path("/missing/wallpaper.png").as_uri()
    with pytest.raises(ValueError, match="Couldn't open"):
        apply_wallpaper(settings, monitors, original, config)
    assert settings.values == original
    assert not list(generated_dir().glob("*.png"))


def test_external_wallpaper_change_and_disabled_helper_prevent_rebuild(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.06
    apply_wallpaper(settings, monitors, original, config)
    settings.values["picture-uri"] = original["picture-uri"]
    changed = [MonitorSpec("one", "One", 0, 0, 30, 20)]
    assert rebuild_for_layout(settings, changed) is None
    config = default_config(original)
    config["border"] = 0.06
    config["auto_rebuild"] = False
    apply_wallpaper(settings, monitors, original, config)
    assert rebuild_for_layout(settings, changed) is None


def test_unplugged_monitor_choices_are_retained(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["enabled"] = True
    config["images"] = {key: {"one": original[key], "unplugged": original[key]}
                        for key in ("picture-uri", "picture-uri-dark")}
    apply_wallpaper(settings, monitors, original, config)
    _, rebuilt = rebuild_for_layout(settings, [MonitorSpec("one", "One", 0, 0, 30, 20)])
    assert "unplugged" in rebuilt["images"]["picture-uri"]


def test_pending_edits_survive_rebuild_and_external_settings_refresh():
    previous = {"single": {"picture-uri": "old", "picture-uri-dark": "dark"},
                "border": 0.03, "generated": {"picture-uri": "old-generated"}}
    draft = {"single": {"picture-uri": "pending", "picture-uri-dark": "dark"},
             "border": 0.03, "generated": {"picture-uri": "old-generated"}}
    latest = {"single": {"picture-uri": "external", "picture-uri-dark": "new-dark"},
              "border": 0.03, "generated": {"picture-uri": "rebuilt"}}
    merged = merge_pending(previous, draft, latest)
    assert merged["single"] == {"picture-uri": "pending", "picture-uri-dark": "new-dark"}
    assert merged["generated"]["picture-uri"] == "rebuilt"


def test_helper_login_entry_exists_only_while_enabled(desktop, tmp_path):
    _, _, values = desktop
    config = default_config(values)
    config["border"] = 0.06
    script = tmp_path / "space and % quote\".py"
    sync_autostart(config, script=script)
    entry = tmp_path / "config/autostart/io.github.nc4wd.WallpaperControls.desktop"
    assert "--watch-displays" in entry.read_text()
    assert "%%" in entry.read_text()
    config["auto_rebuild"] = False
    sync_autostart(config, script=script)
    assert not entry.exists()


def test_single_image_alignment_works_on_mirrored_displays(desktop):
    settings, monitors, original = desktop
    monitors.append(MonitorSpec("mirror", "Mirror", 0, 0, 40, 20))
    config = default_config(original)
    config["alignment"] = "top"
    values, _ = apply_wallpaper(settings, monitors, original, config)
    with Image.open(path_from_uri(values["picture-uri"])) as image:
        assert image.size == (40, 20)


def test_undo_rebuilds_a_missing_generated_file(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.03
    first, _ = apply_wallpaper(settings, monitors, original, config)
    config = load_config(first)
    config["border"] = 0.06
    apply_wallpaper(settings, monitors, settings.values, config)
    path_from_uri(first["picture-uri"]).unlink()
    values, restored = undo_last_apply(settings, monitors)
    assert restored["border"] == 0.03
    assert path_from_uri(values["picture-uri"]).is_file()


@pytest.mark.parametrize("failure", ["sync", "partial"])
def test_failure_after_apply_rolls_back_settings_config_and_files(desktop, failure, monkeypatch):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.03
    first, _ = apply_wallpaper(settings, monitors, original, config)
    saved_json = config_path().read_bytes()
    config = load_config(first)
    config["border"] = 0.1
    sync = None
    if failure == "sync":
        attempts = []
        def sync():
            attempts.append(True)
            if len(attempts) == 1:
                raise OSError("Simulated storage failure after Apply")
    else:
        original_apply = settings.apply
        attempts = []
        def partial_apply():
            old_dark = settings.values["picture-uri-dark"]
            original_apply()
            if not attempts:
                settings.values["picture-uri-dark"] = old_dark
                attempts.append(True)
        monkeypatch.setattr(settings, "apply", partial_apply)
    with pytest.raises((OSError, ValueError)):
        apply_wallpaper(settings, monitors, first, config, sync=sync)
    assert settings.values == first, "An unsuccessful Apply must restore the previous desktop."
    assert config_path().read_bytes() == saved_json
    assert all(path_from_uri(settings.values[key]).is_file()
               for key in ("picture-uri", "picture-uri-dark"))


def test_corrupt_undo_snapshot_is_ignored(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.03
    apply_wallpaper(settings, monitors, original, config)
    config = load_config(settings.values)
    config["undo"]["config"].pop("generated")
    save_config(config)
    assert load_config(settings.values)["undo"] is None


def test_failed_rollback_preserves_all_generated_files(desktop):
    settings, monitors, original = desktop
    config = default_config(original)
    config["border"] = 0.03
    first, _ = apply_wallpaper(settings, monitors, original, config)
    old_paths = list(generated_dir().glob("*.png"))
    config = load_config(first)
    config["border"] = 0.1
    def failed_sync():
        raise OSError("Persistent storage failure")
    with pytest.raises(ValueError, match="image files were kept"):
        apply_wallpaper(settings, monitors, first, config, sync=failed_sync)
    assert all(path.is_file() for path in old_paths)
    assert len(list(generated_dir().glob("*.png"))) == 4


@pytest.mark.parametrize("payload", [
    '{"version":1,"border":' + str(10 ** 400) + '}',
    '{"version":1,"alignment":[]}',
    '{"version":1,"images":{"picture-uri":{"one":42}}}',
    '[' * 2000 + 'null' + ']' * 2000,
])
def test_malformed_preferences_do_not_crash_or_replace_sources(desktop, payload):
    _, _, original = desktop
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text(payload)
    config = load_config(original)
    assert not config["enabled"]
    assert config["single"]["picture-uri"] == original["picture-uri"]


def test_undo_color_only_does_not_require_the_unused_old_image(desktop, tmp_path):
    settings, monitors, original = desktop
    settings.values["picture-options"] = "none"
    next_image = tmp_path / "next.png"
    Image.new("RGB", (20, 10), "blue").save(next_image)
    config = default_config(settings.values)
    config["single"].update({"picture-options": "zoom", "picture-uri": next_image.as_uri(),
                             "picture-uri-dark": next_image.as_uri()})
    config["border"] = 0.03
    apply_wallpaper(settings, monitors, settings.values, config)
    path_from_uri(original["picture-uri"]).unlink()
    restored, _ = undo_last_apply(settings, monitors)
    assert restored["picture-options"] == "none"
