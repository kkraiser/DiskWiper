from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable, Protocol


class RawWriteError(RuntimeError):
    """Raised when a raw device cannot be overwritten completely and safely."""


class RawWriteDevice(Protocol):
    """Minimal device contract used by the platform-independent write engine."""

    size_bytes: int
    logical_sector_size: int
    physical_sector_size: int

    def write_zeros(self, offset: int, length: int) -> int: ...

    def flush(self) -> None: ...


ProgressReporter = Callable[[int, int], None]


@dataclass(frozen=True)
class RawWriteResult:
    bytes_written: int
    cancelled: bool


def overwrite_with_zeros(
    device: RawWriteDevice,
    cancel_event: threading.Event,
    report: ProgressReporter,
    *,
    expected_size: int,
    chunk_size: int = 16 * 1024 * 1024,
) -> RawWriteResult:
    """Overwrite an entire device with zeroes using aligned, exact writes.

    The device implementation owns buffer allocation so a Windows implementation
    can meet FILE_FLAG_NO_BUFFERING address-alignment requirements.
    """
    alignment = _validate_geometry(device, expected_size, chunk_size)
    written = 0
    report(0, expected_size)

    while written < expected_size:
        if cancel_event.is_set():
            return RawWriteResult(bytes_written=written, cancelled=True)

        length = min(chunk_size, expected_size - written)
        if length % alignment:
            raise RawWriteError(
                f"Final write length {length} is not aligned to {alignment} bytes"
            )
        actual = device.write_zeros(written, length)
        if actual != length:
            raise RawWriteError(
                f"Short raw write at offset {written}: expected {length}, wrote {actual}"
            )
        written += actual
        report(written, expected_size)

    device.flush()
    return RawWriteResult(bytes_written=written, cancelled=False)


def _validate_geometry(
    device: RawWriteDevice,
    expected_size: int,
    chunk_size: int,
) -> int:
    if expected_size <= 0:
        raise RawWriteError("Authorized disk size must be positive")
    if device.size_bytes != expected_size:
        raise RawWriteError(
            "Raw device size changed after authorization: "
            f"expected {expected_size}, found {device.size_bytes}"
        )
    logical = device.logical_sector_size
    physical = device.physical_sector_size
    if logical <= 0 or physical <= 0:
        raise RawWriteError("Raw device reported an invalid sector size")
    if physical % logical:
        raise RawWriteError(
            f"Physical sector size {physical} is not a multiple of logical size {logical}"
        )
    alignment = max(logical, physical)
    if expected_size % logical:
        raise RawWriteError(
            f"Device size {expected_size} is not aligned to logical sectors"
        )
    if chunk_size <= 0 or chunk_size % alignment:
        raise RawWriteError(
            f"Chunk size {chunk_size} is not aligned to {alignment} bytes"
        )
    return logical
