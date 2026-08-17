from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, Protocol

from diskwiper.disks.discovery import DiskDiscovery, DiscoveryError
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import DiskFingerprint, PhysicalDisk
from diskwiper.wipe.raw import RawWriteError
from diskwiper.wipe.win32 import DeviceGeometry, WindowsRawDiskProbe


class PreflightError(RuntimeError):
    pass


class ProbeContext(AbstractContextManager[object], Protocol):
    geometry: DeviceGeometry


ProbeFactory = Callable[[int], ProbeContext]


@dataclass(frozen=True)
class PreflightResult:
    disk_number: int
    model: str
    serial_number: str
    geometry: DeviceGeometry


def run_native_preflight(
    discovery: DiskDiscovery,
    policy: ProtectionPolicy,
    disk_number: int,
    *,
    probe_factory: ProbeFactory = WindowsRawDiskProbe,
) -> PreflightResult:
    """Validate native raw-device discovery using read-only access only."""
    before = _eligible_disk(discovery, policy, disk_number)
    expected = before.fingerprint
    try:
        with probe_factory(disk_number) as probe:
            _compare_geometry(expected, probe.geometry)
    except RawWriteError as exc:
        raise PreflightError(f"Read-only raw-device probe failed: {exc}") from exc

    after = _eligible_disk(discovery, policy, disk_number)
    if not expected.matches(after.fingerprint):
        raise PreflightError("Disk identity changed during read-only preflight")
    return PreflightResult(
        disk_number=disk_number,
        model=after.model,
        serial_number=after.serial_number,
        geometry=DeviceGeometry(
            after.size_bytes,
            after.logical_sector_size,
            after.physical_sector_size,
        ),
    )


def _eligible_disk(
    discovery: DiskDiscovery, policy: ProtectionPolicy, disk_number: int
) -> PhysicalDisk:
    try:
        inventory = discovery.discover()
    except DiscoveryError as exc:
        raise PreflightError(f"Disk discovery failed: {exc}") from exc
    disk = inventory.disk_by_number(disk_number)
    if disk is None:
        raise PreflightError(f"Disk {disk_number} is not present")
    assessment = policy.assess(disk)
    if not assessment.can_wipe:
        raise PreflightError(
            "Disk is protected: " + "; ".join(assessment.protection_reasons)
        )
    return disk


def _compare_geometry(expected: DiskFingerprint, actual: DeviceGeometry) -> None:
    differences: list[str] = []
    if actual.size_bytes != expected.size_bytes:
        differences.append(f"size {actual.size_bytes} != {expected.size_bytes}")
    if actual.logical_sector_size != expected.logical_sector_size:
        differences.append(
            "logical sector size "
            f"{actual.logical_sector_size} != {expected.logical_sector_size}"
        )
    if actual.physical_sector_size != expected.physical_sector_size:
        differences.append(
            "physical sector size "
            f"{actual.physical_sector_size} != {expected.physical_sector_size}"
        )
    if differences:
        raise PreflightError("Raw-device geometry mismatch: " + "; ".join(differences))
