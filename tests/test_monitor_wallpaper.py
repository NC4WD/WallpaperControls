# SPDX-License-Identifier: GPL-3.0-or-later
from pathlib import Path

import pytest
from PIL import Image

from monitor_wallpaper import (MonitorSpec, layout_signature,
                               placement_covers_viewport, render_composite)
from monitor_state import default_config, generate_wallpapers, load_config, save_config


def image_uri(path, color, size=(20, 10)):
    Image.new("RGB", size, color).save(path)
    return path.as_uri()


def test_composition_respects_monitor_positions_and_gaps(tmp_path):
    red = image_uri(tmp_path / "red.png", "red")
    blue = image_uri(tmp_path / "blue.png", "blue")
    monitors = [
        MonitorSpec("left", "Left", -100, 0, 100, 60),
        MonitorSpec("right", "Right", 0, 10, 80, 50),
    ]
    result = render_composite(monitors, {"left": red, "right": blue},
                              "zoom", "#000000", scale=1)
    assert result.size == (180, 60)
    assert result.getpixel((10, 10))[:3] == (255, 0, 0)
    assert result.getpixel((110, 20))[:3] == (0, 0, 255)
    assert result.getpixel((110, 0))[:3] == (0, 0, 0)
    assert layout_signature(monitors) == layout_signature(list(reversed(monitors)))


def test_fit_keeps_border_color_inside_monitor(tmp_path):
    red = image_uri(tmp_path / "wide.png", "red", (20, 10))
    monitor = MonitorSpec("one", "One", 0, 0, 20, 20)
    result = render_composite([monitor], {"one": red},
                              "scaled", "#0000ff", scale=1)
    assert result.getpixel((10, 0))[:3] == (0, 0, 255)
    assert result.getpixel((10, 10))[:3] == (255, 0, 0)


def test_center_uses_the_real_viewport_size():
    assert placement_covers_viewport(1672, 941, 1366, 768, "centered")
    assert not placement_covers_viewport(1672, 941, 1920, 1080, "centered")


def test_explicit_border_is_visible_with_a_matching_image(tmp_path):
    red = image_uri(tmp_path / "matching.png", "red", (20, 10))
    monitor = MonitorSpec("one", "One", 0, 0, 20, 10)
    result = render_composite([monitor], {"one": red},
                              "scaled", "#0000ff", scale=1, border=0.1)
    assert result.getpixel((0, 0))[:3] == (0, 0, 255)
    assert result.getpixel((10, 5))[:3] == (255, 0, 0)


def test_border_supports_a_spanned_single_image(tmp_path):
    red = image_uri(tmp_path / "wide.png", "red", (40, 10))
    monitors = [
        MonitorSpec("left", "Left", 0, 0, 20, 10),
        MonitorSpec("right", "Right", 20, 0, 20, 10),
    ]
    result = render_composite(monitors, {"left": red, "right": red},
                              "spanned", "#0000ff", scale=1, border=0.1)
    assert result.getpixel((0, 0))[:3] == (0, 0, 255)
    assert result.getpixel((20, 5))[:3] == (255, 0, 0)


def test_mirrored_displays_and_missing_images_fail_clearly(tmp_path):
    red = image_uri(tmp_path / "red.png", "red")
    monitor = MonitorSpec("one", "One", 0, 0, 20, 20)
    with pytest.raises(ValueError, match="mirroring"):
        render_composite([monitor, MonitorSpec("two", "Two", 0, 0, 20, 20)],
                         {"one": red, "two": red}, "zoom", "#000000")
    with pytest.raises(ValueError, match="Choose an image for One"):
        render_composite([monitor], {}, "zoom", "#000000")


def test_generated_wallpaper_and_preferences_survive_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    red = image_uri(tmp_path / "red.png", "red")
    blue = image_uri(tmp_path / "blue.png", "blue")
    values = {"picture-uri": red, "picture-uri-dark": blue,
              "picture-options": "zoom"}
    config = default_config(values)
    config["enabled"] = True
    config["images"] = {
        "picture-uri": {"one": red}, "picture-uri-dark": {"one": blue},
    }
    monitors = [MonitorSpec("one", "One", 0, 0, 30, 20)]
    generated, signature = generate_wallpapers(monitors, config, "#000000000000")
    config["generated"] = generated
    config["layout"] = signature
    save_config(config)
    current = {**values, **generated, "picture-options": "spanned"}
    restored = load_config(current)
    assert restored["enabled"]
    assert restored["images"] == config["images"]
    assert Path(generated["picture-uri"].removeprefix("file://")).is_file()


def test_single_wallpaper_border_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    red = image_uri(tmp_path / "red.png", "red")
    blue = image_uri(tmp_path / "blue.png", "blue")
    values = {"picture-uri": red, "picture-uri-dark": blue,
              "picture-options": "scaled"}
    config = default_config(values)
    config["border"] = 0.06
    config["images"] = {
        "picture-uri": {"one": red}, "picture-uri-dark": {"one": blue},
    }
    monitors = [MonitorSpec("one", "One", 0, 0, 30, 20)]
    generated, signature = generate_wallpapers(monitors, config, "#000000")
    config["generated"] = generated
    config["layout"] = signature
    save_config(config)
    current = {**values, **generated, "picture-options": "spanned"}
    restored = load_config(current)
    assert not restored["enabled"]
    assert restored["border"] == 0.06
    assert restored["single"] == config["single"]


@pytest.mark.parametrize("placement", ["zoom", "centered"])
@pytest.mark.parametrize("alignment,pixel", [("left", (255, 0, 0)),
                                            ("right", (0, 0, 255))])
def test_alignment_keeps_the_selected_side_of_a_cropped_image(tmp_path, placement,
                                                            alignment, pixel):
    source = Image.new("RGB", (40, 20), "red")
    source.paste("blue", (20, 0, 40, 20))
    source.save(tmp_path / "two-sides.png")
    monitor = MonitorSpec("one", "One", 0, 0, 10, 20)
    result = render_composite([monitor], {"one": (tmp_path / "two-sides.png").as_uri()},
                              placement, "#ffffff", scale=1, alignment=alignment)
    assert result.getpixel((5, 10))[:3] == pixel


def test_fit_alignment_moves_uncovered_space_to_the_opposite_edge(tmp_path):
    uri = image_uri(tmp_path / "wide.png", "red", (20, 10))
    monitor = MonitorSpec("one", "One", 0, 0, 20, 20)
    result = render_composite([monitor], {"one": uri}, "scaled", "#0000ff",
                              scale=1, alignment="top")
    assert result.getpixel((10, 0))[:3] == (255, 0, 0)
    assert result.getpixel((10, 19))[:3] == (0, 0, 255)


def test_hidpi_center_preview_and_wallpaper_use_the_same_natural_size(tmp_path):
    uri = image_uri(tmp_path / "source.png", "red", (20, 10))
    monitor = MonitorSpec("one", "One", 0, 0, 20, 20, 2)
    preview = render_composite([monitor], {"one": uri}, "centered", "#0000ff", scale=1)
    final = render_composite([monitor], {"one": uri}, "centered", "#0000ff")
    assert final.size == (40, 40)
    assert preview.getpixel((4, 10))[:3] == (0, 0, 255)
    assert preview.getpixel((6, 10))[:3] == (255, 0, 0)
    assert final.getpixel((8, 20))[:3] == (0, 0, 255)
    assert final.getpixel((12, 20))[:3] == (255, 0, 0)
