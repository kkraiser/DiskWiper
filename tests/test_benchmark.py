import pytest

from diskwiper.disks.benchmark import estimated_wipe_duration_range


def test_estimated_wipe_range_uses_conservative_write_factors() -> None:
    fastest, slowest = estimated_wipe_duration_range(80_000, 100)

    assert fastest == 1_000
    assert slowest == 2_000


def test_estimated_wipe_range_rejects_invalid_measurements() -> None:
    with pytest.raises(ValueError):
        estimated_wipe_duration_range(100, 0)
