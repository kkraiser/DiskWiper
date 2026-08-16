from __future__ import annotations

from diskwiper.domain.models import JobProgress, JobStatus
from diskwiper.history.database import HistoryStore
from tests.test_diskpart import authorization_for
from tests.factories import make_disk


def test_startup_marks_abandoned_job_interrupted(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.initialize()
    job_id = store.start_job(
        authorization_for(make_disk()),
        method="test",
        simulated=False,
        application_version="test",
    )
    store.record_progress(
        JobProgress(
            job_id=job_id,
            status=JobStatus.WIPING,
            disk_number=4,
            elapsed_seconds=1,
            message="running",
        )
    )

    assert store.initialize() == 1


def test_simulation_is_not_reported_as_previous_real_wipe(tmp_path) -> None:
    store = HistoryStore(tmp_path / "history.sqlite3")
    store.initialize()
    authorization = authorization_for(make_disk())
    job_id = store.start_job(
        authorization,
        method="simulation",
        simulated=True,
        application_version="test",
    )
    store.finish_job(
        JobProgress(
            job_id=job_id,
            status=JobStatus.COMPLETE,
            disk_number=4,
            elapsed_seconds=2,
            message="done",
        )
    )

    assert store.last_completed_at(authorization.fingerprint.stable_key) is None
