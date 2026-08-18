from pathlib import Path

import json

import pytest

from diskwiper.disks.protection import (
    ProtectionConfigurationError,
    ProtectionPolicy,
    add_protected_stable_keys,
    load_protected_devices,
)
from diskwiper.domain.models import DiskStatus, VolumeInfo
from tests.factories import make_disk


def policy() -> ProtectionPolicy:
    return ProtectionPolicy(critical_drive_letters=frozenset({"C", "D"}))


def test_external_disk_with_complete_identity_is_ready() -> None:
    assessment = policy().assess(make_disk())

    assert assessment.status is DiskStatus.READY
    assert assessment.can_wipe


def test_eligible_disk_status_does_not_claim_historical_media_identity() -> None:
    """History cannot identify replacement media behind a bay-identity bridge."""
    assessment = policy().assess(make_disk())

    assert assessment.status is DiskStatus.READY


def test_boot_and_system_flags_are_independent_blocks() -> None:
    for changes in (
        {"is_boot": True},
        {"is_system": True},
        {"boot_from_disk": True},
    ):
        assessment = policy().assess(make_disk(**changes))
        assert assessment.status is DiskStatus.PROTECTED
        assert not assessment.can_wipe


def test_disk_hosting_critical_drive_letter_is_blocked() -> None:
    disk = make_disk(volumes=(VolumeInfo(drive_letter="D"),))

    assessment = policy().assess(disk)

    assert assessment.status is DiskStatus.PROTECTED
    assert any("protected path" in reason for reason in assessment.protection_reasons)


def test_incomplete_identity_fails_closed() -> None:
    assessment = policy().assess(
        make_disk(serial_number="", unique_id="", device_path="")
    )

    assert assessment.status is DiskStatus.PROTECTED
    assert len(assessment.protection_reasons) >= 3


def test_non_usb_disk_is_blocked_by_default() -> None:
    assessment = policy().assess(make_disk(bus_type="SATA"))

    assert assessment.status is DiskStatus.PROTECTED
    assert "Bus type SATA is not allowed" in assessment.protection_reasons


def test_sata_disk_can_be_allowed_without_bypassing_other_protections() -> None:
    sata_policy = ProtectionPolicy(
        critical_drive_letters=frozenset({"C"}),
        allowed_bus_types=frozenset({"USB", "SATA"}),
    )

    assert sata_policy.assess(make_disk(bus_type="SATA")).can_wipe
    protected = sata_policy.assess(
        make_disk(bus_type="SATA", is_system=True, volumes=(VolumeInfo("C"),))
    )
    assert not protected.can_wipe
    assert "Contains the Windows system partition" in protected.protection_reasons
    assert any("protected path" in reason for reason in protected.protection_reasons)


def test_persistent_protected_identity_is_blocked() -> None:
    disk = make_disk()
    protected_policy = ProtectionPolicy(
        critical_drive_letters=frozenset(),
        protected_stable_keys=frozenset({disk.fingerprint.stable_key}),
    )

    assessment = protected_policy.assess(disk)

    assert assessment.status is DiskStatus.PROTECTED
    assert "Device is on the persistent protected list" in assessment.protection_reasons


def test_persistent_serial_protection_is_normalized() -> None:
    assessment = ProtectionPolicy(
        critical_drive_letters=frozenset(),
        protected_serial_numbers=frozenset({"SERIAL1234"}),
    ).assess(make_disk(serial_number=" serial1234 "))

    assert assessment.status is DiskStatus.PROTECTED
    assert "Serial number is on the persistent protected list" in assessment.protection_reasons


def test_protected_device_file_fails_closed_when_malformed(tmp_path) -> None:
    path = tmp_path / "protected_devices.json"
    path.write_text(json.dumps({"serial_numbers": "not-an-array"}), encoding="utf-8")

    with pytest.raises(ProtectionConfigurationError):
        load_protected_devices(path)


def test_stable_key_loaded_from_file_matches_generated_key(tmp_path) -> None:
    disk = make_disk()
    path = tmp_path / "protected_devices.json"
    path.write_text(
        json.dumps({"stable_keys": [disk.fingerprint.stable_key]}),
        encoding="utf-8",
    )
    protected = load_protected_devices(path)
    assessment = ProtectionPolicy(
        critical_drive_letters=frozenset(),
        protected_stable_keys=protected.stable_keys,
    ).assess(disk)

    assert assessment.status is DiskStatus.PROTECTED


def test_adding_protection_preserves_existing_rules(tmp_path) -> None:
    path = tmp_path / "protected_devices.json"
    path.write_text(
        json.dumps(
            {
                "serial_numbers": ["KEEP-SERIAL"],
                "unique_ids": ["KEEP-UNIQUE"],
                "stable_keys": ["KEEP-KEY"],
            }
        ),
        encoding="utf-8",
    )

    updated = add_protected_stable_keys(path, {"new-key"})
    reloaded = load_protected_devices(path)

    assert updated == reloaded
    assert reloaded.stable_keys == frozenset({"KEEP-KEY", "NEW-KEY"})
    assert reloaded.serial_numbers == frozenset({"KEEP-SERIAL"})
    assert reloaded.unique_ids == frozenset({"KEEP-UNIQUE"})
