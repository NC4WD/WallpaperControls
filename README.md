# Wallpaper Controls

Wallpaper Controls is a small GTK4/libadwaita app for Ubuntu and other GNOME
desktops. It restores the wallpaper placement choices missing from recent
settings panels and shows a preview before anything changes.

![Wallpaper Controls preview and Apply button](assets/screenshots/main.png)

## Features

- Fill, Fit, Stretch, Center, Tile, and Span Displays
- Separate wallpaper images for Light and Dark appearance
- A background color and adjustable border size, including for images that match the screen shape
- A different image on each connected monitor, composed into a single spanned wallpaper
- **Apply** and **Revert** controls so edits do not immediately change your desktop
- **Undo Last Apply** to restore the previous desktop, even after reopening the app
- Image alignment to keep a subject visible when an image is cropped
- Numbered display identification and automatic rebuilding when display arrangements change
- Drag and drop from Files onto the preview or a monitor row
- **Open With → Set as Wallpaper** for images in Files

## Install on Ubuntu

Install the system packages:

```sh
sudo apt install python3-gi python3-pil gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0
```

From this folder, run:

```sh
./install.sh
```

Find **Wallpaper Controls** in the app launcher. The installer works in your
user account and does not require `sudo`. You can also run `./run.sh` without
installing. To remove the app, run `./uninstall.sh`; it keeps your wallpaper
images and preferences so your current desktop image does not disappear.

## How to use it

Choose **Light** or **Dark**, select an image, and adjust its placement. The
preview updates while GNOME's wallpaper stays unchanged. Press **Apply** when
you are happy with the result, or **Revert** to discard the edits. **Copy this
image to Dark/Light** copies the selected image to the other appearance when
you apply. The background color fills space left around the image. Choose a
Small, Medium, or Large **Border size** when you want the color to remain
visible even if the image already matches or fills the screen. When you choose
a color while the image covers the display, the app selects Medium for you.

Use **Image alignment** to choose which edge or corner stays visible with Fill,
Fit, Center, or Span. Alignment and placement apply to both appearances and to
every monitor. The preview uses the same renderer as generated wallpapers.

Drop one image from Files onto the preview or Image row to change the selected
appearance. In per-monitor mode, drop onto a numbered display in the preview or
its monitor row. Drops stay in the preview until you press **Apply**.

Open the menu in the title bar and choose **Undo Last Apply** to restore the
previous wallpaper, placement, color, and app preferences. Undo is available
after Apply and survives reopening the app. Apply or Revert any pending edits
first. A wallpaper change made outside the app clears Undo so it cannot
accidentally overwrite another app's choices.

For separate images on each monitor, turn on **Different image on each
monitor** and choose an image in each connected monitor row. Repeat for the
other appearance if you want different Light and Dark sets. The same placement
choice applies inside every monitor. Press **Apply** to generate and use the
combined wallpaper.

Choose **Identify Displays** to show each display's number and connector for
five seconds. Press Escape or click a label to dismiss them sooner.

**Keep wallpapers aligned** automatically rebuilds the last applied images
when the display arrangement or scale changes. It applies to generated
wallpapers (per-monitor images, borders, or custom alignment). A lightweight
helper stays running after the window closes and starts at login. Turn this
switch off and press **Apply** to stop the helper and remove its login entry.
New displays inherit a saved image; images for unplugged displays are kept for
their return. Pending image or color edits are never applied by the helper.

The file-manager action opens Wallpaper Controls with the selected image staged
for both appearances. You still need to press **Apply**.

## Where files go

The app stores per-monitor choices in
`~/.config/wallpaper-controls/monitors.json` and generated wallpapers in
`~/.local/share/wallpaper-controls/generated/`, using the corresponding XDG
locations when those variables are set. It does not upload images or use the
network.
The configuration also keeps a single Undo snapshot. When automatic rebuilding
is enabled for a generated wallpaper, its login entry is stored in
`~/.config/autostart/io.github.nc4wd.WallpaperControls.desktop`.

## Current limits

- GNOME exposes one wallpaper URI for Light and one for Dark. Per-monitor mode
  combines the chosen images into one PNG and uses GNOME's Span Displays mode.
- Mirrored displays cannot show different wallpapers.
- With automatic rebuilding disabled, reopen the app and press **Apply**
  after changing the display arrangement.
- The single-image preview uses the first connected display's size.
- Per-monitor composition uses Pillow's supported raster image formats. PNG,
  JPEG, WebP, GIF, BMP, and TIFF are supported on typical Ubuntu installations;
  SVG uses GTK's image decoder. GNOME slideshow XML files cannot be composed.

## Development and release

Run `/usr/bin/python3 -m pytest -q` to check image composition, saved preferences,
and Undo. GTK integration checks run when a display is available; use
`xvfb-run -a env GSETTINGS_BACKEND=memory /usr/bin/python3 -m pytest -q`
to run all checks on a virtual display. See
[RELEASING.md](RELEASING.md) for the public release process and current Flathub
constraints. The project is licensed under
[GPL-3.0-or-later](LICENSE).
