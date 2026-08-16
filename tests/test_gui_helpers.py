from diskwiper.domain.models import DiskStatus, JobStatus
from diskwiper.gui.confirm_dialog import _serial_challenge
from diskwiper.gui.main_window import MainWindow, _status_color
from diskwiper.gui.main_window import _format_read_speed, _format_wipe_estimate


def test_serial_challenge_uses_first_four_characters() -> None:
    assert _serial_challenge(" 21A000000419 ") == "21A0"


def test_ready_and_cancelled_statuses_have_high_contrast_colors() -> None:
    assert _status_color(DiskStatus.READY.value).name() == "#ffffff"
    assert _status_color(JobStatus.CANCELLED_INCOMPLETE.value).name() == "#ffb347"


def test_complete_status_remains_green() -> None:
    assert _status_color(JobStatus.COMPLETE.value).name() == "#39d353"


def test_read_speed_and_wipe_estimate_are_human_readable() -> None:
    assert _format_read_speed(100_000_000) == "100.0 MB/s"
    assert _format_wipe_estimate(120_000_000_000, 100_000_000) == "~25m–~50m"


def test_every_table_column_has_a_bounded_initial_width() -> None:
    assert len(MainWindow.COLUMN_WIDTHS) == len(MainWindow.COLUMNS)
    assert all(width > 0 for width in MainWindow.COLUMN_WIDTHS)


def test_compact_table_headers_and_serial_width() -> None:
    assert "Position" in MainWindow.COLUMNS
    assert "Est." in MainWindow.COLUMNS
    assert MainWindow.COLUMN_WIDTHS[4] == 130


def test_default_window_is_wide_enough_for_configured_columns() -> None:
    assert MainWindow.DEFAULT_WIDTH >= sum(MainWindow.COLUMN_WIDTHS) + 40
