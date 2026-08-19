import pytest

from diskwiper.disks.benchmark import estimated_wipe_duration


def test_estimated_wipe_duration_uses_midpoint_write_factor() -> None:
    estimate = estimated_wipe_duration(60_000, 100)

    assert estimate == 1_000


def test_estimated_wipe_range_rejects_invalid_measurements() -> None:
    with pytest.raises(ValueError):
        estimated_wipe_duration(100, 0)
