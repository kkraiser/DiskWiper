from __future__ import annotations

import base64
import json
import os
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from diskwiper.domain.models import PhysicalDisk, VolumeInfo


class DiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiskInventory:
    generation: str
    disks: tuple[PhysicalDisk, ...]

    def disk_by_number(self, disk_number: int) -> PhysicalDisk | None:
        return next(
            (disk for disk in self.disks if disk.disk_number == disk_number), None
        )


class DiskDiscovery(Protocol):
    def discover(self) -> DiskInventory: ...


_DISCOVERY_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [Console]::OutputEncoding
$win32Disks = @(Get-CimInstance -ClassName Win32_DiskDrive)
$items = @(
    Get-Disk | Sort-Object Number | ForEach-Object {
        $disk = $_
        $win32Disk = $win32Disks | Where-Object { $_.Index -eq $disk.Number } | Select-Object -First 1
        $volumeItems = @()
        $partitions = @(Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue)
        foreach ($partition in $partitions) {
            $volume = $partition | Get-Volume -ErrorAction SilentlyContinue
            $accessPaths = @($partition.AccessPaths)
            $volumeItems += [pscustomobject]@{
                DriveLetter = if ($volume) { [string]$volume.DriveLetter } else { $null }
                Label = if ($volume) { [string]$volume.FileSystemLabel } else { $null }
                Path = if ($accessPaths.Count -gt 0) { [string]$accessPaths[0] } else { $null }
                Size = if ($volume) { [uint64]$volume.Size } else { [uint64]$partition.Size }
            }
        }
        [pscustomobject]@{
            Number = [uint32]$disk.Number
            Model = [string]$disk.Model
            Manufacturer = [string]$disk.Manufacturer
            FriendlyName = [string]$disk.FriendlyName
            SerialNumber = [string]$disk.SerialNumber
            UniqueId = [string]$disk.UniqueId
            Path = [string]$disk.Path
            PnpDeviceId = if ($win32Disk) { [string]$win32Disk.PNPDeviceID } else { $null }
            Location = [string]$disk.Location
            Size = [uint64]$disk.Size
            BusType = [string]$disk.BusType
            LogicalSectorSize = [uint32]$disk.LogicalSectorSize
            PhysicalSectorSize = [uint32]$disk.PhysicalSectorSize
            NumberOfPartitions = [uint32]$disk.NumberOfPartitions
            IsBoot = [bool]$disk.IsBoot
            IsSystem = [bool]$disk.IsSystem
            BootFromDisk = [bool]$disk.BootFromDisk
            IsOffline = [bool]$disk.IsOffline
            IsReadOnly = [bool]$disk.IsReadOnly
            IsClustered = [bool]$disk.IsClustered
            PartitionStyle = [string]$disk.PartitionStyle
            HealthStatus = [string]$disk.HealthStatus
            OperationalStatus = @($disk.OperationalStatus | ForEach-Object { [string]$_ })
            Volumes = $volumeItems
        }
    }
)
@{ Disks = $items } | ConvertTo-Json -Depth 6 -Compress
"""


class PowerShellDiskDiscovery:
    def __init__(self, timeout_seconds: int = 30) -> None:
        self._timeout_seconds = timeout_seconds

    def discover(self) -> DiskInventory:
        encoded = base64.b64encode(_DISCOVERY_SCRIPT.encode("utf-16-le")).decode("ascii")
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            completed = subprocess.run(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-EncodedCommand",
                    encoded,
                ],
                check=False,
                capture_output=True,
                timeout=self._timeout_seconds,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DiscoveryError(f"Disk discovery could not start: {exc}") from exc

        stdout = completed.stdout.decode("utf-8-sig", errors="replace").strip()
        stderr = completed.stderr.decode("utf-8-sig", errors="replace").strip()
        if completed.returncode != 0:
            raise DiscoveryError(stderr or f"PowerShell exited with {completed.returncode}")
        if not stdout:
            raise DiscoveryError("PowerShell returned no disk inventory")

        try:
            payload = json.loads(stdout)
            raw_disks = payload.get("Disks", [])
            if isinstance(raw_disks, dict):
                raw_disks = [raw_disks]
            disks = tuple(self._parse_disk(item) for item in raw_disks)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise DiscoveryError(f"Invalid disk inventory: {exc}") from exc

        return DiskInventory(generation=str(uuid.uuid4()), disks=disks)

    @staticmethod
    def _parse_disk(item: dict[str, Any]) -> PhysicalDisk:
        raw_volumes = item.get("Volumes") or []
        if isinstance(raw_volumes, dict):
            raw_volumes = [raw_volumes]
        volumes = tuple(
            VolumeInfo(
                drive_letter=_optional_text(volume.get("DriveLetter")),
                label=_optional_text(volume.get("Label")),
                path=_optional_text(volume.get("Path")),
                size_bytes=_optional_int(volume.get("Size")),
            )
            for volume in raw_volumes
        )
        raw_status = item.get("OperationalStatus") or []
        if isinstance(raw_status, str):
            raw_status = [raw_status]
        return PhysicalDisk(
            disk_number=int(item["Number"]),
            model=_text(item.get("Model") or item.get("FriendlyName")),
            manufacturer=_text(item.get("Manufacturer")),
            serial_number=_text(item.get("SerialNumber")),
            unique_id=_text(item.get("UniqueId")),
            device_path=_text(item.get("Path")),
            pnp_device_id=_text(item.get("PnpDeviceId")),
            location=_text(item.get("Location")),
            size_bytes=int(item.get("Size") or 0),
            bus_type=_text(item.get("BusType")),
            logical_sector_size=int(item.get("LogicalSectorSize") or 0),
            physical_sector_size=int(item.get("PhysicalSectorSize") or 0),
            partition_count=int(item.get("NumberOfPartitions") or 0),
            is_boot=bool(item.get("IsBoot")),
            is_system=bool(item.get("IsSystem")),
            boot_from_disk=bool(item.get("BootFromDisk")),
            is_offline=bool(item.get("IsOffline")),
            is_read_only=bool(item.get("IsReadOnly")),
            is_clustered=bool(item.get("IsClustered")),
            partition_style=_text(item.get("PartitionStyle")),
            health_status=_text(item.get("HealthStatus")),
            operational_status=tuple(_text(value) for value in raw_status),
            volumes=volumes,
        )


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def _optional_text(value: object) -> str | None:
    result = _text(value)
    return result or None


def _optional_int(value: object) -> int | None:
    return None if value is None else int(value)
