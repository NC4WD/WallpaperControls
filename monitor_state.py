# SPDX-License-Identifier: GPL-3.0-or-later
"""Persist source images and generated GNOME wallpapers for each monitor."""

import copy
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import unquote, urlparse
from uuid import uuid4

from monitor_wallpaper import layout_signature, render_composite


PICTURE_KEYS = ("picture-uri", "picture-uri-dark")


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
        "generated": {key: "" for key in PICTURE_KEYS},
        "layout": "",
    }


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
        border = loaded.get("border", 0.0)
        if isinstance(border, (int, float)) and 0 <= border <= 0.25:
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
        generated_active = (requested_multi or config["border"] > 0) and all(
            settings_values[key] == config["generated"][key]
            for key in PICTURE_KEYS) and settings_values["picture-options"] == "spanned"
        config["enabled"] = requested_multi and generated_active
        if not generated_active:
            config["border"] = 0.0
            config["single"] = {key: settings_values[key] for key in config["single"]}
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
    for key, name in (("picture-uri", "light"), ("picture-uri-dark", "dark")):
        image = render_composite(monitors, config["images"][key],
                                 config["placement"], color,
                                 border=config.get("border", 0.0))
        filename = f"{name}-{uuid4().hex}.png"
        path = output_dir / filename
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=f".{name}-",
                                         suffix=".png", delete=False) as stream:
            temp_path = Path(stream.name)
        try:
            image.convert("RGB").save(temp_path, format="PNG", optimize=True)
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)
        generated[key] = path.as_uri()
    return generated, layout_signature(monitors)


def clean_old_wallpapers(keep_uris):
    directory = generated_dir()
    keep = {unquote(urlparse(uri).path) for uri in keep_uris
            if uri and urlparse(uri).scheme == "file"}
    for pattern in ("light-*.png", "dark-*.png"):
        for path in directory.glob(pattern):
            if str(path) not in keep:
                path.unlink(missing_ok=True)


def cloned(config):
    return copy.deepcopy(config)
