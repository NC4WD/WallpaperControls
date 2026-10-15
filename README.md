# Wallpaper Controls

Wallpaper Controls is a small GTK4/libadwaita app for Ubuntu and other GNOME
desktops. It restores the wallpaper placement choices missing from recent
settings panels and shows a preview before anything changes.

![Wallpaper Controls preview and Apply button](assets/screenshots/main.png)

## Features

- Fill screen, Fit image, Stretch, Original size, Tile, Span monitors, and Color only
- Separate wallpaper images for light and dark mode
- A background color and adjustable border size, including for images that match the screen shape
- A different image on each connected monitor, composed into a single spanned wallpaper
- **Apply** and **Discard Changes** controls so edits do not immediately change your desktop
- **Restore Previous Wallpaper** to restore the previous desktop, even after reopening the app
- Image position to keep a subject visible when an image is cropped
- Numbered display identification and automatic rebuilding when display arrangements change
- Drag and drop from Files onto the preview or a monitor row
- **Open With → Set as Wallpaper** for images in Files

## Install on Ubuntu

Requires **Ubuntu 24.04 or newer with GNOME**, or another GNOME system with
GTK 4.10 and libadwaita 1.4 or newer. Ubuntu 22.04's standard libraries are too
old. The installer checks these requirements before copying any files.

### Install the Ubuntu package

Download the `.deb` from the [latest GitHub release](https://github.com/NC4WD/WallpaperControls/releases/latest) and install it from the folder where
you saved it:

```sh
sudo apt install ./wallpaper-controls_0.2.0-1_all.deb
```

Ubuntu installs the required libraries. Future updates use the same command
with the new file; a download from GitHub does not enable automatic updates.
Choose **Quit** and reopen the app after updating.

If you previously used `./install.sh`, apply or discard your pending edits,
choose **Quit**, and run `./uninstall.sh` from your source folder first. This
removes the old user launcher so it cannot hide the system package. Your
wallpaper images and preferences are kept. Open the packaged app after
installation to enable its saved monitor-helper preference again.

To remove the package, first turn off **Adjust to monitor changes**, press
**Apply**, and choose **Quit**, then run `sudo apt remove wallpaper-controls`.
Removal keeps your wallpaper images and preferences.

### Install from source

Install the system packages:

```sh
sudo apt install python3-gi python3-gi-cairo python3-pil gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 gsettings-desktop-schemas librsvg2-common webp-pixbuf-loader
```

From this folder, run:

```sh
./install.sh
```

Find **Wallpaper Controls** in the app launcher. The installer works in your
user account and does not require `sudo`. You can also run `./run.sh` without
installing. To remove the app, run `./uninstall.sh`; it keeps your wallpaper
images and preferences so your current desktop image does not disappear.

To update, download the new version and run `./install.sh` again. If the app is
running, choose **Quit** from its menu and reopen it to load the update. Quit
asks before discarding pending edits. Closing the window may leave the optional
display helper running; Quit stops it until the app next opens or you log in.

## How to use it

Choose **Light mode** or **Dark mode**, select an image, and adjust its sizing. The
preview updates while GNOME's wallpaper stays unchanged. Press **Apply** when
you are happy with the result, or **Discard Changes** to discard the edits. **Use for Both** uses the selected image for both light and dark mode when you apply. The background color fills space left around the image. Choose a
Small, Medium, or Large **Border width** when you want the color to remain
visible even if the image already matches or fills the screen. When you choose
a color while the image covers the display, the app selects Medium for you.
Choose **Color only** to fill the screen with that color without an image.
Borders are measured around the whole screen; GNOME's top bar and dock may
cover part of a border, making the visible edges look unequal.

If GNOME has no separate dark image saved, the app previews the light image in
dark mode and labels it **Same as light mode**, matching GNOME's behavior.

Use **Image position** to choose which edge or corner stays visible with Fill,
Fit, Original size, or Span. Position and sizing apply to both modes and to
every monitor. The preview uses the same renderer as generated wallpapers.

Drop one image from Files onto the preview or Image row to change the selected
mode. In per-monitor mode, drop onto a numbered monitor in the preview or
its monitor row. Drops stay in the preview until you press **Apply**.

Open the menu in the title bar and choose **Restore Previous Wallpaper** to restore the
previous wallpaper, placement, color, and app preferences. Undo is available
after Apply and survives reopening the app. Apply or discard any pending edits
first. A wallpaper change made outside the app clears Undo so it cannot
accidentally overwrite another app's choices.

For separate images on each monitor, turn on **Different wallpapers per monitor** and choose an image in each connected monitor row. Repeat for the
other mode if you want different light and dark sets. The same sizing
choice applies inside every monitor. Press **Apply** to generate and use the
combined wallpaper.

Choose **Show Monitor Numbers** to show each monitor's number and connector for
five seconds. Press Escape or click a label to dismiss them sooner.

**Adjust to monitor changes** automatically rebuilds the last applied images
when the display arrangement or scale changes. It applies to generated
wallpapers (per-monitor images, borders, or custom alignment). A lightweight
helper stays running after the window closes and starts at login. Turn this
switch off and press **Apply** to stop the helper and remove its login entry.
New displays inherit a saved image; images for unplugged displays are kept for
their return. Pending image or color edits are never applied by the helper.

The file-manager action opens Wallpaper Controls with the selected image staged
for both modes. You still need to press **Apply**.

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
- PNG, JPEG, WebP, GIF, BMP, TIFF, and SVG are supported with the packages above.
  Animated images use a still frame. GNOME slideshow XML files cannot be composed.
- Source images are limited to 64 megapixels and generated wallpapers to
  32 megapixels across the display arrangement, including gaps between displays.

## Development and release

Run `/usr/bin/python3 -m pytest -q` to check image composition, saved preferences,
and Undo. Tests use isolated settings and temporary folders, so they do not
change your desktop wallpaper. GTK integration checks run when a display is
available; install `python3-pytest xvfb xauth dbus` and use
`dbus-run-session -- xvfb-run -a /usr/bin/python3 -m pytest -q`
to run all checks on a virtual display. See
[RELEASING.md](RELEASING.md) for the public release process and current Flathub
constraints. The project is licensed under
[GPL-3.0-or-later](LICENSE).
