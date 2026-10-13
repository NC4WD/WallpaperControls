#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small GTK front end for GNOME's wallpaper settings."""

import os
import sys
from io import BytesIO
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from monitor_wallpaper import (bounds, layout_signature, monitors_from_display,
                               placement_covers_viewport, render_composite)
from monitor_state import (EDITABLE_KEYS, PICTURE_KEYS, cloned, editable_settings,
                           ensure_monitor_images, load_config, merge_pending,
                           uses_generated_wallpaper)
from wallpaper_backend import apply_wallpaper, rebuild_for_layout, undo_last_apply
from desktop_integration import stop_running_app, sync_autostart


APP_ID = "io.github.nc4wd.WallpaperControls"
APP_VERSION = "0.2.0"
PROJECT_URL = "https://github.com/NC4WD/WallpaperControls"
BACKGROUND_SCHEMA = "org.gnome.desktop.background"
PLACEMENTS = (
    ("Fill screen", "zoom"),
    ("Fit image", "scaled"),
    ("Stretch", "stretched"),
    ("Original size", "centered"),
    ("Tile", "wallpaper"),
    ("Span monitors", "spanned"),
)
PLACEMENT_DESCRIPTIONS = {
    "zoom": "Fill the screen, cropping edges if needed",
    "scaled": "Show the whole image without cropping",
    "stretched": "Stretch the image to fill the screen",
    "centered": "Keep the original image size; large images may be cropped",
    "wallpaper": "Repeat the image to fill the screen",
    "spanned": "Spread one image across all monitors",
}
PLACEMENT_KEYS = [value for _, value in PLACEMENTS]
BORDERS = (
    ("None", 0.0),
    ("Small", 0.03),
    ("Medium", 0.06),
    ("Large", 0.10),
)
ALIGNMENT_CHOICES = (
    ("Center", "center"), ("Top", "top"), ("Bottom", "bottom"),
    ("Left", "left"), ("Right", "right"), ("Top Left", "top-left"),
    ("Top Right", "top-right"), ("Bottom Left", "bottom-left"),
    ("Bottom Right", "bottom-right"),
)


def active_wallpaper_key():
    appearance = Gio.Settings.new("org.gnome.desktop.interface")
    return "picture-uri-dark" if appearance.get_string("color-scheme") == "prefer-dark" else "picture-uri"


def image_uri_from_file(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose an image file.")
    try:
        info = GdkPixbuf.Pixbuf.get_file_info(str(path))
        if not info[0] or info[1] <= 0 or info[2] <= 0:
            raise ValueError("This file can't be opened as an image. Choose another file.")
        GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 1, 1, True)
    except GLib.Error as error:
        raise ValueError("This file can't be opened as an image. Choose another file.") from error
    return Gio.File.new_for_path(str(path)).get_uri()


def file_from_uri(uri):
    if not uri:
        return None
    file = Gio.File.new_for_uri(uri)
    return file.get_path() if file.is_native() else None


class WallpaperPreview(Gtk.DrawingArea):
    """Draw the same composed pixels used by Apply, with optional display labels."""
    def __init__(self, height):
        super().__init__()
        self.set_content_width(280)
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self.draw)
        self.pixbuf = None
        self.monitors = []
        self.frame = (0, 0, 1, 1)
        self.placeholder_label = "Choose an image to preview"

    def update_composite(self, image, monitors, show_labels=True):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buffer.getvalue())
        loader.close()
        self.pixbuf = loader.get_pixbuf()
        self.monitors = monitors if show_labels else []
        self.queue_draw()

    def clear(self, label="Choose an image to preview"):
        self.pixbuf = None
        self.monitors = []
        self.placeholder_label = label
        self.queue_draw()

    def monitor_at(self, x, y):
        if not self.monitors:
            return None
        fx, fy, fw, fh = self.frame
        left, top, width, height = bounds(self.monitors)
        px = left + (x - fx) * width / fw
        py = top + (y - fy) * height / fh
        for monitor in self.monitors:
            if (monitor.x <= px < monitor.x + monitor.width and
                    monitor.y <= py < monitor.y + monitor.height):
                return monitor.connector
        return None

    def draw(self, _area, cr, width, height):
        ratio = self.pixbuf.get_width() / self.pixbuf.get_height() if self.pixbuf else 16 / 9
        fw = max(1, width - 28)
        fh = min(max(1, height - 28), fw / ratio)
        fw = min(fw, fh * ratio)
        x, y = (width - fw) / 2, (height - fh) / 2
        self.frame = (x, y, fw, fh)
        cr.set_source_rgba(0, 0, 0, 0.13)
        cr.rectangle(x + 3, y + 5, fw, fh)
        cr.fill()
        cr.save()
        cr.rectangle(x, y, fw, fh)
        cr.clip()
        if self.pixbuf:
            cr.save()
            cr.translate(x, y)
            cr.scale(fw / self.pixbuf.get_width(), fh / self.pixbuf.get_height())
            Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
            cr.paint()
            cr.restore()
            if self.monitors:
                left, top, lw, lh = bounds(self.monitors)
                for number, monitor in enumerate(self.monitors, 1):
                    mx = x + (monitor.x - left) * fw / lw
                    my = y + (monitor.y - top) * fh / lh
                    mw, mh = monitor.width * fw / lw, monitor.height * fh / lh
                    cr.set_source_rgba(1, 1, 1, 0.75)
                    cr.set_line_width(1.5)
                    cr.rectangle(mx + 1, my + 1, mw - 2, mh - 2)
                    cr.stroke()
                    cr.set_source_rgba(0, 0, 0, 0.7)
                    cr.rectangle(mx + 4, my + 4, min(mw - 8, 125), 23)
                    cr.fill()
                    cr.set_source_rgb(1, 1, 1)
                    cr.set_font_size(12)
                    cr.move_to(mx + 8, my + 20)
                    cr.show_text(f"{number} · {monitor.connector[:12]}")
        else:
            cr.set_source_rgba(0.5, 0.5, 0.5, 0.9)
            cr.set_font_size(14)
            extents = cr.text_extents(self.placeholder_label)
            cr.move_to(x + (fw - extents.width) / 2, y + fh / 2)
            cr.show_text(self.placeholder_label)
        cr.restore()


class WallpaperWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Wallpaper Controls")
        display = Gdk.Display.get_default()
        monitor_model = display.get_monitors()
        geometries = [monitor_model.get_item(index).get_geometry()
                      for index in range(monitor_model.get_n_items())]
        screen_width = min((geometry.width for geometry in geometries), default=1366)
        screen_height = min((geometry.height for geometry in geometries), default=768)
        window_width = max(320, min(830, screen_width - 48))
        window_height = max(420, min(820, screen_height - 64))
        self.set_default_size(window_width, window_height)
        preview_height = max(160, min(240, round(window_height * 0.26)))
        self.settings = Gio.Settings.new(BACKGROUND_SCHEMA)
        self.selected_key = active_wallpaper_key()
        self.refreshing = False
        self.applying = False
        self.saved = self.read_settings()
        self.config_saved = load_config(self.saved)
        self.draft = editable_settings(self.saved, self.config_saved)
        self.config_draft = cloned(self.config_saved)
        self.monitor_model = monitor_model
        self.monitor_specs = monitors_from_display(display)
        self.layout_dirty = (self.uses_generated_wallpaper(self.config_saved) and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.placement_mode_is_multi = False
        self._force_close = False
        self._close_dialog_open = False
        self._identify_windows = []
        self._identify_timeout = 0
        self._settings_timeout = 0
        self.error_message = ""

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.revert_button = Gtk.Button(label="Discard Changes")
        self.revert_button.set_tooltip_text("Discard edits you haven't applied")
        self.revert_button.connect("clicked", self.on_revert)
        header.pack_start(self.revert_button)
        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.set_tooltip_text("Save these changes to your desktop wallpaper")
        self.apply_button.connect("clicked", self.on_apply)
        header.pack_end(self.apply_button)
        menu = Gio.Menu()
        menu.append("Restore Previous Wallpaper", "win.undo")
        menu.append("Show Monitor Numbers", "win.identify")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        menu_button.set_tooltip_text("More options")
        header.pack_end(menu_button)
        self.undo_action = Gio.SimpleAction.new("undo", None)
        self.undo_action.connect("activate", self.on_undo)
        self.add_action(self.undo_action)
        identify_action = Gio.SimpleAction.new("identify", None)
        identify_action.connect("activate", self.on_identify)
        self.add_action(identify_action)
        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_button.set_tooltip_text("About Wallpaper Controls")
        about_button.connect("clicked", self.on_about)
        header.pack_end(about_button)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)
        self.connect("close-request", self.on_close_request)
        self.connect("unrealize", self.on_unrealize)

        scroll = Gtk.ScrolledWindow()
        self.scroll = scroll
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_overlay_scrolling(False)
        toolbar.set_content(scroll)
        clamp = Adw.Clamp()
        clamp.set_maximum_size(760)
        clamp.set_tightening_threshold(620)
        scroll.set_child(clamp)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        content.set_margin_top(14)
        content.set_margin_bottom(18)
        content.set_margin_start(18)
        content.set_margin_end(18)
        clamp.set_child(content)

        self.preview = WallpaperPreview(preview_height)
        preview_frame = Gtk.Frame()
        preview_frame.add_css_class("card")
        preview_frame.set_child(self.preview)
        self.add_drop_target(self.preview, self.on_preview_drop)
        content.append(preview_frame)
        self.drop_hint = Gtk.Label(label="Drop an image here, then press Apply")
        self.drop_hint.add_css_class("dim-label")
        self.drop_hint.set_wrap(True)
        content.append(self.drop_hint)
        self.hint = Gtk.Label(label="Preview your changes, then press Apply.")
        self.hint.set_halign(Gtk.Align.START)
        self.hint.set_wrap(True)
        self.hint.add_css_class("dim-label")
        self.hint.set_visible(False)
        content.append(self.hint)

        image_group = Adw.PreferencesGroup(title="Wallpaper")
        content.append(image_group)
        mode_row = Adw.ActionRow(
            title="Wallpaper for", subtitle="Edit the wallpaper used in light or dark mode")
        self.mode_dropdown = Gtk.DropDown.new_from_strings(["Light mode", "Dark mode"])
        self.mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.mode_dropdown.set_selected(1 if self.selected_key == "picture-uri-dark" else 0)
        self.mode_dropdown.connect("notify::selected", self.on_mode_changed)
        mode_row.add_suffix(self.mode_dropdown)
        mode_row.set_activatable_widget(self.mode_dropdown)
        image_group.add(mode_row)

        monitor_mode_row = Adw.ActionRow(
            title="Different wallpapers per monitor",
            subtitle="Choose a separate image for each monitor")
        self.monitor_switch = Gtk.Switch()
        self.monitor_switch.set_valign(Gtk.Align.CENTER)
        self.monitor_switch.set_active(self.config_draft["enabled"])
        self.monitor_switch.connect("notify::active", self.on_monitor_mode_changed)
        monitor_mode_row.add_suffix(self.monitor_switch)
        monitor_mode_row.set_activatable_widget(self.monitor_switch)
        image_group.add(monitor_mode_row)

        self.image_row = Adw.ActionRow(title="Wallpaper image")
        choose_button = Gtk.Button(label="Choose Image…")
        choose_button.set_valign(Gtk.Align.CENTER)
        choose_button.connect("clicked", self.on_choose_image)
        self.image_row.add_suffix(choose_button)
        self.image_row.set_activatable_widget(choose_button)
        self.add_drop_target(self.image_row, self.on_image_row_drop)
        image_group.add(self.image_row)

        self.copy_row = Adw.ActionRow(
            subtitle="Use the selected image in light and dark mode")
        self.copy_button = Gtk.Button(label="Use for Both")
        self.copy_button.set_valign(Gtk.Align.CENTER)
        self.copy_button.connect("clicked", self.on_copy_image)
        self.copy_row.add_suffix(self.copy_button)
        image_group.add(self.copy_row)

        self.monitors_group = Adw.PreferencesGroup(title="Connected monitors")
        identify_button = Gtk.Button(label="Show Numbers")
        identify_button.set_tooltip_text("Show a number on each monitor for five seconds")
        identify_button.connect("clicked", self.on_identify)
        self.monitors_group.set_header_suffix(identify_button)
        content.append(self.monitors_group)
        self.monitor_rows = []
        self.rebuild_monitor_rows()

        placement_group = Adw.PreferencesGroup(
            title="Image layout",
            description="These settings apply to both modes and all monitors")
        content.append(placement_group)
        self.placement_row = Adw.ActionRow(title="Image sizing")
        self.placement_dropdown = Gtk.DropDown.new_from_strings([label for label, _ in PLACEMENTS])
        self.placement_dropdown.set_valign(Gtk.Align.CENTER)
        self.placement_dropdown.connect("notify::selected", self.on_placement_changed)
        self.placement_row.add_suffix(self.placement_dropdown)
        self.placement_row.set_activatable_widget(self.placement_dropdown)
        placement_group.add(self.placement_row)

        self.alignment_row = Adw.ActionRow(
            title="Image position", subtitle="Choose where the image sits on the screen")
        self.alignment_dropdown = Gtk.DropDown.new_from_strings(
            [label for label, _ in ALIGNMENT_CHOICES])
        self.alignment_dropdown.set_valign(Gtk.Align.CENTER)
        self.alignment_dropdown.connect("notify::selected", self.on_alignment_changed)
        self.alignment_row.add_suffix(self.alignment_dropdown)
        self.alignment_row.set_activatable_widget(self.alignment_dropdown)
        placement_group.add(self.alignment_row)

        self.color_row = Adw.ActionRow(title="Background color")
        self.color_value_label = Gtk.Label()
        self.color_value_label.add_css_class("dim-label")
        color_dialog = Gtk.ColorDialog(
            title="Choose Background Color", with_alpha=False)
        self.color_button = Gtk.ColorDialogButton(dialog=color_dialog)
        self.color_button.set_valign(Gtk.Align.CENTER)
        self.color_button.set_tooltip_text("Choose a color for the space around the image")
        self.color_button.connect("notify::rgba", self.on_color_changed)
        self.color_row.add_suffix(self.color_value_label)
        self.color_row.add_suffix(self.color_button)
        self.color_row.set_activatable_widget(self.color_button)
        placement_group.add(self.color_row)

        self.border_row = Adw.ActionRow(
            title="Border width",
            subtitle="Add space around the image to show the background color")
        self.border_dropdown = Gtk.DropDown.new_from_strings([label for label, _ in BORDERS])
        self.border_dropdown.set_valign(Gtk.Align.CENTER)
        self.border_dropdown.connect("notify::selected", self.on_border_changed)
        self.border_row.add_suffix(self.border_dropdown)
        self.border_row.set_activatable_widget(self.border_dropdown)
        placement_group.add(self.border_row)

        display_group = Adw.PreferencesGroup(
            title="Monitor changes",
            description="When enabled, works with the app closed and starts at login")
        content.append(display_group)
        self.auto_row = Adw.ActionRow(
            title="Adjust to monitor changes",
            subtitle="Keep saved wallpapers in place when monitors connect, disconnect, or move")
        self.auto_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.auto_switch.connect("notify::active", self.on_auto_changed)
        self.auto_row.add_suffix(self.auto_switch)
        self.auto_row.set_activatable_widget(self.auto_switch)
        display_group.add(self.auto_row)

        self._settings_handler = self.settings.connect("changed", self.on_settings_changed)
        self.render_draft()

    def read_settings(self):
        return {key: self.settings.get_string(key) for key in EDITABLE_KEYS}

    def has_changes(self):
        return (self.draft != editable_settings(self.saved, self.config_saved) or
                self.config_draft != self.config_saved
                or self.layout_dirty)

    @staticmethod
    def uses_generated_wallpaper(config):
        return uses_generated_wallpaper(config)

    def rebuild_monitor_rows(self):
        for row in self.monitor_rows:
            self.monitors_group.remove(row)
        self.monitor_rows = []
        for number, monitor in enumerate(self.monitor_specs, 1):
            row = Adw.ActionRow(title=f"{number} · {monitor.label}")
            button = Gtk.Button(label="Choose Image…")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", self.on_choose_monitor_image, monitor.connector)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            self.add_drop_target(row, self.on_monitor_row_drop, monitor.connector)
            self.monitors_group.add(row)
            self.monitor_rows.append(row)

    def on_monitors_changed(self, *_args):
        self.monitor_specs = monitors_from_display(Gdk.Display.get_default())
        self.close_identification()
        self.rebuild_monitor_rows()
        if self.config_draft["enabled"]:
            ensure_monitor_images(self.config_draft, self.monitor_specs)
        if self.config_saved["enabled"]:
            ensure_monitor_images(self.config_saved, self.monitor_specs)
        self.layout_dirty = (self.uses_generated_wallpaper(self.config_draft) and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.render_draft()

    def render_draft(self):
        self.refreshing = True
        multi = self.config_draft["enabled"]
        border = self.config_draft["border"]
        alignment = self.config_draft["alignment"]
        self.monitor_switch.set_active(multi)
        self.image_row.set_visible(not multi)
        self.monitors_group.set_visible(multi)
        self.drop_hint.set_text("Drop an image onto a monitor below or in the preview, then press Apply"
                                if multi else "Drop an image here, then press Apply")
        uri = self.config_draft["single"][self.selected_key]
        path = file_from_uri(uri)
        self.image_row.set_subtitle(Path(path).name if path else
                                    ("No image selected" if not uri else uri))
        source_mode = "light" if self.selected_key == "picture-uri" else "dark"
        destination = "dark" if self.selected_key == "picture-uri" else "light"
        if multi:
            self.copy_row.set_title("Same images in both modes")
            self.copy_row.set_subtitle(f"Use these {source_mode} mode images in {destination} mode too")
            self.copy_button.set_tooltip_text("Use these monitor images in both modes when you press Apply")
            self.copy_button.set_sensitive(any(self.config_draft["images"][self.selected_key].values()))
        else:
            self.copy_row.set_title("Same image in both modes")
            self.copy_row.set_subtitle(f"Use this {source_mode} mode image in {destination} mode too")
            self.copy_button.set_tooltip_text("Use this image in both modes when you press Apply")
            self.copy_button.set_sensitive(bool(uri))
        if multi != self.placement_mode_is_multi:
            options = PLACEMENTS[:-1] if multi else PLACEMENTS
            self.placement_dropdown.set_model(Gtk.StringList.new([label for label, _ in options]))
            self.placement_mode_is_multi = multi
        placement = (self.config_draft["placement"] if multi else
                     self.config_draft["single"]["picture-options"])
        options = PLACEMENT_KEYS[:-1] if multi else PLACEMENT_KEYS
        self.placement_dropdown.set_selected(options.index(placement) if placement in options else 0)
        self.placement_row.set_subtitle(PLACEMENT_DESCRIPTIONS.get(placement, "Choose how the image fills the screen"))
        alignments = [key for _label, key in ALIGNMENT_CHOICES]
        self.alignment_dropdown.set_selected(alignments.index(alignment))
        self.alignment_row.set_sensitive(placement in ("zoom", "scaled", "centered", "spanned"))
        if placement in ("zoom", "spanned"):
            self.alignment_row.set_subtitle("Choose which part of the image stays visible when cropped")
        elif placement in ("scaled", "centered"):
            self.alignment_row.set_subtitle("Choose where the image sits on the screen")
        else:
            self.alignment_row.set_subtitle("This sizing option does not use image position")
        border_values = [value for _label, value in BORDERS]
        self.border_dropdown.set_selected(
            min(range(len(border_values)), key=lambda index: abs(border_values[index] - border)))
        self.auto_switch.set_active(self.config_draft["auto_rebuild"])
        self.auto_row.set_sensitive(self.uses_generated_wallpaper(self.config_draft))
        self.auto_row.set_subtitle(
            "Keep saved wallpapers in place when monitors connect, disconnect, or move"
            if self.uses_generated_wallpaper(self.config_draft) else
            "Your current image layout already adjusts automatically")
        self.undo_action.set_enabled(bool(self.config_saved.get("undo")) and not self.has_changes())
        color = Gdk.RGBA()
        if not color.parse(self.draft["primary-color"]):
            color.parse("#000000")
        self.color_button.set_rgba(color)
        self.color_value_label.set_text("#{:02X}{:02X}{:02X}".format(
            round(color.red * 255), round(color.green * 255), round(color.blue * 255)))
        if border > 0:
            self.color_row.set_subtitle("Fills the border around the image")
        elif placement in ("zoom", "stretched", "spanned"):
            self.color_row.set_subtitle("Add a border below to make this color visible")
        elif placement == "wallpaper":
            self.color_row.set_subtitle("Shows through transparent parts of a tiled image")
        elif not multi and self.background_is_hidden(uri, placement):
            self.color_row.set_subtitle("Add a border below to make this color visible")
        else:
            self.color_row.set_subtitle("Fills the empty space around the image")
        for row, monitor in zip(self.monitor_rows, self.monitor_specs):
            monitor_uri = self.config_draft["images"][self.selected_key].get(monitor.connector, "")
            filename = Path(file_from_uri(monitor_uri)).name if file_from_uri(monitor_uri) else "No image selected"
            row.set_subtitle(f"{monitor.width} × {monitor.height} · {filename}")
        preview_error = ""
        try:
            # One shared renderer determines preview and final image placement.
            monitors = (self.monitor_specs if multi or placement == "spanned" else
                        self.monitor_specs[:1])
            _, _, logical_width, logical_height = bounds(monitors)
            scale = min(1.0, 720 / logical_width, 340 / logical_height)
            image_map = (self.config_draft["images"][self.selected_key] if multi else
                         {monitor.connector: uri for monitor in monitors})
            image = render_composite(monitors, image_map, placement,
                                     self.draft["primary-color"], scale=scale,
                                     allow_missing=True, border=border, alignment=alignment,
                                     allow_mirrored=not multi)
            self.preview.update_composite(image, monitors, show_labels=multi)
        except (OSError, ValueError, GLib.Error, MemoryError) as error:
            self.preview.clear("Preview unavailable")
            preview_error = str(error)
        self.hint.set_text(self.error_message or preview_error)
        self.hint.set_visible(bool(self.error_message or preview_error))
        changed = self.has_changes()
        self.apply_button.set_sensitive(changed)
        self.revert_button.set_sensitive(changed)
        self.refreshing = False

    def show_error(self, message):
        self.error_message = message
        self.hint.set_text(message)
        self.hint.set_visible(True)

    def reset_saved(self, values=None, config=None):
        self.saved = values if values is not None else self.read_settings()
        self.config_saved = config if config is not None else load_config(self.saved)
        self.config_draft = cloned(self.config_saved)
        self.draft = editable_settings(self.saved, self.config_saved)
        self.layout_dirty = (self.uses_generated_wallpaper(self.config_saved) and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.error_message = ""
        self.render_draft()

    def accept_applied_state(self, values, config):
        # A topology rebuild changes saved state while preserving pending edits.
        if not self.has_changes() or (self.draft == editable_settings(self.saved, self.config_saved)
                                     and self.config_draft == self.config_saved):
            self.reset_saved(values, config)
            return
        old_draft = self.draft.copy()
        old_config = merge_pending(self.config_saved, self.config_draft, config)
        previous_values = editable_settings(self.saved, self.config_saved)
        latest_values = editable_settings(values, config)
        for key in EDITABLE_KEYS:
            if old_draft[key] == previous_values[key]:
                old_draft[key] = latest_values[key]
        # Generated filenames, layout and undo are not user edits.
        for key in ("generated", "layout", "undo"):
            old_config[key] = cloned(config[key])
        self.saved, self.config_saved = values, config
        self.draft, self.config_draft = old_draft, old_config
        self.layout_dirty = (self.uses_generated_wallpaper(old_config) and
                             layout_signature(self.monitor_specs) != config["layout"])
        self.render_draft()

    def image_matches_screen(self, uri):
        path = file_from_uri(uri)
        if not path or not os.path.isfile(path):
            return False
        try:
            _format, width, height = GdkPixbuf.Pixbuf.get_file_info(path)
        except (GLib.Error, TypeError, ValueError):
            return False
        if width <= 0 or height <= 0 or not self.monitor_specs:
            return False
        return all(placement_covers_viewport(
            width, height, monitor.width, monitor.height, "scaled")
            for monitor in self.monitor_specs)

    def background_is_hidden(self, uri, placement):
        if placement in ("zoom", "stretched", "spanned"):
            return True
        if placement == "scaled":
            return self.image_matches_screen(uri)
        if placement != "centered":
            return False
        path = file_from_uri(uri)
        if not path or not os.path.isfile(path):
            return False
        try:
            _format, width, height = GdkPixbuf.Pixbuf.get_file_info(path)
        except (GLib.Error, TypeError, ValueError):
            return False
        return bool(self.monitor_specs) and all(placement_covers_viewport(
            width, height, round(monitor.width * monitor.scale),
            round(monitor.height * monitor.scale), placement)
            for monitor in self.monitor_specs)

    def on_settings_changed(self, _settings, _key):
        if self.applying or self.get_application().updating_wallpaper:
            return
        if self._settings_timeout:
            GLib.source_remove(self._settings_timeout)
        self._settings_timeout = GLib.idle_add(self.refresh_external_settings)

    def refresh_external_settings(self):
        self._settings_timeout = 0
        latest = self.read_settings()
        config = load_config(latest)
        self.accept_applied_state(latest, config)
        return GLib.SOURCE_REMOVE

    def on_mode_changed(self, *_args):
        self.selected_key = "picture-uri-dark" if self.mode_dropdown.get_selected() == 1 else "picture-uri"
        self.render_draft()

    def on_monitor_mode_changed(self, *_args):
        if self.refreshing:
            return
        self.config_draft["enabled"] = self.monitor_switch.get_active()
        if self.config_draft["enabled"]:
            ensure_monitor_images(self.config_draft, self.monitor_specs)
        else:
            self.draft.update(self.config_draft["single"])
        self.error_message = ""
        self.render_draft()

    def on_border_changed(self, *_args):
        if self.refreshing:
            return
        index = self.border_dropdown.get_selected()
        if index < len(BORDERS):
            self.config_draft["border"] = BORDERS[index][1]
            self.error_message = ""
            self.render_draft()

    def on_alignment_changed(self, *_args):
        if not self.refreshing:
            index = self.alignment_dropdown.get_selected()
            if index < len(ALIGNMENT_CHOICES):
                self.config_draft["alignment"] = ALIGNMENT_CHOICES[index][1]
                self.error_message = ""
                self.render_draft()

    def on_auto_changed(self, *_args):
        if not self.refreshing:
            self.config_draft["auto_rebuild"] = self.auto_switch.get_active()
            self.render_draft()

    def create_image_dialog(self, current_uri, raster_only=False):
        dialog = Gtk.FileDialog(title="Choose a wallpaper image")
        image_filter = Gtk.FileFilter()
        image_filter.set_name("Supported images" if raster_only else "Images")
        if raster_only:
            for mime_type in ("image/png", "image/jpeg", "image/webp", "image/gif",
                              "image/bmp", "image/tiff"):
                image_filter.add_mime_type(mime_type)
        else:
            image_filter.add_mime_type("image/*")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(image_filter)
        dialog.set_filters(filters)
        current = file_from_uri(current_uri)
        if current and os.path.isfile(current):
            dialog.set_initial_file(Gio.File.new_for_path(current))
        return dialog

    def on_choose_image(self, _button):
        key = self.selected_key
        dialog = self.create_image_dialog(self.config_draft["single"][key])
        dialog.open(self, None, lambda d, r: self.on_image_chosen(d, r, key))

    def on_image_chosen(self, dialog, result, key):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self.stage_file(file, key)

    def on_choose_monitor_image(self, _button, connector):
        key = self.selected_key
        current_uri = self.config_draft["images"][key].get(connector, "")
        dialog = self.create_image_dialog(current_uri, raster_only=True)
        dialog.open(self, None, lambda d, r: self.on_monitor_image_chosen(d, r, key, connector))

    def on_monitor_image_chosen(self, dialog, result, key, connector):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self.stage_file(file, key, connector)

    def stage_file(self, file, key, connector=None):
        try:
            if not file.is_native() or not file.get_path():
                raise ValueError("Choose an image stored on this computer.")
            uri = image_uri_from_file(file.get_path())
            if connector is None:
                self.draft[key] = uri
                self.config_draft["single"][key] = uri
            else:
                self.config_draft["images"][key][connector] = uri
            self.error_message = ""
            self.render_draft()
            return True
        except (OSError, ValueError, GLib.Error) as error:
            self.show_error(str(error))
            return False

    def add_drop_target(self, widget, handler, *args):
        target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        target.set_gtypes([Gdk.FileList, Gio.File])
        target.connect("drop", handler, *args)
        widget.add_controller(target)
        return target

    def drop_file(self, value, connector=None):
        files = value.get_files() if isinstance(value, Gdk.FileList) else [value]
        if len(files) != 1 or not isinstance(files[0], Gio.File):
            self.show_error("Drop one image at a time.")
            return False
        return self.stage_file(files[0], self.selected_key, connector)

    def on_preview_drop(self, _target, value, x, y):
        connector = None
        if self.config_draft["enabled"]:
            connector = self.preview.monitor_at(x, y)
            if connector is None:
                self.show_error("Drop the image onto a numbered monitor or its row below.")
                return False
        return self.drop_file(value, connector)

    def on_image_row_drop(self, _target, value, _x, _y):
        return self.drop_file(value)

    def on_monitor_row_drop(self, _target, value, _x, _y, connector):
        return self.drop_file(value, connector)

    def on_identify(self, *_args):
        self.close_identification()
        for number in range(self.monitor_model.get_n_items()):
            monitor = self.monitor_model.get_item(number)
            if not monitor.is_valid():
                continue
            window = Gtk.Window(application=self.get_application(),
                                transient_for=self, decorated=False,
                                title=f"Monitor {number + 1}")
            window.add_css_class("display-identification")
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                          halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            number_label = Gtk.Label(label=str(number + 1))
            number_label.add_css_class("display-number")
            box.append(number_label)
            box.append(Gtk.Label(label=monitor.get_connector() or f"Monitor {number + 1}"))
            box.append(Gtk.Label(label="Closes in 5 seconds. Press Esc or click to close now."))
            window.set_child(box)
            key_controller = Gtk.EventControllerKey()
            key_controller.connect("key-pressed", self.on_identify_key)
            window.add_controller(key_controller)
            click = Gtk.GestureClick()
            click.connect("released", lambda *_args: self.close_identification())
            window.add_controller(click)
            self._identify_windows.append(window)
            window.fullscreen_on_monitor(monitor)
            window.present()
        self._identify_timeout = GLib.timeout_add(5000, self.identify_timeout)

    def on_identify_key(self, _controller, keyval, _keycode, _state):
        if keyval == Gdk.KEY_Escape:
            self.close_identification()
            return True
        return False

    def identify_timeout(self):
        self._identify_timeout = 0
        self.close_identification()
        return GLib.SOURCE_REMOVE

    def close_identification(self):
        if self._identify_timeout:
            GLib.source_remove(self._identify_timeout)
            self._identify_timeout = 0
        for window in self._identify_windows:
            window.destroy()
        self._identify_windows = []

    def on_copy_image(self, _button):
        other_key = "picture-uri" if self.selected_key == "picture-uri-dark" else "picture-uri-dark"
        if self.config_draft["enabled"]:
            self.config_draft["images"][other_key] = self.config_draft["images"][self.selected_key].copy()
        else:
            uri = self.config_draft["single"][self.selected_key]
            self.draft[other_key] = uri
            self.config_draft["single"][other_key] = uri
        self.render_draft()

    def stage_image_for_both(self, uri):
        self.config_draft["enabled"] = False
        for key in PICTURE_KEYS:
            self.draft[key] = uri
            self.config_draft["single"][key] = uri
        self.draft["picture-options"] = self.config_draft["single"]["picture-options"]
        self.layout_dirty = False
        self.render_draft()

    def on_placement_changed(self, *_args):
        if not self.refreshing:
            index = self.placement_dropdown.get_selected()
            options = PLACEMENTS[:-1] if self.config_draft["enabled"] else PLACEMENTS
            if index < len(options):
                if self.config_draft["enabled"]:
                    self.config_draft["placement"] = options[index][1]
                else:
                    self.draft["picture-options"] = options[index][1]
                    self.config_draft["single"]["picture-options"] = options[index][1]
                self.render_draft()

    def on_color_changed(self, *_args):
        if self.refreshing:
            return
        color = self.color_button.get_rgba()
        value = "#{:04x}{:04x}{:04x}".format(
            round(color.red * 65535), round(color.green * 65535), round(color.blue * 65535))
        self.draft["primary-color"] = value
        self.draft["secondary-color"] = value
        self.draft["color-shading-type"] = "solid"
        if self.config_draft.get("border", 0.0) == 0:
            placement = (self.config_draft["placement"]
                         if self.config_draft["enabled"] else
                         self.draft["picture-options"])
            uri = (self.config_draft["images"][self.selected_key].get(
                       self.monitor_specs[0].connector, "")
                   if self.config_draft["enabled"] and self.monitor_specs else
                   self.draft[self.selected_key])
            if self.background_is_hidden(uri, placement):
                if not self.config_draft["enabled"]:
                    for key in (*PICTURE_KEYS, "picture-options"):
                        self.config_draft["single"][key] = self.draft[key]
                self.config_draft["border"] = 0.06
        self.render_draft()

    def stage_visible_border(self):
        self.config_draft["border"] = 0.06
        self.render_draft()

    def on_revert(self, _button):
        self.reset_saved()

    def on_about(self, _button):
        about = Adw.AboutWindow(
            transient_for=self,
            modal=True,
            application_name="Wallpaper Controls",
            application_icon=APP_ID,
            developer_name="NC4WD",
            version=APP_VERSION,
            website=PROJECT_URL,
            license_type=Gtk.License.CUSTOM,
            license="GNU General Public License, version 3 or later",
        )
        about.present()

    def on_close_request(self, _window):
        if self._force_close or not self.has_changes():
            return False
        if self._close_dialog_open:
            return True
        self._close_dialog_open = True
        dialog = Adw.MessageDialog.new(
            self, "Discard your changes?", "Your changes haven't been applied to the desktop.")
        dialog.add_response("keep", "Keep Editing")
        dialog.add_response("discard", "Discard Changes")
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.set_response_appearance("discard", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self.on_close_response)
        dialog.present()
        return True

    def on_close_response(self, _dialog, response):
        self._close_dialog_open = False
        if response == "discard":
            self._force_close = True
            self.close()

    def on_apply(self, _button):
        if not self.has_changes():
            return
        self.applying = True
        try:
            values, config = apply_wallpaper(
                self.settings, self.monitor_specs, self.draft, self.config_draft,
                sync=Gio.Settings.sync)
        except (OSError, ValueError, GLib.Error, MemoryError) as error:
            self.show_error(str(error))
            return
        finally:
            self.applying = False
        self.reset_saved(values, config)
        self.get_application().update_background_lifetime()

    def on_undo(self, *_args):
        if self.has_changes():
            self.show_error("Apply or Discard Changes before restoring your previous wallpaper.")
            return
        self.applying = True
        try:
            values, config = undo_last_apply(self.settings, self.monitor_specs,
                                             sync=Gio.Settings.sync)
        except (OSError, ValueError, GLib.Error, MemoryError) as error:
            self.show_error(str(error))
            return
        finally:
            self.applying = False
        self.reset_saved(values, config)
        self.get_application().update_background_lifetime()

    def on_unrealize(self, *_args):
        self.close_identification()
        if self._settings_timeout:
            GLib.source_remove(self._settings_timeout)
            self._settings_timeout = 0
        if self._settings_handler:
            self.settings.disconnect(self._settings_handler)
            self._settings_handler = 0


class WallpaperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.updating_wallpaper = False
        self.background_held = False
        self._layout_timeout = 0
        self._state_timeout = 0
        self._monitor_signals = []
        self._stopped = False
        self._desktop_handler = 0
        self._model_handler = 0

    def do_startup(self):
        Adw.Application.do_startup(self)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_args: self.quit())
        self.add_action(quit_action)
        self.desktop_settings = Gio.Settings.new(BACKGROUND_SCHEMA)
        self._desktop_handler = self.desktop_settings.connect("changed", self.on_desktop_settings_changed)
        self.monitor_model = Gdk.Display.get_default().get_monitors()
        self._model_handler = self.monitor_model.connect("items-changed", self.on_display_event)
        self.connect_display_signals()
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b".display-identification { background: #242424; color: white; }"
            b".display-number { font-size: 96px; font-weight: bold; }")
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.update_background_lifetime()

    def main_window(self):
        return next((window for window in self.get_windows()
                     if isinstance(window, WallpaperWindow)), None)

    def connect_display_signals(self):
        for monitor, handler in self._monitor_signals:
            monitor.disconnect(handler)
        self._monitor_signals = []
        for index in range(self.monitor_model.get_n_items()):
            monitor = self.monitor_model.get_item(index)
            for prop in ("geometry", "scale-factor", "scale"):
                if monitor.find_property(prop):
                    handler = monitor.connect(f"notify::{prop}", self.on_display_event)
                    self._monitor_signals.append((monitor, handler))

    def on_display_event(self, *_args):
        if self._stopped:
            return
        self.connect_display_signals()
        window = self.main_window()
        if window:
            window.on_monitors_changed()
        self.schedule_layout_rebuild()

    def schedule_layout_rebuild(self):
        if self._layout_timeout:
            GLib.source_remove(self._layout_timeout)
        # A display change often emits geometry and scale updates separately.
        self._layout_timeout = GLib.timeout_add(1200, self.rebuild_applied_layout)

    def rebuild_applied_layout(self):
        self._layout_timeout = 0
        self.updating_wallpaper = True
        try:
            result = rebuild_for_layout(
                self.desktop_settings, monitors_from_display(Gdk.Display.get_default()),
                sync=Gio.Settings.sync)
            window = self.main_window()
            if result and window:
                window.accept_applied_state(*result)
        except (OSError, ValueError, GLib.Error, MemoryError) as error:
            window = self.main_window()
            if window:
                window.show_error(f"Couldn't adjust the wallpaper for your monitors. {error}")
            else:
                print(f"Wallpaper Controls: {error}", file=sys.stderr)
        finally:
            self.updating_wallpaper = False
        return GLib.SOURCE_REMOVE

    def on_desktop_settings_changed(self, *_args):
        if self.updating_wallpaper or self._stopped:
            return
        if self._state_timeout:
            GLib.source_remove(self._state_timeout)
        self._state_timeout = GLib.idle_add(self.refresh_background_state)

    def refresh_background_state(self):
        self._state_timeout = 0
        self.update_background_lifetime()
        return GLib.SOURCE_REMOVE

    def update_background_lifetime(self):
        values = {key: self.desktop_settings.get_string(key) for key in EDITABLE_KEYS}
        config = load_config(values)
        enabled = config["auto_rebuild"] and uses_generated_wallpaper(config)
        if enabled and not self.background_held:
            self.hold()
            self.background_held = True
            self.schedule_layout_rebuild()
        elif not enabled and self.background_held:
            self.release()
            self.background_held = False
        try:
            sync_autostart(config)
        except OSError as error:
            window = self.main_window()
            message = ("Your wallpaper was saved, but automatic monitor adjustments couldn't "
                       f"be enabled at login. {error}")
            if window:
                window.show_error(message)
            else:
                print(message, file=sys.stderr)

    def do_shutdown(self):
        if self._stopped:
            return
        self._stopped = True
        for timer in (self._layout_timeout, self._state_timeout):
            if timer and GLib.MainContext.default().find_source_by_id(timer):
                GLib.source_remove(timer)
        self._layout_timeout = self._state_timeout = 0
        for monitor, handler in self._monitor_signals:
            monitor.disconnect(handler)
        self._monitor_signals = []
        if self._desktop_handler:
            self.desktop_settings.disconnect(self._desktop_handler)
            self._desktop_handler = 0
        if self._model_handler:
            self.monitor_model.disconnect(self._model_handler)
            self._model_handler = 0
        Adw.Application.do_shutdown(self)

    def do_activate(self):
        window = self.main_window()
        if window is None:
            window = WallpaperWindow(self)
        window.present()

    def do_command_line(self, command_line):
        args = [arg.decode() if isinstance(arg, bytes) else arg
                for arg in command_line.get_arguments()]
        if len(args) == 1:
            self.activate()
            return 0
        if len(args) == 2 and args[1] == "--watch-displays":
            self.update_background_lifetime()
            return 0
        if len(args) == 2 and args[1] in ("--version", "-V"):
            command_line.print_literal(f"Wallpaper Controls {APP_VERSION}\n")
            return 0
        if len(args) == 2 and args[1] in ("--help", "-h"):
            command_line.print_literal(
                "Usage: wallpaper-controls [--set-wallpaper IMAGE] [--show-background-color]\n"
                "Choose wallpaper images and placement for GNOME.\n")
            return 0
        if len(args) == 2 and args[1] == "--show-background-color":
            self.activate()
            self.main_window().stage_visible_border()
            return 0
        if len(args) == 3 and args[1] == "--set-wallpaper":
            try:
                file = command_line.create_file_for_arg(args[2])
                uri = image_uri_from_file(file.get_path())
            except (OSError, ValueError, GLib.Error) as error:
                command_line.printerr_literal(f"wallpaper-controls: {error}\n")
                return 1
            self.activate()
            self.main_window().stage_image_for_both(uri)
            return 0
        command_line.printerr_literal(
            "Usage: wallpaper-controls [--set-wallpaper IMAGE] [--show-background-color]\n")
        return 2


def main(argv=None):
    arguments = sys.argv if argv is None else argv
    if len(arguments) == 2 and arguments[1] == "--quit":
        stop_running_app()
        return 0
    if len(arguments) == 2 and arguments[1] in ("--version", "-V"):
        print(f"Wallpaper Controls {APP_VERSION}")
        return 0
    if len(arguments) == 2 and arguments[1] in ("--help", "-h"):
        print("Usage: wallpaper-controls [--set-wallpaper IMAGE] [--show-background-color]")
        print("Choose wallpaper images and placement for GNOME.")
        return 0
    valid_command = (len(arguments) == 3 and arguments[1] == "--set-wallpaper") or (
        len(arguments) == 2 and arguments[1] in ("--show-background-color", "--watch-displays"))
    if len(arguments) > 1 and not valid_command:
        print("Usage: wallpaper-controls [--set-wallpaper IMAGE] [--show-background-color]",
              file=sys.stderr)
        return 2
    return WallpaperApp().run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
