from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from diskwiper.domain.models import JobProgress, JobStatus, WipeAuthorization


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class HistoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> int:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    stable_key TEXT NOT NULL,
                    disk_number INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    serial_number TEXT NOT NULL,
                    capacity_bytes INTEGER NOT NULL,
                    method TEXT NOT NULL,
                    simulated INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_seconds REAL,
                    bytes_processed INTEGER,
                    result_message TEXT,
                    fingerprint_json TEXT NOT NULL,
                    application_version TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS ix_jobs_stable_key
                ON jobs(stable_key, completed_at);

                CREATE TABLE IF NOT EXISTS job_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    occurred_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    bytes_processed INTEGER
                );
                """
            )
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, result_message = ?
                WHERE status IN (?, ?, ?)
                """,
                (
                    JobStatus.INTERRUPTED.value,
                    _iso_now(),
                    "Application exited before the job reached a terminal state",
                    JobStatus.PREPARING.value,
                    JobStatus.WIPING.value,
                    JobStatus.VERIFYING.value,
                ),
            )
            return cursor.rowcount

    def start_job(
        self,
        authorization: WipeAuthorization,
        method: str,
        simulated: bool,
        application_version: str,
    ) -> str:
        job_id = str(uuid.uuid4())
        fingerprint = {
            "serial_number": authorization.fingerprint.serial_number,
            "unique_id": authorization.fingerprint.unique_id,
            "device_path": authorization.fingerprint.device_path,
            "pnp_device_id": authorization.fingerprint.pnp_device_id,
            "size_bytes": authorization.fingerprint.size_bytes,
            "logical_sector_size": authorization.fingerprint.logical_sector_size,
            "physical_sector_size": authorization.fingerprint.physical_sector_size,
        }
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, stable_key, disk_number, model, serial_number,
                    capacity_bytes, method, simulated, status, started_at,
                    fingerprint_json, application_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    authorization.fingerprint.stable_key,
                    authorization.disk_number,
                    authorization.model,
                    authorization.serial_number,
                    authorization.size_bytes,
                    method,
                    int(simulated),
                    JobStatus.PREPARING.value,
                    _iso_now(),
                    json.dumps(fingerprint, sort_keys=True),
                    application_version,
                ),
            )
        return job_id

    def record_progress(self, progress: JobProgress) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO job_events (
                    job_id, occurred_at, status, message, bytes_processed
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    progress.job_id,
                    _iso_now(),
                    progress.status.value,
                    progress.message,
                    progress.bytes_processed,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, bytes_processed = ?, result_message = ?
                WHERE job_id = ?
                """,
                (
                    progress.status.value,
                    progress.bytes_processed,
                    progress.message,
                    progress.job_id,
                ),
            )

    def finish_job(self, progress: JobProgress) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO job_events (
                    job_id, occurred_at, status, message, bytes_processed
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    progress.job_id,
                    _iso_now(),
                    progress.status.value,
                    progress.message,
                    progress.bytes_processed,
                ),
            )
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, completed_at = ?, duration_seconds = ?,
                    bytes_processed = ?, result_message = ?
                WHERE job_id = ?
                """,
                (
                    progress.status.value,
                    _iso_now(),
                    progress.elapsed_seconds,
                    progress.bytes_processed,
                    progress.message,
                    progress.job_id,
                ),
            )

    def last_completed_at(self, stable_key: str) -> datetime | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT completed_at
                FROM jobs
                WHERE stable_key = ? AND status = ? AND simulated = 0
                ORDER BY completed_at DESC
                LIMIT 1
                """,
                (stable_key, JobStatus.COMPLETE.value),
            ).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()
