from __future__ import annotations

import ctypes

import pytest

from diskwiper.wipe.raw import RawWriteError
import diskwiper.wipe.win32 as win32
from diskwiper.wipe.win32 import (
    DeviceGeometry,
    physical_disk_path,
    validate_device_geometry,
    volume_device_path,
    WindowsRawDisk,
    WindowsRawDiskProbe,
    LockedVolumes,
)


class FakeKernel32:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.controls: list[int] = []
        self.closed: list[int] = []
        self.writes: list[tuple[int, int]] = []
        self.flushed = False
        self.freed = False
        self.next_handle = 100

    def CreateFileW(self, path, *_args):
        self.created.append(path)
        self.next_handle += 1
        return self.next_handle

    def DeviceIoControl(
        self, _handle, code, _in_buffer, _in_size, out_buffer, _out_size,
        _returned, _overlapped,
    ):
        self.controls.append(code)
        if code == win32.IOCTL_DISK_GET_LENGTH_INFO:
            ctypes.cast(out_buffer, ctypes.POINTER(ctypes.c_longlong)).contents.value = 8192
        elif code == win32.IOCTL_STORAGE_QUERY_PROPERTY:
            descriptor = ctypes.cast(
                out_buffer,
                ctypes.POINTER(win32._StorageAccessAlignmentDescriptor),
            ).contents
            descriptor.bytes_per_logical_sector = 512
            descriptor.bytes_per_physical_sector = 4096
        return True

    def SetFilePointerEx(self, _handle, offset, _new_position, _method):
        self._offset = int(offset.value)
        return True

    def WriteFile(self, _handle, _buffer, length, written, _overlapped):
        ctypes.cast(written, ctypes.POINTER(win32.wintypes.DWORD)).contents.value = length
        self.writes.append((self._offset, length))
        return True

    def FlushFileBuffers(self, _handle):
        self.flushed = True
        return True

    def VirtualAlloc(self, *_args):
        return 0x10000

    def VirtualFree(self, *_args):
        self.freed = True
        return True

    def CloseHandle(self, handle):
        self.closed.append(handle)
        return True


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


def test_raw_disk_uses_queried_geometry_and_closes_resources() -> None:
    api = FakeKernel32()

    with WindowsRawDisk(4, kernel32=api) as disk:
        assert disk.size_bytes == 8192
        assert disk.logical_sector_size == 512
        assert disk.physical_sector_size == 4096
        assert disk.write_zeros(4096, 4096) == 4096
        disk.flush()
        disk.update_properties()

    assert api.created == [r"\\.\PhysicalDrive4"]
    assert api.writes == [(4096, 4096)]
    assert api.flushed and api.freed
    assert win32.IOCTL_DISK_UPDATE_PROPERTIES in api.controls
    assert api.closed == [101]


def test_volume_locker_locks_then_dismounts_and_closes_in_reverse() -> None:
    api = FakeKernel32()

    with LockedVolumes(("T", "U"), kernel32=api):
        assert api.controls == [
            win32.FSCTL_LOCK_VOLUME,
            win32.FSCTL_DISMOUNT_VOLUME,
            win32.FSCTL_LOCK_VOLUME,
            win32.FSCTL_DISMOUNT_VOLUME,
        ]

    assert api.created == [r"\\.\T:", r"\\.\U:"]
    assert api.closed == [102, 101]


def test_read_only_probe_requests_no_write_access_or_write_flags() -> None:
    api = FakeKernel32()
    calls = []
    original = api.CreateFileW

    def capture(path, access, sharing, security, creation, flags, template):
        calls.append((path, access, sharing, flags))
        return original(path, access, sharing, security, creation, flags, template)

    api.CreateFileW = capture
    with WindowsRawDiskProbe(4, kernel32=api) as probe:
        assert probe.geometry == DeviceGeometry(8192, 512, 4096)

    assert calls == [
        (
            r"\\.\PhysicalDrive4",
            win32.GENERIC_READ,
            win32.FILE_SHARE_READ | win32.FILE_SHARE_WRITE,
            0,
        )
    ]
    assert not api.writes
    assert api.closed == [101]
