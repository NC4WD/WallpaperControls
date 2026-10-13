# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from PIL import Image

from monitor_wallpaper import MonitorSpec, image_dimensions, render_composite


def test_remote_command_line_image_is_rejected_with_a_readable_error():
    pytest.importorskip("gi")
    from wallpaper_controls import image_uri_from_file
    # Gio.File.get_path() returns None for a URI that is not a local file.
    with pytest.raises(ValueError, match="stored on this computer"):
        image_uri_from_file(None)


@pytest.mark.parametrize("format,extension", [("PNG", "png"), ("JPEG", "jpg"),
    ("WEBP", "webp"), ("GIF", "gif"), ("BMP", "bmp"), ("TIFF", "tiff")])
def test_advertised_image_formats_can_be_chosen_and_composed(tmp_path, format, extension):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk
    Gtk.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("GTK decoder checks require a display outside the tool sandbox.")
    from wallpaper_controls import image_uri_from_file
    path = tmp_path / f"source.{extension}"
    Image.new("RGB", (16, 12), "red").save(path, format=format)
    uri = image_uri_from_file(path)
    result = render_composite([MonitorSpec("one", "One", 0, 0, 16, 12)],
                              {"one": uri}, "zoom", "#000000")
    assert result.size == (16, 12)


def test_svg_can_be_chosen_and_composed(tmp_path):
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk
    Gtk.init()
    if Gdk.Display.get_default() is None:
        pytest.skip("SVG decoder check requires a display outside the tool sandbox.")
    from wallpaper_controls import image_uri_from_file
    path = tmp_path / "source.svg"
    path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="12">'
                    '<rect width="16" height="12" fill="red"/></svg>')
    result = render_composite([MonitorSpec("one", "One", 0, 0, 16, 12)],
                              {"one": image_uri_from_file(path)}, "zoom", "#000000")
    assert result.getpixel((8, 6))[:3] == (255, 0, 0)


def test_camera_orientation_is_used_for_dimensions_and_rendering(tmp_path):
    path = tmp_path / "camera.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (30, 20), "red").save(path, exif=exif)
    assert image_dimensions(path.as_uri()) == (20, 30)
    result = render_composite([MonitorSpec("one", "One", 0, 0, 20, 30)],
                              {"one": path.as_uri()}, "scaled", "#0000ff")
    assert result.getpixel((0, 0))[:3] != (0, 0, 255)
