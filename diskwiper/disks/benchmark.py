from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes
from typing import Callable


class BenchmarkError(RuntimeError):
    pass


def benchmark_read_speed(
    disk_number: int,
    size_bytes: int,
    *,
    sample_bytes: int = 16 * 1024 * 1024,
    clock: Callable[[], float] = time.perf_counter,
) -> float:
    """Measure sampled raw read throughput without writing to the disk."""
    if os.name != "nt":
        raise BenchmarkError("Raw disk benchmarking is only supported on Windows")
    if size_bytes < sample_bytes:
        raise BenchmarkError("Disk is too small for the benchmark sample")
    offsets = tuple(
        min(size_bytes - sample_bytes, int(size_bytes * fraction)) // 4096 * 4096
        for fraction in (0.1, 0.5, 0.9)
    )
    reader = _WindowsRawReader(disk_number)
    started = clock()
    total = 0
    try:
        for offset in offsets:
            total += reader.read(offset, sample_bytes)
    finally:
        reader.close()
    elapsed = clock() - started
    if elapsed <= 0 or total <= 0:
        raise BenchmarkError("Benchmark returned no usable timing data")
    return total / elapsed


class _WindowsRawReader:
    GENERIC_READ = 0x80000000
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OPEN_EXISTING = 3
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_BEGIN = 0

    def __init__(self, disk_number: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
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
        kernel32.SetFilePointerEx.argtypes = (
            wintypes.HANDLE,
            ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.DWORD,
        )
        kernel32.SetFilePointerEx.restype = wintypes.BOOL
        kernel32.ReadFile.argtypes = (
            wintypes.HANDLE,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID,
        )
        kernel32.ReadFile.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._handle = kernel32.CreateFileW(
            rf"\\.\PhysicalDrive{disk_number}",
            self.GENERIC_READ,
            self.FILE_SHARE_READ | self.FILE_SHARE_WRITE,
            None,
            self.OPEN_EXISTING,
            self.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if self._handle == wintypes.HANDLE(-1).value:
            raise BenchmarkError(
                f"Raw read access was denied: {ctypes.WinError(ctypes.get_last_error())}"
            )

    def read(self, offset: int, length: int) -> int:
        if not self._kernel32.SetFilePointerEx(
            self._handle, ctypes.c_longlong(offset), None, self.FILE_BEGIN
        ):
            raise BenchmarkError(str(ctypes.WinError(ctypes.get_last_error())))
        buffer = ctypes.create_string_buffer(length)
        read = wintypes.DWORD()
        if not self._kernel32.ReadFile(
            self._handle, buffer, length, ctypes.byref(read), None
        ):
            raise BenchmarkError(str(ctypes.WinError(ctypes.get_last_error())))
        return int(read.value)

    def close(self) -> None:
        if getattr(self, "_handle", None) is not None:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def estimated_wipe_duration(
    size_bytes: int, measured_read_bytes_per_second: float
) -> float:
    """Estimate zero-write duration at 60% of sampled read throughput."""
    if size_bytes <= 0 or measured_read_bytes_per_second <= 0:
        raise ValueError("Capacity and measured speed must be positive")
    return size_bytes / (measured_read_bytes_per_second * 0.6)
