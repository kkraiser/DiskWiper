from __future__ import annotations

import threading
import time
from dataclasses import replace

import pytest

from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import JobStatus
from diskwiper.history.database import HistoryStore
from diskwiper.wipe.backends import BackendError, BackendResult
from diskwiper.wipe.manager import JobManager
from tests.factories import make_disk


class BarrierBackend:
    name = "barrier-simulation"
    simulated = True
    supports_cancel = True

    def __init__(self, barrier: threading.Barrier) -> None:
        self._barrier = barrier

    def run(self, authorization, cancel_event, report):
        del authorization, cancel_event, report
        self._barrier.wait(timeout=2)
        return BackendResult(JobStatus.COMPLETE, "done", 1)


class HeldRealBackend:
    name = "held-real-backend"
    simulated = False
    supports_cancel = False
    supports_parallel_real = False

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, authorization, cancel_event, report):
        del authorization, cancel_event, report
        self.entered.set()
        assert self.release.wait(timeout=2)
        return BackendResult(JobStatus.COMPLETE, "done", 1)


class ProgressThenFailBackend:
    name = "progress-then-fail"
    simulated = False
    supports_cancel = True
    supports_parallel_real = True

    def run(self, authorization, cancel_event, report):
        del cancel_event
        report(JobStatus.WIPING, "writing", 4096, authorization.size_bytes)
        raise BackendError("device disconnected")


def _assessment(disk):
    return ProtectionPolicy(critical_drive_letters=frozenset()).assess(disk)


def _second_disk():
    return replace(
        make_disk(),
        disk_number=9,
        serial_number="SERIAL5678",
        unique_id="USB-UNIQUE-SERIAL5678",
        device_path=r"\\?\usbstor#disk&ven_example#serial5678",
        pnp_device_id=r"USBSTOR\DISK&VEN_EXAMPLE\SERIAL5678",
    )


def test_simulated_jobs_can_enter_backend_in_parallel(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history, max_workers=2)
    barrier = threading.Barrier(3)
    backend = BarrierBackend(barrier)

    manager.start(_assessment(make_disk()), "one", backend)
    manager.start(_assessment(_second_disk()), "two", backend)
    barrier.wait(timeout=2)

    deadline = time.monotonic() + 2
    while manager.active_disk_numbers() and time.monotonic() < deadline:
        time.sleep(0.01)
    manager.shutdown()
    assert not manager.active_disk_numbers()


def test_only_one_real_backend_job_can_be_active(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history, max_workers=2)
    backend = HeldRealBackend()
    manager.start(_assessment(make_disk()), "one", backend)
    assert backend.entered.wait(timeout=2)

    with pytest.raises(ValueError, match="Only parallel-capable native wipes"):
        manager.start(_assessment(_second_disk()), "two", backend)

    backend.release.set()
    manager.shutdown()


def test_active_elapsed_time_advances_without_backend_progress(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history)
    backend = HeldRealBackend()
    disk = make_disk()
    manager.start(_assessment(disk), "one", backend)
    assert backend.entered.wait(timeout=2)

    first = manager.active_elapsed_seconds()[disk.disk_number]
    time.sleep(0.02)
    second = manager.active_elapsed_seconds()[disk.disk_number]

    assert second > first
    backend.release.set()
    manager.shutdown()


def test_manager_reports_backend_cancellation_capability(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history)
    backend = HeldRealBackend()
    disk = make_disk()
    manager.start(_assessment(disk), "one", backend)
    assert backend.entered.wait(timeout=2)

    assert not manager.can_cancel_disk(disk.disk_number)
    assert not manager.can_cancel_disk(999)

    backend.release.set()
    manager.shutdown()


def test_terminal_error_preserves_last_confirmed_byte_count(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history)
    disk = make_disk(size_bytes=8192)
    manager.start(_assessment(disk), "one", ProgressThenFailBackend())
    manager.shutdown()

    terminal = [event for event in manager.drain_events() if event.status is JobStatus.ERROR]
    assert len(terminal) == 1
    assert terminal[0].bytes_processed == 4096
    assert terminal[0].total_bytes == 8192


def test_parallel_capable_real_jobs_can_run_together(tmp_path) -> None:
    history = HistoryStore(tmp_path / "history.sqlite3")
    history.initialize()
    manager = JobManager(history, max_workers=2)
    barrier = threading.Barrier(3)

    class ParallelRealBackend(BarrierBackend):
        name = "parallel-real"
        simulated = False
        supports_parallel_real = True

    backend = ParallelRealBackend(barrier)
    manager.start(_assessment(make_disk()), "one", backend)
    manager.start(_assessment(_second_disk()), "two", backend)
    barrier.wait(timeout=2)
    manager.shutdown()
