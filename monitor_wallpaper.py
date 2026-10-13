# SPDX-License-Identifier: GPL-3.0-or-later
"""Compose one GNOME spanned wallpaper from per-monitor images."""

from dataclasses import dataclass
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError


MAX_PIXELS = 32_000_000
MAX_SOURCE_PIXELS = 64_000_000
PER_MONITOR_PLACEMENTS = ("zoom", "scaled", "stretched", "centered", "wallpaper", "none")
ALIGNMENTS = {
    "center": (0.5, 0.5), "top": (0.5, 0.0), "bottom": (0.5, 1.0),
    "left": (0.0, 0.5), "right": (1.0, 0.5),
    "top-left": (0.0, 0.0), "top-right": (1.0, 0.0),
    "bottom-left": (0.0, 1.0), "bottom-right": (1.0, 1.0),
}


@dataclass(frozen=True)
class MonitorSpec:
    connector: str
    label: str
    x: int
    y: int
    width: int
    height: int
    scale: float = 1.0


def monitors_from_display(display):
    """Return monitors in GDK's shared logical coordinate space."""
    model = display.get_monitors()
    monitors = []
    seen = set()
    for index in range(model.get_n_items()):
        monitor = model.get_item(index)
        geometry = monitor.get_geometry()
        connector = monitor.get_connector() or f"display-{index + 1}"
        if connector in seen:
            connector = f"{connector}-{index + 1}"
        seen.add(connector)
        model_name = monitor.get_model()
        label = connector if not model_name or model_name == connector else f"{connector} · {model_name}"
        scale = monitor.get_scale() if hasattr(monitor, "get_scale") else monitor.get_scale_factor()
        monitors.append(MonitorSpec(
            connector, label, geometry.x, geometry.y,
            geometry.width, geometry.height, float(scale)))
    return monitors


def layout_signature(monitors):
    data = sorted((m.connector, m.x, m.y, m.width, m.height, m.scale)
                  for m in monitors)
    return hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()


def bounds(monitors):
    if not monitors:
        raise ValueError("Connect a monitor before applying a wallpaper.")
    left = min(m.x for m in monitors)
    top = min(m.y for m in monitors)
    right = max(m.x + m.width for m in monitors)
    bottom = max(m.y + m.height for m in monitors)
    return left, top, right - left, bottom - top


def check_layout(monitors, allow_mirrored=False):
    for index, a in enumerate(monitors):
        if a.width <= 0 or a.height <= 0:
            raise ValueError(f"The size of {a.label} couldn't be read. Check your display settings.")
        if not math.isfinite(a.scale) or a.scale <= 0:
            raise ValueError("The monitor's scale couldn't be read. Check your display settings.")
        for b in monitors[index + 1:]:
            overlap_x = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
            overlap_y = min(a.y + a.height, b.y + b.height) - max(a.y, b.y)
            if overlap_x > 0 and overlap_y > 0:
                if allow_mirrored and (a.x, a.y, a.width, a.height) == (b.x, b.y, b.width, b.height):
                    continue
                raise ValueError("These monitors show the same screen. Turn off mirroring to use different wallpapers.")


def placement_covers_viewport(image_width, image_height, viewport_width,
                              viewport_height, placement):
    """Return whether an opaque image leaves no background color visible."""
    if min(image_width, image_height, viewport_width, viewport_height) <= 0:
        return False
    if placement in ("zoom", "stretched", "spanned"):
        return True
    if placement == "scaled":
        image_ratio = image_width / image_height
        viewport_ratio = viewport_width / viewport_height
        return abs(image_ratio - viewport_ratio) / viewport_ratio < 0.01
    if placement == "centered":
        return image_width >= viewport_width and image_height >= viewport_height
    return False


def _color_rgb(color):
    value = color.removeprefix("#")
    if color.startswith("#") and len(value) == 12:
        try:
            return tuple(round(int(value[index:index + 4], 16) / 257)
                         for index in (0, 4, 8))
        except ValueError:
            return (0, 0, 0)
    try:
        return ImageColor.getrgb(color)[:3]
    except ValueError:
        pass
    return (0, 0, 0)


def check_image_size(width, height):
    if width <= 0 or height <= 0:
        raise ValueError("This file can't be opened as an image. Choose another file.")
    if width * height > MAX_SOURCE_PIXELS:
        raise ValueError("This image is too large. Choose an image smaller than 64 megapixels.")


def _path_from_uri(uri):
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("Choose an image stored on this computer for each monitor.")
    return Path(unquote(parsed.path))


def image_dimensions(uri):
    """Read displayed dimensions, including camera EXIF orientation."""
    path = _path_from_uri(uri)
    try:
        with Image.open(path) as source:
            width, height = source.size
            check_image_size(width, height)
            if source.getexif().get(274) in (5, 6, 7, 8):
                width, height = height, width
            return width, height
    except Image.DecompressionBombError as error:
        raise ValueError("This image is too large. Choose a smaller image.") from error
    except (OSError, UnidentifiedImageError) as error:
        if path.suffix.lower() == ".svg":
            import gi
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            _format, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
            check_image_size(width, height)
            return width, height
        raise ValueError(f"Couldn't open {path.name}. Choose another image.") from error


