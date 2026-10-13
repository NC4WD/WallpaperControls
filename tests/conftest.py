# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests must never select the live desktop settings backend."""
import os

# GLib caches its default backend. Set this before test modules import Gio,
# including desktop-launch tests that may initialise desktop settings.
os.environ["GSETTINGS_BACKEND"] = "memory"
