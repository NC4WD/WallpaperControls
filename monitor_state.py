# SPDX-License-Identifier: GPL-3.0-or-later
"""Persist source images and generated GNOME wallpapers for each monitor."""

import copy
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlparse
from uuid import uuid4

from monitor_wallpaper import ALIGNMENTS, layout_signature, render_composite


PICTURE_KEYS = ("picture-uri", "picture-uri-dark")
EDITABLE_KEYS = (*PICTURE_KEYS, "picture-options", "primary-color",
                 "secondary-color", "color-shading-type")


def uses_generated_wallpaper(config):
    return (config["enabled"] or config.get("border", 0.0) > 0 or
            config.get("alignment", "center") != "center")


def editable_settings(settings_values, config):
    values = settings_values.copy()
    if not config["enabled"]:
        values.update(config["single"])
    return values


def merge_pending(previous, draft, latest):
    """Refresh untouched preferences while retaining the user's pending edits."""
    if draft == previous:
        return cloned(latest)
    if all(isinstance(value, dict) for value in (previous, draft, latest)):
        merged = cloned(latest)
        for key, value in draft.items():
            if key not in previous:
                merged[key] = cloned(value)
            else:
                merged[key] = merge_pending(previous[key], value, latest.get(key))
        return merged
    return cloned(draft)


def ensure_monitor_images(config, monitors):
    """Seed newly connected displays, retaining choices for unplugged ones."""
    for key in PICTURE_KEYS:
        images = config["images"][key]
        fallback = (config["single"][key] or next((v for v in images.values() if v), "") or
                    config["single"][PICTURE_KEYS[0]])
        for monitor in monitors:
            if not images.get(monitor.connector):
                images[monitor.connector] = fallback


def config_path():
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "wallpaper-controls" / "monitors.json"


def generated_dir():
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "wallpaper-controls" / "generated"


def default_config(settings_values):
    return {
        "version": 1,
        "enabled": False,
        "single": {key: settings_values[key] for key in (*PICTURE_KEYS, "picture-options")},
        "images": {key: {} for key in PICTURE_KEYS},
        "placement": "zoom",
        "border": 0.0,
        "alignment": "center",
        "auto_rebuild": True,
        "undo": None,
        "generated": {key: "" for key in PICTURE_KEYS},
        "layout": "",
    }


def valid_snapshot_config(config):
    if not isinstance(config, dict):
        return False
    single, images = config.get("single"), config.get("images")
    border = config.get("border")
    return (config.get("version") == 1 and isinstance(config.get("enabled"), bool) and
            isinstance(config.get("auto_rebuild"), bool) and
            config.get("alignment") in ALIGNMENTS and
            config.get("placement") in ("zoom", "scaled", "stretched", "centered", "wallpaper") and
            isinstance(border, (int, float)) and math.isfinite(border) and 0 <= border <= 0.25 and
            isinstance(config.get("layout"), str) and isinstance(single, dict) and
            all(isinstance(single.get(key), str) for key in (*PICTURE_KEYS, "picture-options")) and
            isinstance(images, dict) and all(isinstance(images.get(key), dict) and
                all(isinstance(k, str) and isinstance(v, str) for k, v in images[key].items())
                for key in PICTURE_KEYS))


