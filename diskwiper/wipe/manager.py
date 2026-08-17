from __future__ import annotations

import logging
import queue
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from diskwiper import __version__
from diskwiper.domain.models import (
    DiskAssessment,
    JobProgress,
    JobStatus,
    WipeAuthorization,
)
from diskwiper.history.database import HistoryStore
from diskwiper.wipe.backends import BackendError, WipeBackend


logger = logging.getLogger(__name__)


@dataclass
class _ActiveJob:
    job_id: str
    disk_number: int
    backend: WipeBackend
    cancel_event: threading.Event
    future: Future[None]
    started_monotonic: float


class JobManager:
    def __init__(self, history: HistoryStore, max_workers: int = 8) -> None:
        self._history = history
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="diskwiper-job",
        )
        self._events: queue.SimpleQueue[JobProgress] = queue.SimpleQueue()
        self._active: dict[str, _ActiveJob] = {}
        self._lock = threading.Lock()

    def start(
        self,
        assessment: DiskAssessment,
        inventory_generation: str,
        backend: WipeBackend,
    ) -> str:
        if not assessment.can_wipe:
            raise ValueError("Protected disks cannot be submitted")
        with self._lock:
            if any(
                job.disk_number == assessment.disk.disk_number
                for job in self._active.values()
            ):
                raise ValueError("This disk already has an active job")
            if not backend.simulated and any(
                not job.backend.simulated for job in self._active.values()
            ):
                active_real = next(
                    job.backend
                    for job in self._active.values()
                    if not job.backend.simulated
                )
                if not (
                    getattr(backend, "supports_parallel_real", False)
                    and getattr(active_real, "supports_parallel_real", False)
                ):
                    raise ValueError("Only parallel-capable native wipes may overlap")

            disk = assessment.disk
            authorization = WipeAuthorization(
                fingerprint=disk.fingerprint,
                disk_number=disk.disk_number,
                model=disk.model,
                serial_number=disk.serial_number,
                size_bytes=disk.size_bytes,
                inventory_generation=inventory_generation,
            )
            job_id = self._history.start_job(
                authorization,
                method=backend.name,
                simulated=backend.simulated,
                application_version=__version__,
            )
            cancel_event = threading.Event()
            started_monotonic = time.monotonic()
            future = self._executor.submit(
                self._run_job,
                job_id,
                authorization,
                backend,
                cancel_event,
            )
            self._active[job_id] = _ActiveJob(
                job_id=job_id,
                disk_number=disk.disk_number,
                backend=backend,
                cancel_event=cancel_event,
                future=future,
                started_monotonic=started_monotonic,
            )
            future.add_done_callback(lambda _: self._forget(job_id))
            return job_id

    def cancel_disk(self, disk_number: int) -> bool:
        with self._lock:
            job = next(
                (job for job in self._active.values() if job.disk_number == disk_number),
                None,
            )
            if job is None or not job.backend.supports_cancel:
                return False
            job.cancel_event.set()
            return True

    def active_disk_numbers(self) -> frozenset[int]:
        with self._lock:
            return frozenset(job.disk_number for job in self._active.values())

    def can_cancel_disk(self, disk_number: int) -> bool:
        with self._lock:
            return any(
                job.disk_number == disk_number and job.backend.supports_cancel
                for job in self._active.values()
            )

    def active_elapsed_seconds(self) -> dict[int, float]:
        now = time.monotonic()
        with self._lock:
            return {
                job.disk_number: now - job.started_monotonic
                for job in self._active.values()
            }

    def drain_events(self) -> list[JobProgress]:
        events: list[JobProgress] = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _run_job(
        self,
        job_id: str,
        authorization: WipeAuthorization,
        backend: WipeBackend,
        cancel_event: threading.Event,
    ) -> None:
        started = time.monotonic()
        last_bytes_processed: int | None = 0
        last_total_bytes: int | None = authorization.size_bytes

        def report(
            status: JobStatus,
            message: str,
            bytes_processed: int | None,
            total_bytes: int | None,
        ) -> None:
            nonlocal last_bytes_processed, last_total_bytes
            if bytes_processed is not None:
                last_bytes_processed = bytes_processed
            if total_bytes is not None:
                last_total_bytes = total_bytes
            progress = JobProgress(
                job_id=job_id,
                status=status,
                disk_number=authorization.disk_number,
                elapsed_seconds=time.monotonic() - started,
                stable_key=authorization.fingerprint.stable_key,
                message=message,
                bytes_processed=bytes_processed,
                total_bytes=total_bytes,
            )
            self._history.record_progress(progress)
            self._events.put(progress)

        report(JobStatus.PREPARING, "Job accepted", 0, authorization.size_bytes)
        try:
            result = backend.run(authorization, cancel_event, report)
            terminal = JobProgress(
                job_id=job_id,
                status=result.status,
                disk_number=authorization.disk_number,
                elapsed_seconds=time.monotonic() - started,
                stable_key=authorization.fingerprint.stable_key,
                message=result.message,
                bytes_processed=result.bytes_processed,
                total_bytes=authorization.size_bytes,
            )
        except BackendError as exc:
            logger.error("Wipe job %s rejected or failed: %s", job_id, exc)
            terminal = JobProgress(
                job_id=job_id,
                status=JobStatus.ERROR,
                disk_number=authorization.disk_number,
                elapsed_seconds=time.monotonic() - started,
                stable_key=authorization.fingerprint.stable_key,
                message=str(exc),
                bytes_processed=last_bytes_processed,
                total_bytes=last_total_bytes,
            )
        except Exception as exc:  # defensive job boundary
            logger.exception("Unexpected wipe worker failure")
            terminal = JobProgress(
                job_id=job_id,
                status=JobStatus.ERROR,
                disk_number=authorization.disk_number,
                elapsed_seconds=time.monotonic() - started,
                stable_key=authorization.fingerprint.stable_key,
                message=f"Unexpected worker failure: {exc}",
                bytes_processed=last_bytes_processed,
                total_bytes=last_total_bytes,
            )
        self._history.finish_job(terminal)
        self._events.put(terminal)

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._active.pop(job_id, None)
