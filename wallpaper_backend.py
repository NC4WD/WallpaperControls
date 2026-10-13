# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply settings and preserve a durable, single-step undo operation."""

from pathlib import Path
from urllib.parse import unquote, urlparse

from monitor_state import (EDITABLE_KEYS, PICTURE_KEYS, clean_old_wallpapers,
                           cloned, ensure_monitor_images, generate_wallpapers,
                           load_config, retained_wallpapers, save_config,
                           uses_generated_wallpaper)
from monitor_wallpaper import layout_signature


def read_settings(settings):
    return {key: settings.get_string(key) for key in EDITABLE_KEYS}


def _commit(settings, values, config, sync):
    previous_values = read_settings(settings)
    previous_config = load_config(previous_values)
    changes = {key: values[key] for key in EDITABLE_KEYS
               if values[key] != previous_values[key]}
    for key in changes:
        if not settings.is_writable(key):
            raise ValueError(f"GNOME does not allow changes to {key}.")
    settings.delay()
    config_written = False
    try:
        for key, value in changes.items():
            if not settings.set_string(key, value):
                raise ValueError(f"Could not save {key}.")
        save_config(config)
        config_written = True
        settings.apply()
        if sync:
            sync()
    except Exception:
        settings.revert()
        if config_written:
            save_config(previous_config)
        raise
    actual = read_settings(settings)
    if actual != values:
        raise ValueError("GNOME did not save all wallpaper settings. Please try again.")
    try:
        clean_old_wallpapers(retained_wallpapers(actual, config))
    except OSError:
        pass
    return actual, config


def apply_wallpaper(settings, monitors, values, config, *, record_undo=True, sync=None):
    previous_values = read_settings(settings)
    previous_config = load_config(previous_values)
    next_values = values.copy()
    next_config = cloned(config)
    if uses_generated_wallpaper(next_config):
        render_config = cloned(next_config)
        if not render_config["enabled"]:
            render_config["images"] = {
                key: {monitor.connector: (next_config["single"][key] or
                                          next_config["single"]["picture-uri"])
                      for monitor in monitors} for key in PICTURE_KEYS}
            render_config["placement"] = next_config["single"]["picture-options"]
        generated, signature = generate_wallpapers(monitors, render_config,
                                                    next_values["primary-color"])
        next_values.update(generated)
        next_values["picture-options"] = "spanned"
        next_config["generated"] = generated
        next_config["layout"] = signature
    else:
        next_values.update(next_config["single"])
        next_config["layout"] = ""
        next_config["generated"] = {key: "" for key in PICTURE_KEYS}
    if record_undo:
        previous_config["undo"] = None
        next_config["undo"] = {"settings": previous_values, "config": previous_config,
                               "applied": next_values.copy()}
    elif next_config.get("undo"):
        next_config["undo"]["applied"] = next_values.copy()
    try:
        return _commit(settings, next_values, next_config, sync)
    except Exception:
        clean_old_wallpapers(retained_wallpapers(previous_values, load_config(previous_values)))
        raise


def undo_last_apply(settings, monitors, *, sync=None):
    current = read_settings(settings)
    config = load_config(current)
    undo = config.get("undo")
    if not undo:
        raise ValueError("There is no previous wallpaper to restore.")
    previous = cloned(undo["config"])
    previous["undo"] = None
    # Rebuild the old choices if the display layout changed since Apply.
    missing_generated = any(
        urlparse(undo["settings"][key]).scheme == "file" and
        not Path(unquote(urlparse(undo["settings"][key]).path)).is_file()
        for key in PICTURE_KEYS)
    if uses_generated_wallpaper(previous) and (
            previous["layout"] != layout_signature(monitors) or missing_generated):
        ensure_monitor_images(previous, monitors)
        return apply_wallpaper(settings, monitors, undo["settings"], previous,
                               record_undo=False, sync=sync)
    if missing_generated:
        raise ValueError("A previous wallpaper image was moved or deleted, so it cannot be restored.")
    return _commit(settings, undo["settings"], previous, sync)


def rebuild_for_layout(settings, monitors, *, sync=None):
    current = read_settings(settings)
    config = load_config(current)
    if (not monitors or not config["auto_rebuild"] or not uses_generated_wallpaper(config)
            or config["layout"] == layout_signature(monitors)):
        return None
    ensure_monitor_images(config, monitors)
    return apply_wallpaper(settings, monitors, current, config,
                           record_undo=False, sync=sync)
