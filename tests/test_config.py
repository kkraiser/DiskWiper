from __future__ import annotations

import pytest

from diskwiper.config import (
    AppConfig,
    INTERNAL_SATA_ENV_VALUE,
    NATIVE_WIPE_ENV_VALUE,
    REAL_WIPE_ENV_VALUE,
)


@pytest.fixture(autouse=True)
def clear_wipe_gates(monkeypatch) -> None:
    """Configuration tests must not inherit armed gates from the launching shell."""
    for name in (
        "DISKWIPER_ENABLE_REAL_WIPES",
        "DISKWIPER_ENABLE_NATIVE_WIPES",
        "DISKWIPER_ENABLE_INTERNAL_SATA_WIPES",
    ):
        monkeypatch.delenv(name, raising=False)


def test_diskpart_requires_general_gate(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_REAL_WIPES", REAL_WIPE_ENV_VALUE)
    config = AppConfig(tmp_path, real_wipes_requested=True, real_backend="diskpart")
    assert config.real_wipes_enabled


def test_native_requires_both_independent_gates(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_REAL_WIPES", REAL_WIPE_ENV_VALUE)
    config = AppConfig(
        tmp_path,
        real_wipes_requested=True,
        real_backend="native",
        native_test_targets=("SERIAL:1234",),
    )
    assert not config.real_wipes_enabled

    monkeypatch.setenv("DISKWIPER_ENABLE_NATIVE_WIPES", NATIVE_WIPE_ENV_VALUE)
    assert config.real_wipes_enabled


def test_native_gate_does_not_replace_general_gate(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_NATIVE_WIPES", NATIVE_WIPE_ENV_VALUE)
    config = AppConfig(
        tmp_path,
        real_wipes_requested=True,
        real_backend="native",
        native_test_targets=("SERIAL:1234",),
    )
    assert not config.real_wipes_enabled


def test_native_requires_an_explicit_test_target(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_REAL_WIPES", REAL_WIPE_ENV_VALUE)
    monkeypatch.setenv("DISKWIPER_ENABLE_NATIVE_WIPES", NATIVE_WIPE_ENV_VALUE)
    config = AppConfig(tmp_path, real_wipes_requested=True, real_backend="native")
    assert not config.real_wipes_enabled


def test_sata_is_protected_without_its_independent_gate(tmp_path) -> None:
    config = AppConfig(tmp_path)

    assert not config.internal_sata_wipes_enabled
    assert config.allowed_bus_types == frozenset({"USB"})


def test_exact_sata_gate_adds_sata_without_enabling_destructive_mode(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_INTERNAL_SATA_WIPES", INTERNAL_SATA_ENV_VALUE)
    config = AppConfig(tmp_path)

    assert config.internal_sata_wipes_enabled
    assert config.allowed_bus_types == frozenset({"USB", "SATA"})
    assert not config.real_wipes_enabled


def test_inexact_sata_gate_fails_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_INTERNAL_SATA_WIPES", "yes")

    assert AppConfig(tmp_path).allowed_bus_types == frozenset({"USB"})
