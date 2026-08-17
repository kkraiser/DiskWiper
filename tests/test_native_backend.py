from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from dataclasses import replace

import pytest

from diskwiper.disks.discovery import DiskInventory
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import JobStatus, VolumeInfo, WipeAuthorization
from diskwiper.wipe.backends import BackendError
from diskwiper.wipe.native import NativeRawWriteBackend
from diskwiper.wipe.raw import RawWriteError
from tests.factories import make_disk


class SequenceDiscovery:
    def __init__(self, *disks) -> None:
        self.disks = list(disks)

    def discover(self) -> DiskInventory:
        return DiskInventory("generation", (self.disks.pop(0),))


class FakeRawDisk(AbstractContextManager):
    def __init__(self, disk, cancel: threading.Event | None = None) -> None:
        self.size_bytes = disk.size_bytes
        self.logical_sector_size = disk.logical_sector_size
        self.physical_sector_size = disk.physical_sector_size
        self.cancel = cancel
        self.writes: list[tuple[int, int]] = []
        self.flushed = False
        self.properties_updated = False
        self.write_error: Exception | None = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def write_zeros(self, offset: int, length: int) -> int:
        if self.write_error is not None:
            raise self.write_error
        self.writes.append((offset, length))
        if self.cancel is not None:
            self.cancel.set()
        return length

    def flush(self) -> None:
        self.flushed = True

    def update_properties(self) -> None:
        self.properties_updated = True


class FakeLocker(AbstractContextManager):
    def __init__(self, paths, captured: list[tuple[str, ...]]) -> None:
        captured.append(tuple(paths))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


def authorization_for(disk) -> WipeAuthorization:
    return WipeAuthorization(
        fingerprint=disk.fingerprint,
        disk_number=disk.disk_number,
        model=disk.model,
        serial_number=disk.serial_number,
        size_bytes=disk.size_bytes,
        inventory_generation="generation",
    )


def make_backend(discovery, raw, captured_locks, **changes):
    options = dict(
        discovery=discovery,
        protection_policy=ProtectionPolicy(frozenset()),
        real_wipes_enabled=True,
        is_admin=lambda: True,
        raw_disk_factory=lambda _number: raw,
        volume_locker=lambda paths: FakeLocker(paths, captured_locks),
        chunk_size=4096,
    )
    options.update(changes)
    return NativeRawWriteBackend(**options)


def test_native_backend_locks_revalidates_writes_and_verifies() -> None:
    before = make_disk(size_bytes=8192)
    after = replace(before, partition_count=0, volumes=())
    raw = FakeRawDisk(before)
    locks: list[tuple[str, ...]] = []
    events = []
    backend = make_backend(SequenceDiscovery(before, before, after), raw, locks)

    result = backend.run(
        authorization_for(before),
        threading.Event(),
        lambda *event: events.append(event),
    )

    assert locks == [(r"\\?\Volume{test-volume}",)]
    assert raw.writes == [(0, 4096), (4096, 4096)]
    assert raw.flushed and raw.properties_updated
    assert result.status is JobStatus.COMPLETE
    assert any(event[0] is JobStatus.WIPING for event in events)


def test_native_backend_cancellation_is_incomplete() -> None:
    disk = make_disk(size_bytes=8192)
    cancel = threading.Event()
    raw = FakeRawDisk(disk, cancel)
    backend = make_backend(SequenceDiscovery(disk, disk), raw, [])

    result = backend.run(authorization_for(disk), cancel, lambda *_: None)

    assert result.status is JobStatus.CANCELLED_INCOMPLETE
    assert result.bytes_processed == 4096
    assert not raw.flushed
    assert not raw.properties_updated


def test_native_backend_rejects_incomplete_volume_lock_coverage() -> None:
    disk = make_disk(
        partition_count=2,
        volumes=(VolumeInfo(drive_letter="T"),),
    )
    raw = FakeRawDisk(disk)
    backend = make_backend(SequenceDiscovery(disk), raw, [])

    with pytest.raises(BackendError, match="lock coverage"):
        backend.run(authorization_for(disk), threading.Event(), lambda *_: None)

    assert not raw.writes


def test_native_backend_rejects_geometry_change_before_writing() -> None:
    disk = make_disk(size_bytes=4096)
    raw = FakeRawDisk(disk)
    raw.physical_sector_size = 512
    backend = make_backend(SequenceDiscovery(disk, disk), raw, [])

    with pytest.raises(BackendError, match="physical sector size changed"):
        backend.run(authorization_for(disk), threading.Event(), lambda *_: None)

    assert not raw.writes


def test_native_backend_gate_rejects_before_discovery() -> None:
    disk = make_disk(size_bytes=4096)
    raw = FakeRawDisk(disk)
    backend = make_backend(
        SequenceDiscovery(), raw, [], real_wipes_enabled=False
    )

    with pytest.raises(BackendError, match="gate is disabled"):
        backend.run(authorization_for(disk), threading.Event(), lambda *_: None)


def test_native_backend_translates_disconnect_style_write_failure() -> None:
    disk = make_disk(size_bytes=4096)
    raw = FakeRawDisk(disk)
    raw.write_error = RawWriteError("The device is not connected")
    backend = make_backend(SequenceDiscovery(disk, disk), raw, [])

    with pytest.raises(BackendError, match="device is not connected"):
        backend.run(authorization_for(disk), threading.Event(), lambda *_: None)

    assert not raw.flushed
    assert not raw.properties_updated


def test_native_backend_requires_zero_partitions_after_write() -> None:
    disk = make_disk(size_bytes=4096)
    raw = FakeRawDisk(disk)
    backend = make_backend(SequenceDiscovery(disk, disk, disk), raw, [])

    with pytest.raises(BackendError, match="found 1 partition"):
        backend.run(authorization_for(disk), threading.Event(), lambda *_: None)

    assert raw.flushed and raw.properties_updated
