from __future__ import annotations

from dataclasses import replace

from diskwiper.domain.models import PhysicalDisk, VolumeInfo


def make_disk(**changes) -> PhysicalDisk:
    disk = PhysicalDisk(
        disk_number=4,
        model="Test HDD",
        manufacturer="Example",
        serial_number="SERIAL1234",
        unique_id="USB-UNIQUE-SERIAL1234",
        device_path=r"\\?\usbstor#disk&ven_example#serial1234",
        pnp_device_id=r"USBSTOR\DISK&VEN_EXAMPLE\SERIAL1234",
        location="USBROOT(0)#USB(1)",
        size_bytes=500_000_000_000,
        bus_type="USB",
        logical_sector_size=512,
        physical_sector_size=4096,
        partition_count=1,
        is_boot=False,
        is_system=False,
        boot_from_disk=False,
        is_offline=False,
        is_read_only=False,
        is_clustered=False,
        partition_style="GPT",
        health_status="Healthy",
        operational_status=("Online",),
        volumes=(VolumeInfo(drive_letter="T", label="TEST", size_bytes=500_000_000_000),),
    )
    return replace(disk, **changes)
