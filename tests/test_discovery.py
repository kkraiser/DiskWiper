from __future__ import annotations

import subprocess
import json

from diskwiper.disks.discovery import PowerShellDiskDiscovery


def test_discovery_hides_powershell_window_on_windows(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(args[0], 0, b'{"Disks":[]}', b"")

    monkeypatch.setattr("diskwiper.disks.discovery.subprocess.run", fake_run)

    inventory = PowerShellDiskDiscovery().discover()

    assert inventory.disks == ()
    assert captured["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_discovery_preserves_every_partition_access_path(monkeypatch) -> None:
    payload = {
        "Disks": [
            {
                "Number": 4,
                "Model": "Test",
                "SerialNumber": "SERIAL",
                "UniqueId": "UNIQUE",
                "Path": r"\\?\disk",
                "PnpDeviceId": r"USBSTOR\DISK",
                "Size": 4096,
                "BusType": "USB",
                "LogicalSectorSize": 512,
                "PhysicalSectorSize": 4096,
                "NumberOfPartitions": 1,
                "Volumes": [
                    {
                        "DriveLetter": "T",
                        "Path": "T:\\",
                        "AccessPaths": ["T:\\", "\\\\?\\Volume{guid}\\"],
                        "PartitionType": "Basic",
                        "FileSystem": "NTFS",
                        "Size": 4096,
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(
        "diskwiper.disks.discovery.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(payload).encode(), b""
        ),
    )

    volume = PowerShellDiskDiscovery().discover().disks[0].volumes[0]
    assert volume.access_paths == ("T:\\", "\\\\?\\Volume{guid}\\")
    assert volume.partition_type == "Basic"
    assert volume.file_system == "NTFS"


def test_discovery_omits_zero_byte_empty_enclosure_slots(monkeypatch) -> None:
    payload = {
        "Disks": [
            {
                "Number": 3,
                "Model": "ASM235CM",
                "SerialNumber": "TEST-EMPTY-SLOT",
                "Size": 0,
                "BusType": "USB",
                "LogicalSectorSize": 0,
                "PhysicalSectorSize": 0,
            },
            {
                "Number": 4,
                "Model": "Installed HDD",
                "SerialNumber": "PRESENT",
                "Size": 4096,
                "BusType": "USB",
                "LogicalSectorSize": 512,
                "PhysicalSectorSize": 4096,
            },
        ]
    }
    monkeypatch.setattr(
        "diskwiper.disks.discovery.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(payload).encode(), b""
        ),
    )

    inventory = PowerShellDiskDiscovery().discover()

    assert tuple(disk.disk_number for disk in inventory.disks) == (4,)


def test_discovery_keeps_nonempty_disk_with_invalid_geometry_visible(monkeypatch) -> None:
    payload = {
        "Disks": [
            {
                "Number": 7,
                "Model": "Malformed but present",
                "SerialNumber": "PRESENT",
                "Size": 4096,
                "BusType": "USB",
                "LogicalSectorSize": 0,
                "PhysicalSectorSize": 0,
            }
        ]
    }
    monkeypatch.setattr(
        "diskwiper.disks.discovery.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(payload).encode(), b""
        ),
    )

    inventory = PowerShellDiskDiscovery().discover()

    assert tuple(disk.disk_number for disk in inventory.disks) == (7,)
