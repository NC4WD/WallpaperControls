#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Small GTK front end for GNOME's wallpaper settings."""

import math
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

from monitor_wallpaper import bounds, layout_signature, monitors_from_display, render_composite
from monitor_state import (PICTURE_KEYS, clean_old_wallpapers, cloned,
                           generate_wallpapers, load_config, save_config)


APP_ID = "io.github.nc4wd.WallpaperControls"
APP_VERSION = "0.1.0"
PROJECT_URL = "https://github.com/NC4WD/WallpaperControls"
BACKGROUND_SCHEMA = "org.gnome.desktop.background"
PLACEMENTS = (
    ("Fill Screen", "zoom"),
    ("Fit Screen", "scaled"),
    ("Stretch", "stretched"),
    ("Center", "centered"),
    ("Tile", "wallpaper"),
    ("Span Displays", "spanned"),
)
PLACEMENT_KEYS = [value for _, value in PLACEMENTS]
EDITABLE_KEYS = (
    "picture-uri", "picture-uri-dark", "picture-options",
    "primary-color", "secondary-color", "color-shading-type",
)


def active_wallpaper_key():
    appearance = Gio.Settings.new("org.gnome.desktop.interface")
    return "picture-uri-dark" if appearance.get_string("color-scheme") == "prefer-dark" else "picture-uri"


def image_uri_from_file(filename):
    path = Path(filename).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("Choose an image file.")
    if not Gio.content_type_is_a(Gio.content_type_guess(str(path), None)[0], "image/*"):
        raise ValueError("The selected file is not an image.")
    return Gio.File.new_for_path(str(path)).get_uri()


def file_from_uri(uri):
    if not uri:
        return None
    file = Gio.File.new_for_uri(uri)
    return file.get_path() if file.is_native() else None


