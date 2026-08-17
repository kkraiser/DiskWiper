from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterable

from diskwiper.wipe.raw import RawWriteError


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_WRITE_THROUGH = 0x80000000
FILE_FLAG_NO_BUFFERING = 0x20000000
FILE_BEGIN = 0

MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04

IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020

STORAGE_ACCESS_ALIGNMENT_PROPERTY = 6
PROPERTY_STANDARD_QUERY = 0
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _StoragePropertyQuery(ctypes.Structure):
    _fields_ = (
        ("property_id", wintypes.DWORD),
        ("query_type", wintypes.DWORD),
        ("additional_parameters", ctypes.c_ubyte * 1),
    )


class _StorageAccessAlignmentDescriptor(ctypes.Structure):
    _fields_ = (
        ("version", wintypes.DWORD),
        ("size", wintypes.DWORD),
        ("bytes_per_cache_line", wintypes.DWORD),
        ("bytes_offset_for_cache_alignment", wintypes.DWORD),
        ("bytes_per_logical_sector", wintypes.DWORD),
        ("bytes_per_physical_sector", wintypes.DWORD),
        ("bytes_offset_for_sector_alignment", wintypes.DWORD),
    )


@dataclass(frozen=True)
class DeviceGeometry:
    size_bytes: int
    logical_sector_size: int
    physical_sector_size: int


class WindowsRawDisk:
    """Unbuffered synchronous access to one Windows physical disk."""

    def __init__(self, disk_number: int) -> None:
        if os.name != "nt":
            raise RawWriteError("Raw disk writing is only supported on Windows")
        if disk_number < 0:
            raise ValueError("Disk number cannot be negative")

        self._kernel32 = _configure_kernel32()
        self._handle: int | None = None
        self._zero_buffer: int | None = None
        self._zero_buffer_size = 0
        path = physical_disk_path(disk_number)
        handle = self._kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise _last_error(f"Could not open {path} for raw writing")
        self._handle = handle

        try:
            geometry = self._query_geometry()
        except Exception:
            self.close()
            raise
        self.size_bytes = geometry.size_bytes
        self.logical_sector_size = geometry.logical_sector_size
        self.physical_sector_size = geometry.physical_sector_size

    def write_zeros(self, offset: int, length: int) -> int:
        handle = self._require_open()
        if offset < 0 or length <= 0:
            raise RawWriteError("Raw write offset and length must be positive")
        if offset % self.logical_sector_size or length % self.logical_sector_size:
            raise RawWriteError("Raw write is not aligned to the logical sector size")
        buffer = self._get_zero_buffer(length)
        if not self._kernel32.SetFilePointerEx(
            handle, ctypes.c_longlong(offset), None, FILE_BEGIN
        ):
            raise _last_error(f"Could not seek raw disk to offset {offset}")
        written = wintypes.DWORD()
        if not self._kernel32.WriteFile(
            handle,
            ctypes.c_void_p(buffer),
            length,
            ctypes.byref(written),
            None,
        ):
            raise _last_error(f"Raw write failed at offset {offset}")
        return int(written.value)

    def flush(self) -> None:
        if not self._kernel32.FlushFileBuffers(self._require_open()):
            raise _last_error("Could not flush raw disk writes")

    def update_properties(self) -> None:
        returned = wintypes.DWORD()
        if not self._kernel32.DeviceIoControl(
            self._require_open(),
            IOCTL_DISK_UPDATE_PROPERTIES,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        ):
            raise _last_error("Could not refresh raw disk properties")

    def close(self) -> None:
        if self._zero_buffer is not None:
            if not self._kernel32.VirtualFree(
                ctypes.c_void_p(self._zero_buffer), 0, MEM_RELEASE
            ):
                raise _last_error("Could not release aligned zero buffer")
            self._zero_buffer = None
            self._zero_buffer_size = 0
        if self._handle is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> WindowsRawDisk:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _query_geometry(self) -> DeviceGeometry:
        handle = self._require_open()
        length = ctypes.c_longlong()
        returned = wintypes.DWORD()
        if not self._kernel32.DeviceIoControl(
            handle,
            IOCTL_DISK_GET_LENGTH_INFO,
            None,
            0,
            ctypes.byref(length),
            ctypes.sizeof(length),
            ctypes.byref(returned),
            None,
        ):
            raise _last_error("Could not query raw disk length")

        query = _StoragePropertyQuery(
            STORAGE_ACCESS_ALIGNMENT_PROPERTY,
            PROPERTY_STANDARD_QUERY,
        )
        alignment = _StorageAccessAlignmentDescriptor()
        if not self._kernel32.DeviceIoControl(
            handle,
            IOCTL_STORAGE_QUERY_PROPERTY,
            ctypes.byref(query),
            ctypes.sizeof(query),
            ctypes.byref(alignment),
            ctypes.sizeof(alignment),
            ctypes.byref(returned),
            None,
        ):
            raise _last_error("Could not query raw disk sector alignment")
        geometry = DeviceGeometry(
            size_bytes=int(length.value),
            logical_sector_size=int(alignment.bytes_per_logical_sector),
            physical_sector_size=int(alignment.bytes_per_physical_sector),
        )
        validate_device_geometry(geometry)
        return geometry

    def _get_zero_buffer(self, length: int) -> int:
        if length > self._zero_buffer_size:
            if self._zero_buffer is not None:
                if not self._kernel32.VirtualFree(
                    ctypes.c_void_p(self._zero_buffer), 0, MEM_RELEASE
                ):
                    raise _last_error("Could not resize aligned zero buffer")
            address = self._kernel32.VirtualAlloc(
                None, length, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE
            )
            if not address:
                self._zero_buffer = None
                self._zero_buffer_size = 0
                raise _last_error(f"Could not allocate {length} byte zero buffer")
            self._zero_buffer = int(address)
            self._zero_buffer_size = length
        assert self._zero_buffer is not None
        return self._zero_buffer

    def _require_open(self) -> int:
        if self._handle is None:
            raise RawWriteError("Raw disk handle is closed")
        return self._handle


