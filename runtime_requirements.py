# SPDX-License-Identifier: GPL-3.0-or-later
"""Check desktop library versions before installing or opening a window."""


def check_versions(gtk_version, adw_version):
    if tuple(gtk_version) < (4, 10) or tuple(adw_version) < (1, 4):
        raise ValueError(
            "Wallpaper Controls needs GTK 4.10 and libadwaita 1.4 or newer. "
            "Use Ubuntu 24.04 or newer with the GNOME desktop.")


def check_schemas(schema_source):
    if schema_source is None or any(
            schema_source.lookup(schema, True) is None
            for schema in ("org.gnome.desktop.background", "org.gnome.desktop.interface")):
        raise ValueError(
            "GNOME wallpaper settings are missing. "
            "On Ubuntu, install gsettings-desktop-schemas.")
