# Releasing Wallpaper Controls

The intended public repository is
[`NC4WD/WallpaperControls`](https://github.com/NC4WD/WallpaperControls). Its
name must remain `WallpaperControls` to match the application ID
`io.github.nc4wd.WallpaperControls` used by the app and its desktop files.

## GitHub release

1. Review the source, metadata, and [AI disclosure](AI_DISCLOSURE.md).
2. Run `/usr/bin/python3 -m pytest -q` and
   `appstreamcli validate --no-net io.github.nc4wd.WallpaperControls.metainfo.xml`.
3. Test `./install.sh`, the app window, the Files action, and `./uninstall.sh`
   on a clean GNOME user account. Test the per-monitor result with two physical
   displays, including a Light/Dark switch and a changed display layout.
4. Create a public GitHub repository named `WallpaperControls` under `NC4WD`,
   put this folder at its root, and push the reviewed source.
5. Review the real app screenshots in `assets/screenshots/` and the AppStream
   metadata. The screenshot URLs are pinned to `v0.1.0`.
6. Tag the reviewed version `v0.1.0` and publish a GitHub release. Make sure
   both screenshot URLs in AppStream resolve from that tag.

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