class LockedVolumes:
    """Own exclusive locks for all supplied volumes until the context exits."""

    def __init__(self, volume_paths: Iterable[str]) -> None:
        if os.name != "nt":
            raise RawWriteError("Volume locking is only supported on Windows")
        self._kernel32 = _configure_kernel32()
        self._handles: list[int] = []
        try:
            for source_path in volume_paths:
                path = volume_device_path(source_path)
                handle = self._kernel32.CreateFileW(
                    path,
                    GENERIC_READ | GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    None,
                    OPEN_EXISTING,
                    0,
                    None,
                )
                if handle == INVALID_HANDLE_VALUE:
                    raise _last_error(f"Could not open volume {path}")
                self._handles.append(handle)
                self._control(handle, FSCTL_LOCK_VOLUME, f"Could not lock volume {path}")
                self._control(
                    handle,
                    FSCTL_DISMOUNT_VOLUME,
                    f"Could not dismount volume {path}",
                )
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        while self._handles:
            self._kernel32.CloseHandle(self._handles.pop())

    def __enter__(self) -> LockedVolumes:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _control(self, handle: int, code: int, message: str) -> None:
        returned = wintypes.DWORD()
        if not self._kernel32.DeviceIoControl(
            handle, code, None, 0, None, 0, ctypes.byref(returned), None
        ):
            raise _last_error(message)


def physical_disk_path(disk_number: int) -> str:
    if disk_number < 0:
        raise ValueError("Disk number cannot be negative")
    return rf"\\.\PhysicalDrive{disk_number}"


def volume_device_path(path: str) -> str:
    """Convert a drive letter or volume GUID access path for CreateFile."""
    cleaned = path.strip().rstrip("\\")
    if len(cleaned) == 1 and cleaned.isalpha():
        cleaned += ":"
    if len(cleaned) == 2 and cleaned[0].isalpha() and cleaned[1] == ":":
        return rf"\\.\{cleaned.upper()}"
    if cleaned.lower().startswith(r"\\?\volume{") and cleaned.endswith("}"):
        return cleaned
    raise RawWriteError(f"Unsupported volume access path: {path!r}")


def validate_device_geometry(geometry: DeviceGeometry) -> None:
    if geometry.size_bytes <= 0:
        raise RawWriteError("Raw disk reported an invalid length")
    logical = geometry.logical_sector_size
    physical = geometry.physical_sector_size
    if logical <= 0 or physical <= 0:
        raise RawWriteError("Raw disk reported an invalid sector size")
    if physical % logical:
        raise RawWriteError("Physical sector size is not a multiple of logical size")
    if geometry.size_bytes % logical:
        raise RawWriteError("Raw disk length is not aligned to logical sectors")


def _last_error(message: str) -> RawWriteError:
    error = ctypes.WinError(ctypes.get_last_error())
    return RawWriteError(f"{message}: {error}")


def _configure_kernel32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.DeviceIoControl.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    kernel32.DeviceIoControl.restype = wintypes.BOOL
    kernel32.SetFilePointerEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    kernel32.SetFilePointerEx.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.VirtualAlloc.argtypes = (
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    kernel32.VirtualAlloc.restype = wintypes.LPVOID
    kernel32.VirtualFree.argtypes = (
        wintypes.LPVOID,
        ctypes.c_size_t,
        wintypes.DWORD,
    )
    kernel32.VirtualFree.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32
