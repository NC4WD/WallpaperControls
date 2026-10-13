# Changelog

## 0.2.0 — 2026-10-12

- Simplified labels, instructions, and error messages. Discard Changes and Restore Previous Wallpaper now clearly distinguish unapplied edits from undoing the last change. Light and dark modes, image sizing, monitor numbers, and automatic monitor adjustments use consistent wording.
- Added Undo Last Apply, including restoration after reopening the app and retention of the previous generated wallpaper files.
- Added image alignment for Fill, Fit, Center, and Span with a shared renderer for the preview and final wallpaper.
- Added Identify Displays with numbered labels that dismiss after five seconds, on click, or with Escape.
- Added automatic rebuilding of applied wallpapers when displays are connected, removed, scaled, or rearranged. The optional display helper runs in the background and at login; new displays inherit a saved image and disconnected display choices are retained.
- Added drag and drop onto the preview, image row, or individual monitor rows. Dropped images are staged until Apply; unsupported files and multiple-file drops show a clear error.
- Preserved pending edits during automatic rebuilds and stopped rebuilding when another app changes the desktop wallpaper.
- Fixed Center and Tile sizing on scaled displays and added GTK integration checks to continuous integration.

## 0.1.5 — 2026-10-11

- Fixed the single-image preview to use the connected display's actual resolution instead of assuming 1920×1080.
- Fixed Center previews that showed background color even though a larger image covered the real screen.
- Automatically select a Medium border when choosing a color that would otherwise be hidden.

## 0.1.4 — 2026-10-11

- Added Small, Medium, and Large border sizes so the background color remains visible even when an image matches the screen shape.
- Applied visible borders consistently to single-image and per-monitor wallpapers.
- Preserved original wallpaper choices while generating bordered wallpapers.

## 0.1.3 — 2026-10-11

- Show the selected background color as a hex value.
- Explain when the wallpaper covers the background color, including fitted images that already match the screen shape.
- Removed the unused transparency control from the color chooser.

## 0.1.2 — 2026-10-03

- Fixed the local app launcher showing a generic gear by installing a PNG icon and pointing both desktop entries directly to it.

## 0.1.1 — 2026-10-03

- Sized the window for the smallest connected display and made the preview more compact.
- Kept the main controls visible on a 768-pixel-tall screen, with a visible scrollbar when more rows are needed.

## 0.1.0 — 2026-10-03

- Added a GTK4/libadwaita window with wallpaper preview and Apply/Revert controls.
- Added Light and Dark images, placement choices, and a border color.
- Added separate images for each connected monitor through a generated spanned wallpaper.
- Added an image action for the Files “Open With” menu.
- Added an About window and a warning before discarding unapplied changes.
