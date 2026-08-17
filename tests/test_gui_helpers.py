from diskwiper.domain.models import DiskStatus, JobProgress, JobStatus
from diskwiper.gui.confirm_dialog import _serial_challenge
from diskwiper.gui.main_window import MainWindow, _status_color
from diskwiper.gui.main_window import _format_read_speed, _format_wipe_estimate
from diskwiper.gui.main_window import _format_live_eta, _format_write_speed


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
    assert _format_write_speed(progress) == "100.0 MB/s"
    assert _format_live_eta(progress) == "~1m"


def test_every_table_column_has_a_bounded_initial_width() -> None:
    assert len(MainWindow.COLUMN_WIDTHS) == len(MainWindow.COLUMNS)
    assert all(width > 0 for width in MainWindow.COLUMN_WIDTHS)


def test_compact_table_headers_and_serial_width() -> None:
    assert "Position" in MainWindow.COLUMNS
    assert "Est." in MainWindow.COLUMNS
    assert MainWindow.COLUMN_WIDTHS[4] == 130


def test_default_window_is_wide_enough_for_configured_columns() -> None:
    assert MainWindow.DEFAULT_WIDTH >= sum(MainWindow.COLUMN_WIDTHS) + 40
