from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_identifier(value: str | None) -> str:
    return " ".join((value or "").strip().upper().split())


class DiskStatus(StrEnum):
    PROTECTED = "PROTECTED"
    READY = "READY"
    PREVIOUSLY_WIPED = "PREVIOUSLY WIPED"


class JobStatus(StrEnum):
    CONFIRMING = "CONFIRMING"
    PREPARING = "PREPARING"
    WIPING = "WIPING"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    CANCELLED_INCOMPLETE = "CANCELLED / INCOMPLETE"
    INTERRUPTED = "INTERRUPTED"
    DISCONNECTED_INCOMPLETE = "DISCONNECTED / INCOMPLETE"
    ERROR = "ERROR"


@dataclass(frozen=True)
class VolumeInfo:
    drive_letter: str | None = None
    label: str | None = None
    path: str | None = None
    size_bytes: int | None = None


@dataclass(frozen=True)
class DiskFingerprint:
    serial_number: str
    unique_id: str
    device_path: str
    pnp_device_id: str
    size_bytes: int
    logical_sector_size: int
    physical_sector_size: int

    @property
    def stable_key(self) -> str:
        canonical = "|".join(
            (
                normalize_identifier(self.serial_number),
                normalize_identifier(self.unique_id),
                normalize_identifier(self.device_path),
                normalize_identifier(self.pnp_device_id),
                str(self.size_bytes),
                str(self.logical_sector_size),
                str(self.physical_sector_size),
            )
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def matches(self, other: DiskFingerprint) -> bool:
        return self.stable_key == other.stable_key


@dataclass(frozen=True)
class PhysicalDisk:
    disk_number: int
    model: str
    manufacturer: str
    serial_number: str
    unique_id: str
    device_path: str
    pnp_device_id: str
    location: str
    size_bytes: int
    bus_type: str
    logical_sector_size: int
    physical_sector_size: int
    partition_count: int
    is_boot: bool
    is_system: bool
    boot_from_disk: bool
    is_offline: bool
    is_read_only: bool
    is_clustered: bool
    partition_style: str
    health_status: str
    operational_status: tuple[str, ...] = ()
    volumes: tuple[VolumeInfo, ...] = ()

    @property
    def fingerprint(self) -> DiskFingerprint:
        return DiskFingerprint(
            serial_number=self.serial_number,
            unique_id=self.unique_id,
            device_path=self.device_path,
            pnp_device_id=self.pnp_device_id,
            size_bytes=self.size_bytes,
            logical_sector_size=self.logical_sector_size,
            physical_sector_size=self.physical_sector_size,
        )

    @property
    def drive_letters(self) -> tuple[str, ...]:
        return tuple(
            volume.drive_letter.upper()
            for volume in self.volumes
            if volume.drive_letter
        )

    @property
    def enclosure_position(self) -> str | None:
        """Return a USB enclosure bay label when Windows exposes one."""
        if normalize_identifier(self.bus_type) != "USB":
            return None
        match = re.search(r"\bFUNCTION\s+(\d+)\b", self.location, re.IGNORECASE)
        if match is None:
            return None
        position = int(match.group(1))
        return f"P{position}" if position > 0 else None


@dataclass(frozen=True)
class DiskAssessment:
    disk: PhysicalDisk
    status: DiskStatus
    protection_reasons: tuple[str, ...] = ()
    previously_wiped_at: datetime | None = None

    @property
    def can_wipe(self) -> bool:
        return not self.protection_reasons


@dataclass(frozen=True)
class WipeAuthorization:
    fingerprint: DiskFingerprint
    disk_number: int
    model: str
    serial_number: str
    size_bytes: int
    inventory_generation: str
    authorized_at: datetime = field(default_factory=utc_now)


@dataclass(frozen=True)
class JobProgress:
    job_id: str
    status: JobStatus
    disk_number: int
    elapsed_seconds: float
    stable_key: str = ""
    message: str = ""
    bytes_processed: int | None = None
    total_bytes: int | None = None
