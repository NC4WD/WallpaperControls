# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from runtime_requirements import check_schemas, check_versions


@pytest.mark.parametrize("gtk,adw", [((4, 6), (1, 1)), ((4, 14), (1, 2)), ((3, 24), (1, 4))])
def test_older_ubuntu_libraries_fail_with_install_guidance(gtk, adw):
    with pytest.raises(ValueError, match="Ubuntu 24.04"):
        check_versions(gtk, adw)


def test_supported_libraries_are_accepted():
    check_versions((4, 10), (1, 4))
    check_versions((4, 14), (1, 5))


def test_missing_gnome_schemas_fail_before_settings_construction():
    with pytest.raises(ValueError, match="gsettings-desktop-schemas"):
        check_schemas(None)