def _load_image(uri):
    path = _path_from_uri(uri)
    try:
        with Image.open(path) as source:
            check_image_size(source.width, source.height)
            return ImageOps.exif_transpose(source).convert("RGBA")
    except Image.DecompressionBombError as error:
        raise ValueError("This image is too large. Choose a smaller image.") from error
    except (OSError, UnidentifiedImageError) as error:
        # Keep GTK's SVG image support when using generated wallpapers too.
        if path.suffix.lower() == ".svg":
            try:
                import gi
                gi.require_version("GdkPixbuf", "2.0")
                from gi.repository import GdkPixbuf
                _format, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
                check_image_size(width, height)
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
                _success, data = pixbuf.save_to_bufferv("png", [], [])
                with Image.open(BytesIO(data)) as source:
                    return source.convert("RGBA")
            except ValueError:
                raise
            except Exception as svg_error:
                raise ValueError(f"Couldn't open {path.name}. Choose another image.") from svg_error
        raise ValueError(f"Couldn't open {path.name}. Choose another image.") from error


def _place_image(canvas, source, rectangle, placement, scale, alignment="center"):
    x, y, width, height = rectangle
    ax, ay = ALIGNMENTS[alignment]
    if placement == "stretched":
        canvas.alpha_composite(source.resize((width, height), Image.Resampling.LANCZOS), (x, y))
    elif placement == "scaled":
        image = ImageOps.contain(source, (width, height), Image.Resampling.LANCZOS)
        canvas.alpha_composite(image, (x + round((width - image.width) * ax),
                                       y + round((height - image.height) * ay)))
    elif placement == "centered":
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        visible_width, visible_height = min(size[0], width), min(size[1], height)
        crop_left = max(0, round((size[0] - width) * ax))
        crop_top = max(0, round((size[1] - height) * ay))
        # Resize only the visible source region. A HiDPI layout must not
        # allocate a giant enlarged image just to crop almost all of it away.
        fx, fy = source.width / size[0], source.height / size[1]
        box = (crop_left * fx, crop_top * fy,
               min(source.width, (crop_left + visible_width) * fx),
               min(source.height, (crop_top + visible_height) * fy))
        image = source.resize((visible_width, visible_height), Image.Resampling.LANCZOS, box=box)
        canvas.alpha_composite(image, (x + round((width - image.width) * ax),
                                       y + round((height - image.height) * ay)))
    elif placement == "wallpaper":
        size = (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        tw, th = min(size[0], width), min(size[1], height)
        box = (0, 0, source.width * tw / size[0], source.height * th / size[1])
        image = source.resize((tw, th), Image.Resampling.LANCZOS, box=box)
        tiled = Image.new("RGBA", (width, height))
        tiled.paste(image, (0, 0))
        # Double completed strips instead of looping millions of times for
        # a one-pixel tile. Raw copies retain alpha; composite only once.
        filled_width = tw
        while filled_width < width:
            piece_width = min(filled_width, width - filled_width)
            tiled.paste(tiled.crop((0, 0, piece_width, th)), (filled_width, 0))
            filled_width += piece_width
        filled_height = th
        while filled_height < height:
            piece_height = min(filled_height, height - filled_height)
            tiled.paste(tiled.crop((0, 0, width, piece_height)), (0, filled_height))
            filled_height += piece_height
        canvas.alpha_composite(tiled, (x, y))
    else:  # zoom / Fill Screen
        image = ImageOps.fit(source, (width, height), Image.Resampling.LANCZOS,
                            centering=(ax, ay))
        canvas.alpha_composite(image, (x, y))


def render_composite(monitors, image_uris, placement, color, scale=None,
                     allow_missing=False, border=0.0, alignment="center", allow_mirrored=False):
    """Return a Pillow RGBA image matching the joined display layout."""
    check_layout(monitors, allow_mirrored=allow_mirrored)
    left, top, logical_width, logical_height = bounds(monitors)
    if placement not in (*PER_MONITOR_PLACEMENTS, "spanned"):
        raise ValueError("Choose how to size the wallpaper image.")
    if alignment not in ALIGNMENTS:
        raise ValueError("Choose an image position.")
    if scale is None:
        scale = max(m.scale for m in monitors)
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("The monitor's scale couldn't be read. Check your display settings.")
    if not isinstance(border, (int, float)) or not math.isfinite(border) or not 0 <= border <= 0.25:
        raise ValueError("Choose a border width.")
    width = max(1, round(logical_width * scale))
    height = max(1, round(logical_height * scale))
    if width * height > MAX_PIXELS:
        raise ValueError("This monitor arrangement is too large. Try a lower display resolution.")
    canvas = Image.new("RGBA", (width, height), (*_color_rgb(color), 255))
    if placement == "none":
        return canvas
    if placement == "spanned":
        uri = image_uris.get(monitors[0].connector)
        if not uri:
            raise ValueError("Choose an image before applying the wallpaper.")
        inset = round(min(width, height) * border)
        rectangle = (inset, inset, max(1, width - inset * 2),
                     max(1, height - inset * 2))
        _place_image(canvas, _load_image(uri), rectangle, "zoom", scale, alignment)
        return canvas
    for monitor in monitors:
        uri = image_uris.get(monitor.connector)
        if not uri:
            if allow_missing:
                continue
            raise ValueError(f"Choose an image for {monitor.label}.")
        x = round((monitor.x - left) * scale)
        y = round((monitor.y - top) * scale)
        right = round((monitor.x + monitor.width - left) * scale)
        bottom = round((monitor.y + monitor.height - top) * scale)
        monitor_width = right - x
        monitor_height = bottom - y
        inset = round(min(monitor_width, monitor_height) * border)
        rectangle = (x + inset, y + inset,
                     max(1, monitor_width - inset * 2),
                     max(1, monitor_height - inset * 2))
        # Natural image pixels must retain their size on HiDPI monitors,
        # including when rendering a reduced preview of the same layout.
        _place_image(canvas, _load_image(uri), rectangle, placement,
                     scale / monitor.scale, alignment)
    return canvas
