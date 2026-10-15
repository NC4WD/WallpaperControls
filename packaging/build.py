#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a Debian binary and matching Git source archive without root."""

import argparse
import ast
from datetime import datetime, timezone
from email.utils import format_datetime
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.nc4wd.WallpaperControls"
MAINTAINER = "NC4WD <silvermach2002@gmail.com>"
MODULES = ("wallpaper_controls.py", "monitor_wallpaper.py", "monitor_state.py",
           "wallpaper_backend.py", "desktop_integration.py", "runtime_requirements.py")


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def write(path, contents, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(mode)


def compress(path, contents, epoch):
    with path.open("wb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=epoch) as archive:
            archive.write(contents)
    path.chmod(0o644)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--revision", default="1", help="Debian packaging revision")
    parser.add_argument("--maintainer", default=MAINTAINER)
    args = parser.parse_args()
    if not re.fullmatch(r"[1-9][0-9]*", args.revision):
        parser.error("revision must be a positive integer")
    if not re.fullmatch(r"[^<>\r\n]+ <[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+>", args.maintainer):
        parser.error("maintainer must be Name <working-email@example.com>")
    if shutil.which("dpkg-deb") is None:
        parser.error("dpkg-deb is required; on Ubuntu install dpkg")
    if not (ROOT / ".git").exists():
        parser.error("build from a Git checkout, or initialize and commit the extracted source first")
    if git("status", "--porcelain", "--untracked-files=normal").strip():
        parser.error("commit source changes first so the binary and source archive match")
    tree = ast.parse((ROOT / "wallpaper_controls.py").read_text())
    version = next(ast.literal_eval(node.value) for node in tree.body
                   if isinstance(node, ast.Assign) and
                   any(isinstance(target, ast.Name) and target.id == "APP_VERSION"
                       for target in node.targets))
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        parser.error("APP_VERSION must be a numeric dotted version")
    epoch = int(git("show", "-s", "--format=%ct", "HEAD").strip())
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    deb = output / f"wallpaper-controls_{version}-{args.revision}_all.deb"
    source = output / f"wallpaper-controls-{version}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="wallpaper-deb-") as temporary:
        package = Path(temporary) / "package"
        app = package / "usr/share/wallpaper-controls"
        app.mkdir(parents=True)
        for filename in MODULES:
            shutil.copyfile(ROOT / filename, app / filename)
            (app / filename).chmod(0o755 if filename == "wallpaper_controls.py" else 0o644)
        write(package / "usr/bin/wallpaper-controls",
              '#!/bin/sh\nexec /usr/bin/python3 /usr/share/wallpaper-controls/wallpaper_controls.py "$@"\n',
              mode=0o755)
        for name in (APP_ID, f"{APP_ID}.SetWallpaper"):
            contents = (ROOT / f"{name}.desktop.in").read_text().replace(
                "@EXEC@", "/usr/bin/wallpaper-controls")
            write(package / f"usr/share/applications/{name}.desktop", contents)
        for extension, size in (("svg", "scalable"), ("png", "256x256")):
            path = package / f"usr/share/icons/hicolor/{size}/apps/{APP_ID}.{extension}"
            path.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / f"{APP_ID}.{extension}", path)
            path.chmod(0o644)
        write(package / f"usr/share/metainfo/{APP_ID}.metainfo.xml",
              (ROOT / f"{APP_ID}.metainfo.xml").read_text())
        docs = package / "usr/share/doc/wallpaper-controls"
        docs.mkdir(parents=True)
        for filename, destination in (("README.md", "README.md.gz"),
                                      ("CHANGELOG.md", "changelog.gz"),
                                      ("AI_DISCLOSURE.md", "AI_DISCLOSURE.md.gz")):
            compress(docs / destination, (ROOT / filename).read_bytes(), 0)
        changelog = (
            f"wallpaper-controls ({version}-{args.revision}) noble; urgency=medium\n\n"
            "  * Package the reviewed application for Ubuntu 24.04 and newer.\n\n"
            f" -- {args.maintainer}  {format_datetime(datetime.fromtimestamp(epoch, timezone.utc))}\n")
        compress(docs / "changelog.Debian.gz", changelog.encode(), 0)
        manual = package / "usr/share/man/man1/wallpaper-controls.1.gz"
        manual.parent.mkdir(parents=True)
        compress(manual, (ROOT / "packaging/wallpaper-controls.1").read_text().replace(
            "@VERSION@", version).encode(), 0)
        write(package / "usr/share/lintian/overrides/wallpaper-controls",
              "# Distributed on GitHub, not uploaded to the Debian archive.\n"
              "# There is no Debian Intent To Package bug to close.\n"
              "wallpaper-controls: initial-upload-closes-no-bugs\n")
        write(docs / "copyright", (
            "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n"
            "Upstream-Name: Wallpaper-Controls\n"
            "Source: https://github.com/NC4WD/WallpaperControls\n\n"
            "Files: *\nCopyright: 2026 NC4WD\nLicense: GPL-3+\n"
            " This program is free software: you may redistribute it and/or modify it\n"
            " under the GNU General Public License, version 3 or any later version.\n"
            " .\n On Debian and Ubuntu, the full license is in\n"
            " /usr/share/common-licenses/GPL-3.\n\n"
            f"Files: usr/share/metainfo/{APP_ID}.metainfo.xml\n"
            "Copyright: 2026 NC4WD\nLicense: CC0-1.0\n"
            " This metadata is dedicated to the public domain under CC0 1.0.\n"
            " On Debian and Ubuntu, the full text is in\n"
            " /usr/share/common-licenses/CC0-1.0.\n"))
        payload = sorted(path for path in package.rglob("*") if path.is_file())
        installed_size = sum((path.stat().st_size + 1023) // 1024 for path in payload)
        control = package / "DEBIAN"
        write(control / "control", (
            f"Package: wallpaper-controls\nVersion: {version}-{args.revision}\n"
            "Section: gnome\nPriority: optional\nArchitecture: all\n"
            f"Maintainer: {args.maintainer}\nInstalled-Size: {installed_size}\n"
            "Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, python3-pil (>= 9.1), "
            "gir1.2-gtk-4.0 (>= 4.10), gir1.2-adw-1 (>= 1.4), gir1.2-gdkpixbuf-2.0, "
            "gsettings-desktop-schemas (>= 42), librsvg2-common, webp-pixbuf-loader\n"
            "Homepage: https://github.com/NC4WD/WallpaperControls\n"
            "Description: Preview and adjust wallpapers on GNOME desktops\n"
            " Choose wallpaper sizing, position, borders, and light/dark images.\n"
            " Compose different images for each monitor and preview before Apply.\n"
            " Requires GNOME with GTK 4.10 and libadwaita 1.4 or newer\n"
            " (Ubuntu 24.04 or newer).\n"))
        write(control / "md5sums", "".join(
            f"{hashlib.md5(path.read_bytes()).hexdigest()}  {path.relative_to(package).as_posix()}\n"
            for path in payload))
        for path in [package, *package.rglob("*")]:
            if path.is_dir():
                path.chmod(0o755)
            os.utime(path, (epoch, epoch))
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build",
                        str(package), str(deb)], check=True,
                       env={**os.environ, "SOURCE_DATE_EPOCH": str(epoch)})
    archive = git("archive", "--format=tar", f"--prefix=wallpaper-controls-{version}/", "HEAD")
    compress(source, archive, epoch)
    write(output / "SHA256SUMS", "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in (deb, source)))
    print(f"Built from commit {git('rev-parse', '--short', 'HEAD').decode().strip()}")
    for path in (deb, source, output / "SHA256SUMS"):
        print(path)


if __name__ == "__main__":
    main()
