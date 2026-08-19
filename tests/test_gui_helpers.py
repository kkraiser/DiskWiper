import pytest

from diskwiper.domain.models import DiskStatus, JobProgress, JobStatus
from diskwiper.gui.confirm_dialog import _serial_challenge
from diskwiper.gui.main_window import MainWindow, _copy_log_snapshot, _status_color
from diskwiper.gui.main_window import _format_read_speed, _format_wipe_estimate
from diskwiper.gui.main_window import _format_job_time, _format_live_eta, _format_write_speed


def test_serial_challenge_uses_first_four_characters() -> None:
    assert _serial_challenge(" 21A000000419 ") == "21A0"


def test_ready_and_cancelled_statuses_have_high_contrast_colors() -> None:
    assert _status_color(DiskStatus.READY.value).name() == "#ffffff"
    assert _status_color(JobStatus.CANCELLED_INCOMPLETE.value).name() == "#ffb347"


def test_complete_status_remains_green() -> None:
    assert _status_color(JobStatus.COMPLETE.value).name() == "#39d353"


def test_read_speed_and_wipe_estimate_are_human_readable() -> None:
    assert _format_read_speed(100_000_000) == "100.0 MB/s"
    assert _format_wipe_estimate(120_000_000_000, 100_000_000) == "~33m"


def test_live_write_speed_and_eta_use_confirmed_progress() -> None:
    progress = JobProgress(
        job_id="job",
        status=JobStatus.WIPING,
        disk_number=4,
        elapsed_seconds=10,
        bytes_processed=1_000_000_000,
        total_bytes=7_000_000_000,
    )
    assert _format_write_speed(progress, 110_000_000) == "110.0 (100.0 avg.) MB/s"
    assert _format_live_eta(progress) == "~1m"
    assert _format_job_time(progress) == "0m (~1m)"


def test_completed_job_shows_final_time_and_average_speed() -> None:
    progress = JobProgress(
        job_id="job",
        status=JobStatus.COMPLETE,
        disk_number=5,
        elapsed_seconds=97_248,
        bytes_processed=18_000_000_000_000,
        total_bytes=18_000_000_000_000,
    )
    assert _format_write_speed(progress, 200_000_000) == "185.1 avg. MB/s"
    assert _format_job_time(progress) == "27h 01m (Done)"


def test_time_before_wipe_shows_only_initial_estimate() -> None:
    assert _format_job_time(None, 120 * 60) == "— (~2h 00m)"


def test_every_table_column_has_a_bounded_initial_width() -> None:
    assert len(MainWindow.COLUMN_WIDTHS) == len(MainWindow.COLUMNS)
    assert all(width > 0 for width in MainWindow.COLUMN_WIDTHS)


def test_compact_table_headers_and_serial_width() -> None:
    assert "Position" in MainWindow.COLUMNS
    assert "Time: Total (Remaining)" in MainWindow.COLUMNS
    assert "Speed: Current (Avg.)" in MainWindow.COLUMNS
    assert MainWindow.COLUMN_WIDTHS[4] == 130


def test_default_window_is_wide_enough_for_configured_columns() -> None:
    assert MainWindow.DEFAULT_WIDTH >= sum(MainWindow.COLUMN_WIDTHS) + 40


def test_default_window_reserves_vertical_space_for_bounded_activity_log() -> None:
    assert MainWindow.DEFAULT_HEIGHT >= 720
    assert 100 <= MainWindow.ACTIVITY_MAX_BLOCKS <= 1_000


def test_log_snapshot_copies_the_entire_current_file(tmp_path) -> None:
    source = tmp_path / "diskwiper.log"
    destination = tmp_path / "saved" / "test-run.log"
    source.write_text("first line\nlast line\n", encoding="utf-8")

    result = _copy_log_snapshot(source, destination)

    assert result == destination
    assert destination.read_text(encoding="utf-8") == "first line\nlast line\n"


def test_log_snapshot_rejects_overwriting_the_active_log(tmp_path) -> None:
    source = tmp_path / "diskwiper.log"
    source.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="active log"):
        _copy_log_snapshot(source, source)
