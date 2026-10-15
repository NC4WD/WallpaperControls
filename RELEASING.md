# Releasing Wallpaper-Controls

The intended public repository is
[`NC4WD/WallpaperControls`](https://github.com/NC4WD/WallpaperControls). Its
name must remain `WallpaperControls` to match the application ID
`io.github.nc4wd.WallpaperControls` used by the app and its desktop files.

## GitHub release

1. Review the source, metadata, and [AI disclosure](AI_DISCLOSURE.md).
2. Run `dbus-run-session -- xvfb-run -a /usr/bin/python3 -m pytest -q` and
   `appstreamcli validate --no-net io.github.nc4wd.WallpaperControls.metainfo.xml`.
3. Test `./install.sh`, the app window, the Files action, and `./uninstall.sh`
   on a clean GNOME user account. Test the per-monitor result with two physical
   displays, including a Light/Dark switch and a changed display layout.
   Verify numbered labels appear on the intended physical displays and the
   helper rebuilds after closing the window and after logging in. The test
   suite covers simulated display layouts and cannot replace these physical
   display checks. Verify Undo restores both appearances and the chosen color.
4. Push the reviewed source to the public GitHub repository.
5. Review the real app screenshots in `assets/screenshots/`. Set the release
   date in AppStream and the changelog to the publication date, and update
   screenshot URLs to point to the release tag.
6. Tag the reviewed version and publish a GitHub release. Make sure the
   screenshot URL in AppStream resolves from that tag.

## Build downloadable packages

Commit the reviewed source, then run:

```sh
/usr/bin/python3 packaging/build.py
```

The builder requires Git, Python 3, and `dpkg-deb`, and runs without root.
Build in a Git checkout. To rebuild from an extracted source archive,
initialize a Git repository there and commit its files first.
It creates `dist/wallpaper-controls_0.2.1-1_all.deb`, the matching source archive,
and `SHA256SUMS`. Both packages come from the same clean commit. The `.deb`
contains only Python code and assets, so its architecture is `all`; it targets
Ubuntu 24.04 or newer with GNOME. It installs under `/usr` without modifying
users' wallpaper settings or personal files during installation.

Use `--revision 2` for a packaging-only update to the same app version and
`--maintainer 'Name <email@example.com>'` to override the package contact.
An app update also changes `APP_VERSION`, AppStream, and the changelog.
Run `lintian dist/*.deb`, validate the packaged desktop files and metadata,
and test installation, upgrade, launch, and removal in a disposable Ubuntu
24.04 environment. Publish the `.deb`, matching source archive, and checksums
together after the physical-display release checks above, or an explicit
maintainer waiver recorded in the release notes.

This builds a GitHub download. An Ubuntu repository or PPA would be separate
work and is needed for automatic updates through Software Updater.

## Release audit — 2026-10-13

The 0.2.0 candidate received a source, settings, image-rendering, helper,
installer, and metadata audit. The audit fixed save rollback and image retention,
malformed preferences, tiny-tile performance, oversized image handling, native
color-only backgrounds, dark-image fallback, update shutdown, and launcher
escaping. Regression checks cover these paths, including simulated failed saves.

Validation uses temporary preferences, a memory settings backend, and disposable
install folders. A clean Ubuntu 24.04 container checks the minimum supported
desktop libraries; it uses a virtual display and does not run GNOME Shell.

| Check | Result |
| --- | --- |
| Full suite on Ubuntu 26.04, GTK 4.22 / libadwaita 1.9 | 64 passed |
| Full suite in a clean Ubuntu 24.04 container, GTK 4.14 / libadwaita 1.5 | 64 passed |
| Final image-input checks on Ubuntu 26.04, including a nonlocal URI rejection added after the full runs | 9 passed |
| AppStream metadata, desktop entries, source and installer syntax | Passed |
| Clean install, installed version command, and uninstall on Ubuntu 24.04 | Passed |

The suites report desktop-library deprecation warnings, with no failed tests.
These APIs remain compatible with the minimum supported libraries. Physical
monitor and login checks remain outstanding.

**Physical-display validation (outstanding for 0.2.0):** test two physical monitors in a real
GNOME session. Cover different light/dark images, Apply and Restore Previous
Wallpaper, monitor numbers, mixed display scales, unplug/replug, rearrangement,
the helper after closing the window, and helper startup after login. Also check
the Files action and keyboard navigation in that session. Automated tests do
not establish the real compositor result or login behavior.

On 2026-10-14 the maintainer explicitly authorized publishing 0.2.0 without
the physical two-monitor test. The release notes disclose that this test was
skipped. This waiver does not mark physical-display or login validation as
passed. The final automated suite passed all 65 checks on Ubuntu 24.04 and
26.04; package installation, upgrade, removal, preference retention, and the
installed app's Apply/Undo and login-helper removal behavior were also checked.

The v0.2.0 screenshot URLs point to the release tag. This GitHub release does
not include a Flathub submission.

## Flathub status

This repository does **not** include a Flatpak manifest. Flathub's current
[generative AI policy](https://docs.flathub.org/docs/for-app-authors/requirements)
prohibits AI-generated or AI-assisted manifests and requires disclosure of
AI-generated application material. A human maintainer must author the manifest
and personally handle the submission and review.

Flathub also expects a meaningful development history, tagged releases, and
evidence of real-world use. Publish and maintain the GitHub version first, then
recheck Flathub's requirements before considering a submission.

There is also a functional packaging issue to resolve: the app changes GNOME's
wallpaper GSettings directly, while ordinary Flatpak sandboxes use private
settings. A Flatpak build must demonstrate that it can read and update the
host desktop's settings without excessive permissions, or adapt to the
[Wallpaper portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Wallpaper.html).
The portal can set an image but does not offer this app's placement and
per-appearance controls. Do not submit a Flatpak until this behavior is tested
on a real GNOME session.
