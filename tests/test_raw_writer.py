from __future__ import annotations

import threading

import pytest

from diskwiper.wipe.raw import RawWriteError, overwrite_with_zeros


class FakeRawDevice:
    def __init__(
        self,
        size_bytes: int = 4096,
        logical_sector_size: int = 512,
        physical_sector_size: int = 4096,
    ) -> None:
        self.size_bytes = size_bytes
        self.logical_sector_size = logical_sector_size
        self.physical_sector_size = physical_sector_size
        self.writes: list[tuple[int, int]] = []
        self.flushed = False
        self.short_write = False

    def write_zeros(self, offset: int, length: int) -> int:
        self.writes.append((offset, length))
        return length - 512 if self.short_write else length

    def flush(self) -> None:
        self.flushed = True


def test_overwrite_reports_exact_progress_and_flushes() -> None:
    device = FakeRawDevice(size_bytes=12_288)
    progress: list[tuple[int, int]] = []

    result = overwrite_with_zeros(
        device,
        threading.Event(),
        lambda written, total: progress.append((written, total)),
        expected_size=12_288,
        chunk_size=4096,
    )

    assert device.writes == [(0, 4096), (4096, 4096), (8192, 4096)]
    assert progress == [(0, 12_288), (4096, 12_288), (8192, 12_288), (12_288, 12_288)]
    assert device.flushed
    assert result.bytes_written == 12_288
    assert not result.cancelled


def test_cancellation_stops_before_the_next_chunk_without_flushing() -> None:
    device = FakeRawDevice(size_bytes=8192)
    cancel = threading.Event()

    def report(written: int, total: int) -> None:
        del total
        if written == 4096:
            cancel.set()

    result = overwrite_with_zeros(
        device,
        cancel,
        report,
        expected_size=8192,
        chunk_size=4096,
    )

    assert device.writes == [(0, 4096)]
    assert not device.flushed
    assert result.cancelled
    assert result.bytes_written == 4096


def test_size_change_fails_before_any_write() -> None:
    device = FakeRawDevice(size_bytes=8192)

    with pytest.raises(RawWriteError, match="size changed"):
        overwrite_with_zeros(
            device,
            threading.Event(),
            lambda *_: None,
            expected_size=4096,
            chunk_size=4096,
        )

    assert not device.writes


def test_unaligned_chunk_fails_before_any_write() -> None:
    device = FakeRawDevice()

    with pytest.raises(RawWriteError, match="Chunk size"):
        overwrite_with_zeros(
            device,
            threading.Event(),
            lambda *_: None,
            expected_size=4096,
            chunk_size=512,
        )

    assert not device.writes


def test_short_write_is_fatal_and_is_not_flushed_as_complete() -> None:
    device = FakeRawDevice()
    device.short_write = True

    with pytest.raises(RawWriteError, match="Short raw write"):
        overwrite_with_zeros(
            device,
            threading.Event(),
            lambda *_: None,
            expected_size=4096,
            chunk_size=4096,
        )

    assert not device.flushed
