# SPDX-License-Identifier: GPL-3.0-or-later
"""Apply settings and preserve a durable, single-step undo operation."""

from pathlib import Path
from urllib.parse import unquote, urlparse

from monitor_state import (EDITABLE_KEYS, PICTURE_KEYS, clean_old_wallpapers,
                           cloned, config_path, ensure_monitor_images, generate_wallpapers,
                           load_config, retained_wallpapers, save_config, single_image_uri,
                           uses_generated_wallpaper, write_config_bytes)
from monitor_wallpaper import layout_signature

SETTING_NAMES = {
    "picture-uri": "the light mode wallpaper",
    "picture-uri-dark": "the dark mode wallpaper",
    "picture-options": "image sizing",
    "primary-color": "the background color",
    "secondary-color": "the background color",
    "color-shading-type": "the background color style",
}


class WallpaperSaveError(ValueError):
    """Keep generated images if a failed settings rollback cannot be verified."""


def read_settings(settings):
    return {key: settings.get_string(key) for key in EDITABLE_KEYS}


def _commit(settings, values, config, sync):
    previous_values = read_settings(settings)
    try:
        previous_contents = config_path().read_bytes()
    except FileNotFoundError:
        previous_contents = None
    changes = {key: values[key] for key in EDITABLE_KEYS
               if values[key] != previous_values[key]}
    for key in changes:
        if not settings.is_writable(key):
            raise ValueError(f"Your system doesn't allow changes to {SETTING_NAMES[key]}.")
    settings.delay()
    config_written = False
    try:
        for key, value in changes.items():
            if not settings.set_string(key, value):
                raise ValueError(f"Couldn't save {SETTING_NAMES[key]}. Please try again.")
        save_config(config)
        config_written = True
        settings.apply()
        if sync:
            sync()
        actual = read_settings(settings)
        if actual != values:
            raise ValueError("Your wallpaper settings weren't saved completely. Please try again.")
    except Exception as error:
        settings.revert()
        try:
            # revert() only discards pending writes. Once Apply has happened,
            # explicitly restore values that reached the settings backend.
            restore = {key: value for key, value in previous_values.items()
                       if settings.get_string(key) != value}
            if restore:
                settings.delay()
                for key, value in restore.items():
                    if not settings.is_writable(key) or not settings.set_string(key, value):
                        raise ValueError("The previous wallpaper couldn't be restored.")
                settings.apply()
                if sync:
                    sync()
            if read_settings(settings) != previous_values:
                raise ValueError("The previous wallpaper couldn't be restored.")
            if config_written:
                write_config_bytes(previous_contents)
        except Exception as rollback_error:
            settings.revert()
            raise WallpaperSaveError(
                "The wallpaper change failed and couldn't be fully undone. "
                "Your image files were kept. Reopen the app and check your wallpaper.") from rollback_error
        raise error
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
                key: {monitor.connector: single_image_uri(next_config, key)
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
    except WallpaperSaveError:
        # The desktop may still reference either set of files. Preserve both.
        raise
    except Exception:
        try:
            actual = read_settings(settings)
            keep = retained_wallpapers(actual, load_config(actual))
            keep.extend(retained_wallpapers(previous_values, previous_config))
            clean_old_wallpapers(keep)
        except OSError:
            pass
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
    missing_generated = undo["settings"]["picture-options"] != "none" and any(
        urlparse(undo["settings"][key]).scheme == "file" and
        not Path(unquote(urlparse(undo["settings"][key]).path)).is_file()
        for key in PICTURE_KEYS)
    if uses_generated_wallpaper(previous) and (
            previous["layout"] != layout_signature(monitors) or missing_generated):
        ensure_monitor_images(previous, monitors)
        return apply_wallpaper(settings, monitors, undo["settings"], previous,
                               record_undo=False, sync=sync)
    if missing_generated:
        raise ValueError("Your previous image was moved or deleted. Choose it again to restore it.")
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
