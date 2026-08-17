from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from diskwiper.disks.discovery import DiskInventory
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.wipe.preflight import PreflightError, run_native_preflight
from diskwiper.wipe.win32 import DeviceGeometry
from tests.factories import make_disk


class SequenceDiscovery:
    def __init__(self, *disks) -> None:
        self.disks = list(disks)

    def discover(self) -> DiskInventory:
        return DiskInventory("generation", (self.disks.pop(0),))


class FakeProbe(AbstractContextManager):
    def __init__(self, geometry: DeviceGeometry) -> None:
        self.geometry = geometry
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True


def test_preflight_matches_read_only_geometry_and_revalidates() -> None:
    disk = make_disk(size_bytes=8192)
    probe = FakeProbe(DeviceGeometry(8192, 512, 4096))

    result = run_native_preflight(
        SequenceDiscovery(disk, disk),
        ProtectionPolicy(frozenset()),
        disk.disk_number,
        probe_factory=lambda _number: probe,
    )

    assert result.disk_number == disk.disk_number
    assert result.geometry.size_bytes == 8192
    assert probe.closed


def test_preflight_rejects_geometry_mismatch() -> None:
    disk = make_disk(size_bytes=8192)
    probe = FakeProbe(DeviceGeometry(4096, 512, 4096))

    with pytest.raises(PreflightError, match="geometry mismatch"):
        run_native_preflight(
            SequenceDiscovery(disk),
            ProtectionPolicy(frozenset()),
            disk.disk_number,
            probe_factory=lambda _number: probe,
        )

    assert probe.closed


def test_preflight_rejects_protected_disk_before_opening_probe() -> None:
    disk = make_disk(is_system=True)
    opened = False

    def factory(_number):
        nonlocal opened
        opened = True
        return FakeProbe(DeviceGeometry(disk.size_bytes, 512, 4096))

    with pytest.raises(PreflightError, match="protected"):
        run_native_preflight(
            SequenceDiscovery(disk),
            ProtectionPolicy(frozenset()),
            disk.disk_number,
            probe_factory=factory,
        )

    assert not opened