class WallpaperPreview(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_content_width(720)
        self.set_content_height(360)
        self.set_hexpand(True)
        self.set_vexpand(False)
        self.set_draw_func(self.draw)
        self.pixbuf = None
        self.composite_pixbuf = None
        self.composite_monitors = []
        self.image_width = 0
        self.image_height = 0
        self.placeholder_label = "Choose an image to preview"
        self.placement = "zoom"
        self.color = Gdk.RGBA()
        self.color.parse("#000000")

    def update(self, uri, placement, color):
        self.pixbuf = None
        self.composite_pixbuf = None
        self.composite_monitors = []
        self.image_width = self.image_height = 0
        self.placement = placement
        self.color = color
        self.placeholder_label = "Preview unavailable" if uri else "Choose an image to preview"
        path = file_from_uri(uri)
        if path and os.path.isfile(path):
            try:
                _, self.image_width, self.image_height = GdkPixbuf.Pixbuf.get_file_info(path)
                self.pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 1920, 1080, True)
                if self.image_width <= 0 or self.image_height <= 0:
                    self.image_width = self.pixbuf.get_width()
                    self.image_height = self.pixbuf.get_height()
            except (GLib.Error, TypeError, ValueError):
                pass
        self.queue_draw()

    def update_composite(self, image, monitors):
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        loader = GdkPixbuf.PixbufLoader.new_with_type("png")
        loader.write(buffer.getvalue())
        loader.close()
        self.composite_pixbuf = loader.get_pixbuf()
        self.pixbuf = self.composite_pixbuf
        self.composite_monitors = monitors
        self.queue_draw()

    def paint_image(self, cr, x, y, width, height):
        if not self.pixbuf or width <= 0 or height <= 0:
            return
        cr.save()
        cr.translate(x, y)
        cr.scale(width / self.pixbuf.get_width(), height / self.pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, self.pixbuf, 0, 0)
        cr.paint()
        cr.restore()

    def draw(self, _area, cr, width, height):
        # The frame is a 16:9 desktop. Image placement uses a 1920x1080
        # reference so Center and Tile retain their natural pixel sizes.
        margin = 18
        frame_width = max(width - margin * 2, 1)
        ratio = (self.composite_pixbuf.get_width() / self.composite_pixbuf.get_height()
                 if self.composite_pixbuf else 16 / 9)
        frame_height = min(max(height - margin * 2, 1), frame_width / ratio)
        frame_width = min(frame_width, frame_height * ratio)
        x0 = (width - frame_width) / 2
        y0 = (height - frame_height) / 2
        cr.set_source_rgba(0, 0, 0, 0.13)
        cr.rectangle(x0 + 3, y0 + 7, frame_width, frame_height)
        cr.fill()
        cr.save()
        cr.rectangle(x0, y0, frame_width, frame_height)
        cr.clip()
        cr.set_source_rgb(self.color.red, self.color.green, self.color.blue)
        cr.paint()
        if self.composite_pixbuf:
            self.paint_image(cr, x0, y0, frame_width, frame_height)
            left, top, logical_width, logical_height = bounds(self.composite_monitors)
            for monitor in self.composite_monitors:
                mx = x0 + (monitor.x - left) * frame_width / logical_width
                my = y0 + (monitor.y - top) * frame_height / logical_height
                mw = monitor.width * frame_width / logical_width
                mh = monitor.height * frame_height / logical_height
                cr.set_source_rgba(1, 1, 1, 0.75)
                cr.set_line_width(1.5)
                cr.rectangle(mx + 1, my + 1, mw - 2, mh - 2)
                cr.stroke()
                cr.set_source_rgba(0, 0, 0, 0.7)
                cr.rectangle(mx + 7, my + 7, min(mw - 14, 110), 23)
                cr.fill()
                cr.set_source_rgb(1, 1, 1)
                cr.select_font_face("Sans", 0, 0)
                cr.set_font_size(12)
                cr.move_to(mx + 13, my + 23)
                cr.show_text(monitor.connector[:14])
        elif self.pixbuf and self.image_width and self.image_height:
            iw, ih = self.image_width, self.image_height
            vw, vh = 1920, 1080
            sx, sy = frame_width / vw, frame_height / vh
            if self.placement == "stretched":
                self.paint_image(cr, x0, y0, frame_width, frame_height)
            elif self.placement == "wallpaper":
                tw, th = iw * sx, ih * sy
                # Tiny tiles can be drawn too densely to distinguish here.
                tw, th = max(tw, 8), max(th, 8)
                for row in range(min(math.ceil(frame_height / th), 100)):
                    for col in range(min(math.ceil(frame_width / tw), 100)):
                        self.paint_image(cr, x0 + col * tw, y0 + row * th, tw, th)
            else:
                if self.placement == "centered":
                    scale = 1.0
                elif self.placement == "scaled":
                    scale = min(vw / iw, vh / ih)
                else:  # zoom and spanned are both cropped to fill this frame.
                    scale = max(vw / iw, vh / ih)
                dw, dh = iw * scale * sx, ih * scale * sy
                self.paint_image(cr, x0 + (frame_width - dw) / 2,
                                 y0 + (frame_height - dh) / 2, dw, dh)
        else:
            cr.set_source_rgba(1, 1, 1, 0.8 if self.color.red < 0.5 else 0.7)
            cr.select_font_face("Sans", 0, 0)
            cr.set_font_size(16)
            label = self.placeholder_label
            extents = cr.text_extents(label)
            cr.move_to(x0 + (frame_width - extents.width) / 2,
                       y0 + frame_height / 2)
            cr.show_text(label)
        cr.restore()
        cr.set_source_rgba(1, 1, 1, 0.22)
        cr.set_line_width(1)
        cr.rectangle(x0 + 0.5, y0 + 0.5, frame_width - 1, frame_height - 1)
        cr.stroke()


class WallpaperWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Wallpaper Controls")
        self.set_default_size(830, 750)
        self.settings = Gio.Settings.new(BACKGROUND_SCHEMA)
        self.selected_key = active_wallpaper_key()
        self.refreshing = False
        self.applying = False
        self.saved = self.read_settings()
        self.draft = self.saved.copy()
        self.config_saved = load_config(self.saved)
        self.config_draft = cloned(self.config_saved)
        self.monitor_model = Gdk.Display.get_default().get_monitors()
        self.monitor_specs = monitors_from_display(Gdk.Display.get_default())
        self.layout_dirty = (self.config_saved["enabled"] and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.placement_mode_is_multi = False
        self._monitor_signal_handles = []
        self._force_close = False
        self._close_dialog_open = False

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self.revert_button = Gtk.Button(label="Revert")
        self.revert_button.connect("clicked", self.on_revert)
        header.pack_start(self.revert_button)
        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self.on_apply)
        header.pack_end(self.apply_button)
        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic")
        about_button.set_tooltip_text("About Wallpaper Controls")
        about_button.connect("clicked", self.on_about)
        header.pack_end(about_button)
        toolbar.add_top_bar(header)
        self.set_content(toolbar)
        self.connect("close-request", self.on_close_request)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        toolbar.set_content(scroll)
        clamp = Adw.Clamp()
        clamp.set_maximum_size(760)
        clamp.set_tightening_threshold(620)
        scroll.set_child(clamp)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content.set_margin_top(22)
        content.set_margin_bottom(30)
        content.set_margin_start(18)
        content.set_margin_end(18)
        clamp.set_child(content)

        self.preview = WallpaperPreview()
        preview_frame = Gtk.Frame()
        preview_frame.add_css_class("card")
        preview_frame.set_child(self.preview)
        content.append(preview_frame)
        self.hint = Gtk.Label(label="Preview your changes, then press Apply.")
        self.hint.set_halign(Gtk.Align.START)
        self.hint.set_wrap(True)
        self.hint.add_css_class("dim-label")
        content.append(self.hint)

        image_group = Adw.PreferencesGroup(title="Wallpaper")
        content.append(image_group)
        mode_row = Adw.ActionRow(title="Appearance", subtitle="Choose which wallpaper to edit")
        self.mode_dropdown = Gtk.DropDown.new_from_strings(["Light", "Dark"])
        self.mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.mode_dropdown.set_selected(1 if self.selected_key == "picture-uri-dark" else 0)
        self.mode_dropdown.connect("notify::selected", self.on_mode_changed)
        mode_row.add_suffix(self.mode_dropdown)
        mode_row.set_activatable_widget(self.mode_dropdown)
        image_group.add(mode_row)

        monitor_mode_row = Adw.ActionRow(
            title="Different image on each monitor",
            subtitle="Combines your choices into a wallpaper that spans your displays")
        self.monitor_switch = Gtk.Switch()
        self.monitor_switch.set_valign(Gtk.Align.CENTER)
        self.monitor_switch.set_active(self.config_draft["enabled"])
        self.monitor_switch.connect("notify::active", self.on_monitor_mode_changed)
        monitor_mode_row.add_suffix(self.monitor_switch)
        monitor_mode_row.set_activatable_widget(self.monitor_switch)
        image_group.add(monitor_mode_row)

        self.image_row = Adw.ActionRow(title="Image")
        choose_button = Gtk.Button(label="Choose Image…")
        choose_button.set_valign(Gtk.Align.CENTER)
        choose_button.connect("clicked", self.on_choose_image)
        self.image_row.add_suffix(choose_button)
        self.image_row.set_activatable_widget(choose_button)
        image_group.add(self.image_row)

        self.copy_row = Adw.ActionRow(
            subtitle="Copies the selected image to the other appearance when you apply")
        self.copy_button = Gtk.Button(label="Copy")
        self.copy_button.set_valign(Gtk.Align.CENTER)
        self.copy_button.connect("clicked", self.on_copy_image)
        self.copy_row.add_suffix(self.copy_button)
        image_group.add(self.copy_row)

        self.monitors_group = Adw.PreferencesGroup(title="Connected monitors")
        content.append(self.monitors_group)
        self.monitor_rows = []
        self.rebuild_monitor_rows()

        placement_group = Adw.PreferencesGroup(title="Placement and borders")
        content.append(placement_group)
        placement_row = Adw.ActionRow(title="Placement")
        self.placement_dropdown = Gtk.DropDown.new_from_strings([label for label, _ in PLACEMENTS])
        self.placement_dropdown.set_valign(Gtk.Align.CENTER)
        self.placement_dropdown.connect("notify::selected", self.on_placement_changed)
        placement_row.add_suffix(self.placement_dropdown)
        placement_row.set_activatable_widget(self.placement_dropdown)
        placement_group.add(placement_row)

        color_row = Adw.ActionRow(title="Border color",
                                  subtitle="Visible with Fit, Center, and some tiled images")
        self.color_button = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog())
        self.color_button.set_valign(Gtk.Align.CENTER)
        self.color_button.connect("notify::rgba", self.on_color_changed)
        color_row.add_suffix(self.color_button)
        color_row.set_activatable_widget(self.color_button)
        placement_group.add(color_row)

        self.settings.connect("changed", self.on_settings_changed)
        self.monitor_model.connect("items-changed", self.on_monitors_changed)
        self.connect_monitor_signals()
        self.render_draft()

    def read_settings(self):
        return {key: self.settings.get_string(key) for key in EDITABLE_KEYS}

    def has_changes(self):
        return (self.draft != self.saved or self.config_draft != self.config_saved
                or self.layout_dirty)

    def rebuild_monitor_rows(self):
        for row in self.monitor_rows:
            self.monitors_group.remove(row)
        self.monitor_rows = []
        for monitor in self.monitor_specs:
            row = Adw.ActionRow(title=monitor.label)
            button = Gtk.Button(label="Choose Image…")
            button.set_valign(Gtk.Align.CENTER)
            button.connect("clicked", self.on_choose_monitor_image, monitor.connector)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            self.monitors_group.add(row)
            self.monitor_rows.append(row)

    def connect_monitor_signals(self):
        for monitor, handler in self._monitor_signal_handles:
            monitor.disconnect(handler)
        self._monitor_signal_handles = []
        for index in range(self.monitor_model.get_n_items()):
            monitor = self.monitor_model.get_item(index)
            for signal in ("notify::geometry", "notify::scale-factor"):
                handler = monitor.connect(signal, self.on_monitors_changed)
                self._monitor_signal_handles.append((monitor, handler))

    def on_monitors_changed(self, *_args):
        self.monitor_specs = monitors_from_display(Gdk.Display.get_default())
        self.connect_monitor_signals()
        self.rebuild_monitor_rows()
        self.layout_dirty = (self.config_draft["enabled"] and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.render_draft()

    def render_draft(self):
        self.refreshing = True
        multi = self.config_draft["enabled"]
        self.monitor_switch.set_active(multi)
        self.image_row.set_visible(not multi)
        self.monitors_group.set_visible(multi)
        uri = self.draft[self.selected_key]
        path = file_from_uri(uri)
        self.image_row.set_subtitle(Path(path).name if path else
                                    ("No image selected" if not uri else uri))
        destination = "Dark" if self.selected_key == "picture-uri" else "Light"
        if multi:
            self.copy_row.set_title(f"Copy all monitor images to {destination}")
            self.copy_row.set_subtitle("Copies every monitor's image to the other appearance when you apply")
            image_map = self.config_draft["images"][self.selected_key]
            self.copy_button.set_sensitive(any(image_map.values()))
        else:
            self.copy_row.set_title(f"Copy this image to {destination}")
            self.copy_row.set_subtitle("Copies this image to the other appearance when you apply")
            self.copy_button.set_sensitive(bool(uri))
        if multi != self.placement_mode_is_multi:
            options = PLACEMENTS[:-1] if multi else PLACEMENTS
            self.placement_dropdown.set_model(Gtk.StringList.new([label for label, _ in options]))
            self.placement_mode_is_multi = multi
        placement = self.config_draft["placement"] if multi else self.draft["picture-options"]
        options = PLACEMENT_KEYS[:-1] if multi else PLACEMENT_KEYS
        self.placement_dropdown.set_selected(options.index(placement) if placement in options else 0)
        color = Gdk.RGBA()
        if not color.parse(self.draft["primary-color"]):
            color.parse("#000000")
        self.color_button.set_rgba(color)
        if multi:
            for row, monitor in zip(self.monitor_rows, self.monitor_specs):
                monitor_uri = self.config_draft["images"][self.selected_key].get(monitor.connector, "")
                filename = Path(file_from_uri(monitor_uri)).name if file_from_uri(monitor_uri) else "No image selected"
                row.set_subtitle(f"{monitor.width} × {monitor.height} · {filename}")
            try:
                _, _, logical_width, logical_height = bounds(self.monitor_specs)
                scale = min(1.0, 720 / logical_width, 340 / logical_height)
                image = render_composite(self.monitor_specs,
                                         self.config_draft["images"][self.selected_key],
                                         placement, self.draft["primary-color"],
                                         scale=scale, allow_missing=True)
                self.preview.update_composite(image, self.monitor_specs)
                self.hint.set_text("Preview your monitor layout, then press Apply.")
            except (OSError, ValueError, GLib.Error) as error:
                self.preview.update("", "zoom", color)
                self.preview.placeholder_label = "Preview unavailable"
                self.hint.set_text(str(error))
        else:
            self.preview.update(uri, placement, color)
            self.hint.set_text("Preview your changes, then press Apply.")
        changed = self.has_changes()
        self.apply_button.set_sensitive(changed)
        self.revert_button.set_sensitive(changed)
        self.refreshing = False

    def on_settings_changed(self, _settings, _key):
        if self.applying:
            return
        latest = self.read_settings()
        if not self.has_changes():
            self.saved = latest
            self.draft = latest.copy()
            self.config_saved = load_config(latest)
            self.config_draft = cloned(self.config_saved)
            self.render_draft()
            return
        for key in EDITABLE_KEYS:
            if self.draft[key] == self.saved[key]:
                self.draft[key] = latest[key]
        self.saved = latest
        self.render_draft()

    def on_mode_changed(self, *_args):
        self.selected_key = "picture-uri-dark" if self.mode_dropdown.get_selected() == 1 else "picture-uri"
        self.render_draft()

    def on_monitor_mode_changed(self, *_args):
        if self.refreshing:
            return
        enable = self.monitor_switch.get_active()
        if enable:
            self.config_draft["single"] = {
                key: self.draft[key] for key in (*PICTURE_KEYS, "picture-options")}
            for key in PICTURE_KEYS:
                for monitor in self.monitor_specs:
                    self.config_draft["images"][key].setdefault(
                        monitor.connector, self.config_draft["single"][key])
            if self.config_saved["enabled"]:
                for key in (*PICTURE_KEYS, "picture-options"):
                    self.draft[key] = self.saved[key]
        else:
            for key in (*PICTURE_KEYS, "picture-options"):
                self.draft[key] = self.config_draft["single"][key]
        self.config_draft["enabled"] = enable
        self.layout_dirty = (enable and self.config_saved["enabled"] and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
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
        dialog = self.create_image_dialog(self.draft[key])
        dialog.open(self, None, lambda d, r: self.on_image_chosen(d, r, key))

    def on_image_chosen(self, dialog, result, key):
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        self.draft[key] = file.get_uri()
        self.config_draft["single"][key] = file.get_uri()
        self.render_draft()

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
        self.config_draft["images"][key][connector] = file.get_uri()
        self.render_draft()

    def on_copy_image(self, _button):
        other_key = "picture-uri" if self.selected_key == "picture-uri-dark" else "picture-uri-dark"
        if self.config_draft["enabled"]:
            self.config_draft["images"][other_key] = self.config_draft["images"][self.selected_key].copy()
        else:
            self.draft[other_key] = self.draft[self.selected_key]
            self.config_draft["single"][other_key] = self.draft[other_key]
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
        self.render_draft()

    def on_revert(self, _button):
        self.saved = self.read_settings()
        self.draft = self.saved.copy()
        self.config_saved = load_config(self.saved)
        self.config_draft = cloned(self.config_saved)
        self.layout_dirty = (self.config_saved["enabled"] and
                             layout_signature(self.monitor_specs) != self.config_saved["layout"])
        self.render_draft()

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
            self, "Discard changes?", "Your wallpaper changes have not been applied.")
        dialog.add_response("keep", "Keep Editing")
        dialog.add_response("discard", "Discard")
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
        next_settings = self.draft.copy()
        next_config = cloned(self.config_draft)
        try:
            if next_config["enabled"]:
                generated, signature = generate_wallpapers(
                    self.monitor_specs, next_config, next_settings["primary-color"])
                next_settings.update(generated)
                next_settings["picture-options"] = "spanned"
                next_config["generated"] = generated
                next_config["layout"] = signature
            else:
                next_settings.update(next_config["single"])
                next_config["layout"] = ""
            changes = {key: next_settings[key] for key in EDITABLE_KEYS
                       if next_settings[key] != self.saved[key]}
            for key in changes:
                if not self.settings.is_writable(key):
                    raise ValueError(f"GNOME does not allow changes to {key}.")
            save_config(next_config)
            self.applying = True
            self.settings.delay()
            for key, value in changes.items():
                if not self.settings.set_string(key, value):
                    raise ValueError(f"Could not save {key}.")
            self.settings.apply()
            Gio.Settings.sync()
        except (OSError, ValueError, GLib.Error, MemoryError) as error:
            self.settings.revert()
            self.hint.set_text(str(error))
            return
        finally:
            self.applying = False
        self.saved = self.read_settings()
        self.draft = self.saved.copy()
        self.config_saved = next_config
        self.config_draft = cloned(next_config)
        self.layout_dirty = False
        try:
            clean_old_wallpapers(next_config["generated"].values()
                                 if next_config["enabled"] else ())
        except OSError:
            pass
        self.render_draft()


class WallpaperApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def do_activate(self):
        window = self.props.active_window
        if window is None:
            window = WallpaperWindow(self)
        window.present()

    def do_command_line(self, command_line):
        args = [arg.decode() if isinstance(arg, bytes) else arg
                for arg in command_line.get_arguments()]
        if len(args) == 1:
            self.activate()
            return 0
        if len(args) == 2 and args[1] in ("--version", "-V"):
            command_line.print_literal(f"Wallpaper Controls {APP_VERSION}\n")
            return 0
        if len(args) == 2 and args[1] in ("--help", "-h"):
            command_line.print_literal(
                "Usage: wallpaper-controls [--set-wallpaper IMAGE]\n"
                "Choose wallpaper images and placement for GNOME.\n")
            return 0
        if len(args) == 3 and args[1] == "--set-wallpaper":
            try:
                file = command_line.create_file_for_arg(args[2])
                uri = image_uri_from_file(file.get_path())
            except (OSError, ValueError, GLib.Error) as error:
                command_line.printerr_literal(f"wallpaper-controls: {error}\n")
                return 1
            self.activate()
            self.props.active_window.stage_image_for_both(uri)
            return 0
        command_line.printerr_literal("Usage: wallpaper-controls [--set-wallpaper IMAGE]\n")
        return 2


def main(argv=None):
    arguments = sys.argv if argv is None else argv
    if len(arguments) == 2 and arguments[1] in ("--version", "-V"):
        print(f"Wallpaper Controls {APP_VERSION}")
        return 0
    if len(arguments) == 2 and arguments[1] in ("--help", "-h"):
        print("Usage: wallpaper-controls [--set-wallpaper IMAGE]")
        print("Choose wallpaper images and placement for GNOME.")
        return 0
    if len(arguments) > 1 and not (len(arguments) == 3 and arguments[1] == "--set-wallpaper"):
        print("Usage: wallpaper-controls [--set-wallpaper IMAGE]", file=sys.stderr)
        return 2
    return WallpaperApp().run(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
