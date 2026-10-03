#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
set -eu
exec /usr/bin/python3 "$(dirname "$0")/wallpaper_controls.py" "$@"
