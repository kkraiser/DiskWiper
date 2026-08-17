from __future__ import annotations

import pytest

from diskwiper.main import build_parser


def test_diskpart_remains_the_default_real_backend() -> None:
    args = build_parser().parse_args([])
    assert args.real_backend == "diskpart"


def test_native_backend_requires_explicit_parser_selection() -> None:
    args = build_parser().parse_args(["--real-backend", "native"])
    assert args.real_backend == "native"


def test_unknown_real_backend_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--real-backend", "unknown"])


def test_native_preflight_accepts_an_explicit_disk_number() -> None:
    args = build_parser().parse_args(["--native-preflight", "4"])
    assert args.native_preflight == 4