def load_config(settings_values):
    config = default_config(settings_values)
    try:
        loaded = json.loads(config_path().read_text(encoding="utf-8"))
        if loaded.get("version") != 1:
            return config
        if isinstance(loaded.get("images"), dict):
            for key in PICTURE_KEYS:
                if isinstance(loaded["images"].get(key), dict):
                    config["images"][key] = {
                        str(k): str(v) for k, v in loaded["images"][key].items()
                        if isinstance(k, str) and isinstance(v, str)
                    }
        if loaded.get("placement") in ("zoom", "scaled", "stretched", "centered", "wallpaper"):
            config["placement"] = loaded["placement"]
        if loaded.get("alignment") in ALIGNMENTS:
            config["alignment"] = loaded["alignment"]
        if isinstance(loaded.get("auto_rebuild"), bool):
            config["auto_rebuild"] = loaded["auto_rebuild"]
        border = loaded.get("border", 0.0)
        if isinstance(border, (int, float)) and math.isfinite(border) and 0 <= border <= 0.25:
            config["border"] = float(border)
        if isinstance(loaded.get("single"), dict):
            for key in config["single"]:
                if isinstance(loaded["single"].get(key), str):
                    config["single"][key] = loaded["single"][key]
        if isinstance(loaded.get("generated"), dict):
            for key in PICTURE_KEYS:
                if isinstance(loaded["generated"].get(key), str):
                    config["generated"][key] = loaded["generated"][key]
        if isinstance(loaded.get("layout"), str):
            config["layout"] = loaded["layout"]
        requested_multi = bool(loaded.get("enabled"))
        generated_active = (requested_multi or config["border"] > 0 or
                            config["alignment"] != "center") and all(
            settings_values[key] == config["generated"][key]
            for key in PICTURE_KEYS) and settings_values["picture-options"] == "spanned"
        config["enabled"] = requested_multi and generated_active
        if not generated_active:
            config["border"] = 0.0
            config["alignment"] = "center"
            config["single"] = {key: settings_values[key] for key in config["single"]}
        undo = loaded.get("undo")
        if (isinstance(undo, dict) and isinstance(undo.get("settings"), dict) and
                isinstance(undo.get("config"), dict) and
                isinstance(undo.get("applied"), dict) and all(
                    isinstance(undo["settings"].get(key), str) and
                    undo["applied"].get(key) == settings_values.get(key)
                    for key in EDITABLE_KEYS) and
                valid_snapshot_config(undo["config"])):
            config["undo"] = undo
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return config


def save_config(config):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".monitors-", suffix=".json", delete=False) as stream:
        temp_path = Path(stream.name)
        json.dump(config, stream, indent=2, sort_keys=True)
        stream.write("\n")
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def generate_wallpapers(monitors, config, color):
    output_dir = generated_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = {}
    created = []
    try:
        for key, name in (("picture-uri", "light"), ("picture-uri-dark", "dark")):
            image = render_composite(monitors, config["images"][key],
                                     config["placement"], color,
                                     border=config.get("border", 0.0),
                                     alignment=config.get("alignment", "center"),
                                     allow_mirrored=not config["enabled"])
            path = output_dir / f"{name}-{uuid4().hex}.png"
            with tempfile.NamedTemporaryFile(dir=output_dir, prefix=f".{name}-",
                                             suffix=".png", delete=False) as stream:
                temp_path = Path(stream.name)
            try:
                image.convert("RGB").save(temp_path, format="PNG", optimize=True)
                os.replace(temp_path, path)
                created.append(path)
            finally:
                temp_path.unlink(missing_ok=True)
            generated[key] = path.as_uri()
    except Exception:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return generated, layout_signature(monitors)


def clean_old_wallpapers(keep_uris):
    directory = generated_dir()
    keep = {unquote(urlparse(uri).path) for uri in keep_uris
            if uri and urlparse(uri).scheme == "file"}
    for pattern in ("light-*.png", "dark-*.png"):
        for path in directory.glob(pattern):
            if str(path) not in keep:
                path.unlink(missing_ok=True)


def retained_wallpapers(settings_values, config):
    """Keep current sources plus the previous desktop and its source images."""
    uris = [settings_values.get(key, "") for key in PICTURE_KEYS]
    for key in PICTURE_KEYS:
        uris.append(config["single"].get(key, ""))
        uris.extend(config["images"][key].values())
    undo = config.get("undo")
    if undo:
        uris.extend(undo["settings"].get(key, "") for key in PICTURE_KEYS)
        previous = undo["config"]
        for key in PICTURE_KEYS:
            uris.append(previous.get("single", {}).get(key, ""))
            uris.extend(previous.get("images", {}).get(key, {}).values())
    return uris


def cloned(config):
    return copy.deepcopy(config)
