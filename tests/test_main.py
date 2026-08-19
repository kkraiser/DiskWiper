from __future__ import annotations

import pytest

from diskwiper.main import build_parser


def test_diskpart_remains_the_default_real_backend() -> None:
    args = build_parser().parse_args([])
    assert args.real_backend == "diskpart"

    args = build_parser().parse_args(["--real-backend", "native"])
    assert args.real_backend == "native"

    with pytest.raises(SystemExit):
        build_parser().parse_args(["--real-backend", "unknown"])


def test_native_preflight_accepts_an_explicit_disk_number() -> None:
    args = build_parser().parse_args(["--native-preflight", "4"])
    assert args.native_preflight == 4


def test_native_test_target_is_explicit() -> None:
    args = build_parser().parse_args(
        [
            "--native-test-target",
            "TEST-SERIAL-1:150038863360",
            "--native-test-target",
            "TEST-SERIAL-2:18000207937536",
        ]
    )
    assert args.native_test_target == [
        "TEST-SERIAL-1:150038863360",
        "TEST-SERIAL-2:18000207937536",
    ]
