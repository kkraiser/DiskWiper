from __future__ import annotations

import argparse
import sys
from pathlib import Path

from diskwiper.config import AppConfig, default_data_dir
from diskwiper.disks.discovery import PowerShellDiskDiscovery
from diskwiper.disks.protection import (
    ProtectionConfigurationError,
    ProtectionPolicy,
    default_critical_drive_letters,
    load_protected_devices,
)
from diskwiper.history.database import HistoryStore
from diskwiper.util.admin import is_administrator
from diskwiper.util.logging import configure_logging
from diskwiper.wipe.backends import DiskPartBackend, RealWipeBackend, SimulationBackend
from diskwiper.wipe.manager import JobManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safety-first Windows HDD wiper")
    parser.add_argument(
        "--enable-real-wipes",
        action="store_true",
        help="Request destructive mode; also requires the backend safety gate(s)",
    )
    parser.add_argument(
        "--real-backend",
        choices=("diskpart", "native"),
        default="diskpart",
        help="Select the destructive backend; native requires an additional safety gate",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Override the application data directory",
    )
    parser.add_argument(
        "--simulation-seconds",
        type=int,
        default=20,
        help="Duration of each simulated wipe",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help="Print a read-only protected/ready disk inventory and exit",
    )
    parser.add_argument(
        "--native-preflight",
        type=int,
        metavar="DISK_NUMBER",
        help="Run read-only native handle and geometry checks for one eligible disk",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.native_preflight is not None and args.enable_real_wipes:
        parser.error("--native-preflight cannot be combined with --enable-real-wipes")
    config = AppConfig(
        data_dir=(args.data_dir or default_data_dir()).resolve(),
        real_wipes_requested=args.enable_real_wipes,
        real_backend=args.real_backend,
        simulation_seconds=max(1, args.simulation_seconds),
    )
    config.data_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(config.log_path)

    discovery = PowerShellDiskDiscovery()
    try:
        protected = load_protected_devices(config.data_dir / "protected_devices.json")
    except ProtectionConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    policy = ProtectionPolicy(
        critical_drive_letters=default_critical_drive_letters(config.data_dir),
        protected_stable_keys=protected.stable_keys,
        protected_serial_numbers=protected.serial_numbers,
        protected_unique_ids=protected.unique_ids,
    )

    if args.inventory_only:
        return _print_inventory(discovery, policy)
    if args.native_preflight is not None:
        return _run_native_preflight(discovery, policy, args.native_preflight)

    if args.enable_real_wipes and not config.real_wipes_enabled:
        print(
            "Real wipes were requested but all required safety gates for the "
            f"{args.real_backend} backend are not set. Starting in simulation mode.",
            file=sys.stderr,
        )
    if config.real_wipes_enabled and not is_administrator():
        print("Destructive mode requires Administrator privileges.", file=sys.stderr)
        return 2

    from PySide6.QtWidgets import QApplication

    from diskwiper.gui.main_window import MainWindow

    history = HistoryStore(config.database_path)
    history.initialize()
    manager = JobManager(history)
    simulation = SimulationBackend(config.simulation_seconds)
    real_backend: RealWipeBackend
    if config.real_backend == "native":
        from diskwiper.wipe.native import NativeRawWriteBackend

        real_backend = NativeRawWriteBackend(
            discovery=discovery,
            protection_policy=policy,
            real_wipes_enabled=config.real_wipes_enabled,
            is_admin=is_administrator,
        )
    else:
        real_backend = DiskPartBackend(
            discovery=discovery,
            protection_policy=policy,
            real_wipes_enabled=config.real_wipes_enabled,
            is_admin=is_administrator,
        )

    application = QApplication(sys.argv[:1])
    application.setApplicationName("DiskWiper")
    window = MainWindow(
        config=config,
        discovery=discovery,
        policy=policy,
        history=history,
        manager=manager,
        simulation_backend=simulation,
        real_backend=real_backend,
    )
    window.show()
    return application.exec()


def _print_inventory(
    discovery: PowerShellDiskDiscovery,
    policy: ProtectionPolicy,
) -> int:
    try:
        inventory = discovery.discover()
    except Exception as exc:
        print(f"Disk discovery failed: {exc}", file=sys.stderr)
        return 1
    for disk in inventory.disks:
        assessment = policy.assess(disk)
        print(
            f"Disk {disk.disk_number}: {assessment.status.value} | "
            f"{disk.model or 'Unknown'} | {disk.serial_number or 'NO SERIAL'} | "
            f"{disk.size_bytes} bytes | {disk.bus_type or 'Unknown'}"
        )
        for reason in assessment.protection_reasons:
            print(f"  - {reason}")
    return 0


def _run_native_preflight(
    discovery: PowerShellDiskDiscovery,
    policy: ProtectionPolicy,
    disk_number: int,
) -> int:
    from diskwiper.wipe.preflight import PreflightError, run_native_preflight

    try:
        result = run_native_preflight(discovery, policy, disk_number)
    except PreflightError as exc:
        print(f"Native preflight failed: {exc}", file=sys.stderr)
        return 1
    geometry = result.geometry
    print("READ-ONLY native preflight passed")
    print(f"Disk: {result.disk_number}")
    print(f"Model: {result.model or 'Unknown'}")
    print(f"Serial: {result.serial_number}")
    print(f"Size: {geometry.size_bytes} bytes")
    print(f"Logical sector: {geometry.logical_sector_size} bytes")
    print(f"Physical sector: {geometry.physical_sector_size} bytes")
    print("No volume locks, dismounts, or writes were requested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
