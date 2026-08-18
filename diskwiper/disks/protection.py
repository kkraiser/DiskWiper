from __future__ import annotations

import os
import sys
import json
from dataclasses import dataclass, field
from pathlib import Path

from diskwiper.domain.models import (
    DiskAssessment,
    DiskStatus,
    PhysicalDisk,
    normalize_identifier,
)


class ProtectionConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProtectedDevices:
    stable_keys: frozenset[str] = field(default_factory=frozenset)
    serial_numbers: frozenset[str] = field(default_factory=frozenset)
    unique_ids: frozenset[str] = field(default_factory=frozenset)


def add_protected_stable_keys(
    path: Path, stable_keys: set[str] | frozenset[str]
) -> ProtectedDevices:
    """Persist additional exact device fingerprints without dropping existing rules."""
    protected = load_protected_devices(path)
    updated = ProtectedDevices(
        stable_keys=protected.stable_keys
        | frozenset(normalize_identifier(key) for key in stable_keys if key),
        serial_numbers=protected.serial_numbers,
        unique_ids=protected.unique_ids,
    )
    payload = {
        "serial_numbers": sorted(updated.serial_numbers),
        "unique_ids": sorted(updated.unique_ids),
        "stable_keys": sorted(updated.stable_keys),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return updated


def load_protected_devices(path: Path) -> ProtectedDevices:
    if not path.exists():
        return ProtectedDevices()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("top-level value must be an object")

        def values(name: str) -> frozenset[str]:
            raw = payload.get(name, [])
            if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
                raise TypeError(f"{name} must be an array of strings")
            return frozenset(
                normalized
                for item in raw
                if (normalized := normalize_identifier(item))
            )

        return ProtectedDevices(
            stable_keys=values("stable_keys"),
            serial_numbers=values("serial_numbers"),
            unique_ids=values("unique_ids"),
        )
    except (OSError, ValueError, TypeError) as exc:
        raise ProtectionConfigurationError(
            f"Invalid protected-device file {path}: {exc}"
        ) from exc


def _drive_letter(path: str | Path | None) -> str | None:
    if not path:
        return None
    drive, _ = os.path.splitdrive(os.path.abspath(str(path)))
    return drive[:1].upper() if drive else None


def default_critical_drive_letters(data_dir: Path) -> frozenset[str]:
    candidates: list[str | Path | None] = [
        sys.executable,
        Path.cwd(),
        Path.home(),
        data_dir,
        os.environ.get("WINDIR"),
        os.environ.get("USERPROFILE"),
    ]
    return frozenset(
        letter for candidate in candidates if (letter := _drive_letter(candidate))
    )


@dataclass(frozen=True)
class ProtectionPolicy:
    critical_drive_letters: frozenset[str]
    protected_stable_keys: frozenset[str] = field(default_factory=frozenset)
    protected_serial_numbers: frozenset[str] = field(default_factory=frozenset)
    protected_unique_ids: frozenset[str] = field(default_factory=frozenset)
    allowed_bus_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"USB"})
    )

    def assess(
        self,
        disk: PhysicalDisk,
    ) -> DiskAssessment:
        reasons: list[str] = []
        if disk.is_boot:
            reasons.append("Contains the current Windows boot partition")
        if disk.is_system:
            reasons.append("Contains the Windows system partition")
        if disk.boot_from_disk:
            reasons.append("Firmware is configured to boot from this disk")
        if disk.is_clustered:
            reasons.append("Clustered disks are unsupported")
        if disk.is_read_only:
            reasons.append("Disk is read-only")
        if not disk.serial_number.strip():
            reasons.append("No stable serial number was reported")
        if not disk.unique_id.strip():
            reasons.append("No Windows unique disk identifier was reported")
        if not disk.device_path.strip():
            reasons.append("No persistent device path was reported")
        if not disk.pnp_device_id.strip():
            reasons.append("No Plug and Play device identifier was reported")
        if disk.size_bytes <= 0:
            reasons.append("Disk capacity is invalid")
        if disk.logical_sector_size <= 0 or disk.physical_sector_size <= 0:
            reasons.append("Disk sector geometry is invalid")
        if disk.bus_type.upper() not in self.allowed_bus_types:
            reasons.append(f"Bus type {disk.bus_type or 'Unknown'} is not allowed")
        critical = sorted(set(disk.drive_letters) & self.critical_drive_letters)
        if critical:
            reasons.append(
                "Hosts a protected path on " + ", ".join(f"{letter}:" for letter in critical)
            )
        if normalize_identifier(disk.fingerprint.stable_key) in {
            normalize_identifier(key) for key in self.protected_stable_keys
        }:
            reasons.append("Device is on the persistent protected list")
        if normalize_identifier(disk.serial_number) in self.protected_serial_numbers:
            reasons.append("Serial number is on the persistent protected list")
        if normalize_identifier(disk.unique_id) in self.protected_unique_ids:
            reasons.append("Unique ID is on the persistent protected list")

        if reasons:
            status = DiskStatus.PROTECTED
        else:
            status = DiskStatus.READY
        return DiskAssessment(
            disk=disk,
            status=status,
            protection_reasons=tuple(reasons),
        )
