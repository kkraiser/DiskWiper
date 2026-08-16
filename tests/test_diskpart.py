from __future__ import annotations

import subprocess
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from diskwiper.disks.discovery import DiskInventory
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import JobStatus, WipeAuthorization
from diskwiper.wipe.backends import BackendError, DiskPartBackend
from tests.factories import make_disk


class SequenceDiscovery:
    def __init__(self, *inventories: DiskInventory) -> None:
        self._inventories = list(inventories)

    def discover(self) -> DiskInventory:
        return self._inventories.pop(0)


def inventory(disk, generation="generation") -> DiskInventory:
    return DiskInventory(generation=generation, disks=(disk,))


def authorization_for(disk) -> WipeAuthorization:
    return WipeAuthorization(
        fingerprint=disk.fingerprint,
        disk_number=disk.disk_number,
        model=disk.model,
        serial_number=disk.serial_number,
        size_bytes=disk.size_bytes,
        inventory_generation="generation",
    )


def reporter(*_args) -> None:
    return None


def test_script_is_minimal_and_selects_explicit_disk() -> None:
    assert DiskPartBackend.script_for(4) == (
        "select disk 4\ndetail disk\nclean all\nexit\n"
    )


def test_real_wipe_gate_rejects_before_discovery_or_process() -> None:
    invoked = False

    def runner(_path: Path):
        nonlocal invoked
        invoked = True
        return subprocess.CompletedProcess([], 0, b"", b"")

    disk = make_disk()
    backend = DiskPartBackend(
        discovery=SequenceDiscovery(inventory(disk)),
        protection_policy=ProtectionPolicy(frozenset()),
        real_wipes_enabled=False,
        is_admin=lambda: True,
        process_runner=runner,
    )

    with pytest.raises(BackendError, match="gate is disabled"):
        backend.run(authorization_for(disk), threading.Event(), reporter)
    assert not invoked


def test_identity_change_rejects_before_process() -> None:
    original = make_disk()
    replacement = make_disk(serial_number="DIFFERENT9999")
    invoked = False

    def runner(_path: Path):
        nonlocal invoked
        invoked = True
        return subprocess.CompletedProcess([], 0, b"", b"")

    backend = DiskPartBackend(
        discovery=SequenceDiscovery(inventory(replacement)),
        protection_policy=ProtectionPolicy(frozenset()),
        real_wipes_enabled=True,
        is_admin=lambda: True,
        process_runner=runner,
    )

    with pytest.raises(BackendError, match="identity changed"):
        backend.run(authorization_for(original), threading.Event(), reporter)
    assert not invoked


def test_success_requires_zero_partitions_after_diskpart() -> None:
    before = make_disk(partition_count=1)
    after = replace(before, partition_count=0, volumes=())
    captured_script = ""

    def runner(path: Path):
        nonlocal captured_script
        captured_script = path.read_text(encoding="ascii")
        return subprocess.CompletedProcess([], 0, b"DiskPart succeeded", b"")

    backend = DiskPartBackend(
        discovery=SequenceDiscovery(inventory(before), inventory(after)),
        protection_policy=ProtectionPolicy(frozenset()),
        real_wipes_enabled=True,
        is_admin=lambda: True,
        process_runner=runner,
    )

    result = backend.run(authorization_for(before), threading.Event(), reporter)

    assert result.status is JobStatus.COMPLETE
    assert "clean all" in captured_script


def test_partitions_remaining_causes_failure() -> None:
    disk = make_disk(partition_count=1)
    backend = DiskPartBackend(
        discovery=SequenceDiscovery(inventory(disk), inventory(disk)),
        protection_policy=ProtectionPolicy(frozenset()),
        real_wipes_enabled=True,
        is_admin=lambda: True,
        process_runner=lambda _path: subprocess.CompletedProcess([], 0, b"ok", b""),
    )

    with pytest.raises(BackendError, match="found 1 partition"):
        backend.run(authorization_for(disk), threading.Event(), reporter)

