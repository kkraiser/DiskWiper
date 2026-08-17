from __future__ import annotations

import pytest

from diskwiper.wipe.raw import RawWriteError
from diskwiper.wipe.win32 import (
    DeviceGeometry,
    physical_disk_path,
    validate_device_geometry,
    volume_device_path,
)


def test_physical_disk_path_rejects_negative_numbers() -> None:
    assert physical_disk_path(4) == r"\\.\PhysicalDrive4"
    with pytest.raises(ValueError, match="negative"):
        physical_disk_path(-1)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("t", r"\\.\T:"),
        ("T:", r"\\.\T:"),
        ("\\\\?\\Volume{1234}\\", r"\\?\Volume{1234}"),
    ),
)
def test_volume_paths_are_normalized_for_direct_access(source: str, expected: str) -> None:
    assert volume_device_path(source) == expected


def test_unknown_volume_path_fails_closed() -> None:
    with pytest.raises(RawWriteError, match="Unsupported volume"):
        volume_device_path(r"C:\mount\disk")


def test_valid_geometry_is_accepted() -> None:
    validate_device_geometry(DeviceGeometry(4096, 512, 4096))


@pytest.mark.parametrize(
    "geometry",
    (
        DeviceGeometry(0, 512, 4096),
        DeviceGeometry(4096, 0, 4096),
        DeviceGeometry(4096, 512, 1000),
        DeviceGeometry(4097, 512, 4096),
    ),
)
def test_invalid_geometry_fails_closed(geometry: DeviceGeometry) -> None:
    with pytest.raises(RawWriteError):
        validate_device_geometry(geometry)
