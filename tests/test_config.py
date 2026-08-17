from __future__ import annotations

from diskwiper.config import AppConfig, NATIVE_WIPE_ENV_VALUE, REAL_WIPE_ENV_VALUE


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
        native_test_target="SERIAL:1234",
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
        native_test_target="SERIAL:1234",
    )
    assert not config.real_wipes_enabled


def test_native_requires_an_explicit_test_target(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DISKWIPER_ENABLE_REAL_WIPES", REAL_WIPE_ENV_VALUE)
    monkeypatch.setenv("DISKWIPER_ENABLE_NATIVE_WIPES", NATIVE_WIPE_ENV_VALUE)
    config = AppConfig(tmp_path, real_wipes_requested=True, real_backend="native")
    assert not config.real_wipes_enabled
