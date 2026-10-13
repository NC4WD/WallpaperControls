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
NATIVE_PLACEMENTS = ("none", "zoom", "scaled", "stretched", "centered", "wallpaper", "spanned")


def uses_generated_wallpaper(config):
    if not config["enabled"] and config["single"]["picture-options"] == "none":
        return False
    return (config["enabled"] or config.get("border", 0.0) > 0 or
            config.get("alignment", "center") != "center")


def single_image_uri(config, key):
    """GNOME uses the light image when no separate dark image is selected."""
    return config["single"][key] or (config["single"]["picture-uri"] if key == "picture-uri-dark" else "")


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
    single, images, generated = config.get("single"), config.get("images"), config.get("generated")
    border = config.get("border")
    return (config.get("version") == 1 and isinstance(config.get("enabled"), bool) and
            isinstance(config.get("auto_rebuild"), bool) and
            isinstance(config.get("alignment"), str) and config["alignment"] in ALIGNMENTS and
            config.get("placement") in ("none", "zoom", "scaled", "stretched", "centered", "wallpaper") and
            isinstance(border, (int, float)) and 0 <= border <= 0.25 and math.isfinite(border) and
            isinstance(config.get("layout"), str) and isinstance(single, dict) and
            all(isinstance(single.get(key), str) for key in (*PICTURE_KEYS, "picture-options")) and
            single["picture-options"] in NATIVE_PLACEMENTS and
            isinstance(generated, dict) and
            all(isinstance(generated.get(key), str) for key in PICTURE_KEYS) and
            config.get("undo") is None and
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
        if loaded.get("placement") in ("none", "zoom", "scaled", "stretched", "centered", "wallpaper"):
            config["placement"] = loaded["placement"]
        if isinstance(loaded.get("alignment"), str) and loaded["alignment"] in ALIGNMENTS:
            config["alignment"] = loaded["alignment"]
        if isinstance(loaded.get("auto_rebuild"), bool):
            config["auto_rebuild"] = loaded["auto_rebuild"]
        border = loaded.get("border", 0.0)
        if isinstance(border, (int, float)) and 0 <= border <= 0.25 and math.isfinite(border):
            config["border"] = float(border)
        if isinstance(loaded.get("single"), dict):
            for key in config["single"]:
                if (isinstance(loaded["single"].get(key), str) and
                        (key != "picture-options" or loaded["single"][key] in NATIVE_PLACEMENTS)):
                    config["single"][key] = loaded["single"][key]
        if isinstance(loaded.get("generated"), dict):
            for key in PICTURE_KEYS:
                if isinstance(loaded["generated"].get(key), str):
                    config["generated"][key] = loaded["generated"][key]
        if isinstance(loaded.get("layout"), str):
            config["layout"] = loaded["layout"]
        requested_multi = loaded.get("enabled") is True
        generated_active = (requested_multi or config["border"] > 0 or
                            config["alignment"] != "center") and all(
            bool(config["generated"][key]) and settings_values[key] == config["generated"][key]
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
    except (OSError, ValueError, TypeError, AttributeError, RecursionError, OverflowError):
        pass
    return config


def save_config(config):
    contents = (json.dumps(config, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    write_config_bytes(contents)


def write_config_bytes(contents):
    """Atomically write preferences, or restore the absence of a config file."""
    path = config_path()
    if contents is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent,
                                         prefix=".monitors-", suffix=".json", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
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
