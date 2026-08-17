from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from typing import Callable, Iterable, Protocol

from diskwiper.disks.discovery import DiskDiscovery, DiscoveryError
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import JobStatus, PhysicalDisk, WipeAuthorization
from diskwiper.wipe.backends import BackendError, BackendResult, StatusReporter
from diskwiper.wipe.raw import RawWriteDevice, RawWriteError, overwrite_with_zeros
from diskwiper.wipe.win32 import LockedVolumes, WindowsRawDisk, volume_device_path


class RawDiskContext(RawWriteDevice, AbstractContextManager[RawWriteDevice], Protocol):
    pass


RawDiskFactory = Callable[[int], RawDiskContext]
VolumeLocker = Callable[[Iterable[str]], AbstractContextManager[object]]


class NativeRawWriteBackend:
    name = "native-zero-overwrite"
    simulated = False
    supports_cancel = True

    def __init__(
        self,
        discovery: DiskDiscovery,
        protection_policy: ProtectionPolicy,
        real_wipes_enabled: bool,
        is_admin: Callable[[], bool],
        *,
        raw_disk_factory: RawDiskFactory = WindowsRawDisk,
        volume_locker: VolumeLocker = LockedVolumes,
        chunk_size: int = 16 * 1024 * 1024,
    ) -> None:
        self._discovery = discovery
        self._policy = protection_policy
        self._real_wipes_enabled = real_wipes_enabled
        self._is_admin = is_admin
        self._raw_disk_factory = raw_disk_factory
        self._volume_locker = volume_locker
        self._chunk_size = chunk_size

    def run(
        self,
        authorization: WipeAuthorization,
        cancel_event: threading.Event,
        report: StatusReporter,
    ) -> BackendResult:
        if not self._real_wipes_enabled:
            raise BackendError("Real wipe gate is disabled")
        if not self._is_admin():
            raise BackendError("Administrator privileges are required")

        report(JobStatus.PREPARING, "Revalidating disk identity and protection", 0, None)
        disk = self._revalidate(authorization)
        volume_paths = _lockable_volume_paths(disk)

        try:
            with self._volume_locker(volume_paths):
                report(
                    JobStatus.PREPARING,
                    "Volumes locked; revalidating disk identity",
                    0,
                    authorization.size_bytes,
                )
                locked_disk = self._revalidate(authorization)
                if _lockable_volume_paths(locked_disk) != volume_paths:
                    raise BackendError("Disk volume layout changed while acquiring locks")

                with self._raw_disk_factory(locked_disk.disk_number) as raw_disk:
                    self._validate_raw_geometry(authorization, raw_disk)

                    def progress(written: int, total: int) -> None:
                        report(
                            JobStatus.WIPING,
                            "Writing zero pattern with native raw I/O",
                            written,
                            total,
                        )

                    result = overwrite_with_zeros(
                        raw_disk,
                        cancel_event,
                        progress,
                        expected_size=authorization.size_bytes,
                        chunk_size=self._chunk_size,
                    )
                    if result.cancelled:
                        return BackendResult(
                            JobStatus.CANCELLED_INCOMPLETE,
                            "Native zero overwrite cancelled; disk is incomplete",
                            result.bytes_written,
                        )
                    report(
                        JobStatus.VERIFYING,
                        "Refreshing Windows disk metadata",
                        result.bytes_written,
                        authorization.size_bytes,
                    )
                    raw_disk.update_properties()
        except BackendError:
            raise
        except (RawWriteError, OSError) as exc:
            raise BackendError(f"Native raw wipe failed: {exc}") from exc

        self._verify_completion(authorization)
        return BackendResult(
            JobStatus.COMPLETE,
            "Native zero overwrite completed and no partitions remain",
            authorization.size_bytes,
        )

    def set_protection_policy(self, policy: ProtectionPolicy) -> None:
        self._policy = policy

    def _revalidate(self, authorization: WipeAuthorization) -> PhysicalDisk:
        try:
            inventory = self._discovery.discover()
        except DiscoveryError as exc:
            raise BackendError(f"Revalidation failed: {exc}") from exc
        current = inventory.disk_by_number(authorization.disk_number)
        if current is None:
            raise BackendError("Authorized disk number is no longer present")
        if not authorization.fingerprint.matches(current.fingerprint):
            raise BackendError("Disk identity changed after confirmation")
        assessment = self._policy.assess(current)
        if not assessment.can_wipe:
            raise BackendError(
                "Disk became protected: " + "; ".join(assessment.protection_reasons)
            )
        return current

    @staticmethod
    def _validate_raw_geometry(
        authorization: WipeAuthorization, raw_disk: RawWriteDevice
    ) -> None:
        expected = authorization.fingerprint
        if raw_disk.logical_sector_size != expected.logical_sector_size:
            raise BackendError("Raw device logical sector size changed")
        if raw_disk.physical_sector_size != expected.physical_sector_size:
            raise BackendError("Raw device physical sector size changed")

    def _verify_completion(self, authorization: WipeAuthorization) -> None:
        report_error = "Post-wipe discovery failed"
        try:
            inventory = self._discovery.discover()
        except DiscoveryError as exc:
            raise BackendError(f"{report_error}: {exc}") from exc
        current = inventory.disk_by_number(authorization.disk_number)
        if current is None:
            raise BackendError("Disk disappeared before completion could be verified")
        if not authorization.fingerprint.matches(current.fingerprint):
            raise BackendError("Disk identity changed before completion verification")
        if current.partition_count != 0:
            raise BackendError(
                f"Post-wipe verification found {current.partition_count} partition(s)"
            )


def _lockable_volume_paths(disk: PhysicalDisk) -> tuple[str, ...]:
    if len(disk.volumes) != disk.partition_count:
        raise BackendError(
            "Cannot prove lock coverage for every partition on the selected disk"
        )
    paths: list[str] = []
    for volume in disk.volumes:
        candidates = (*volume.access_paths, volume.path, volume.drive_letter)
        normalized_candidates: list[str] = []
        for candidate in candidates:
            if not candidate:
                continue
            try:
                normalized_candidates.append(volume_device_path(candidate))
            except RawWriteError:
                continue
        if not normalized_candidates:
            raise BackendError("A partition has no lockable volume access path")
        normalized = next(
            (
                path
                for path in normalized_candidates
                if path.lower().startswith(r"\\?\volume{")
            ),
            normalized_candidates[0],
        )
        if normalized in paths:
            raise BackendError("Duplicate volume access path discovered")
        paths.append(normalized)
    return tuple(paths)
