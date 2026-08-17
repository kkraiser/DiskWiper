from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from diskwiper.disks.discovery import DiskDiscovery, DiscoveryError
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.domain.models import JobStatus, WipeAuthorization


logger = logging.getLogger(__name__)
StatusReporter = Callable[[JobStatus, str, int | None, int | None], None]


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class BackendResult:
    status: JobStatus
    message: str
    bytes_processed: int | None = None


class WipeBackend(Protocol):
    name: str
    simulated: bool
    supports_cancel: bool

    def run(
        self,
        authorization: WipeAuthorization,
        cancel_event: threading.Event,
        report: StatusReporter,
    ) -> BackendResult: ...


class RealWipeBackend(WipeBackend, Protocol):
    def set_protection_policy(self, policy: ProtectionPolicy) -> None: ...


class SimulationBackend:
    name = "simulated-zero-overwrite"
    simulated = True
    supports_cancel = True

    def __init__(self, duration_seconds: int = 20, steps: int = 100) -> None:
        self._duration_seconds = max(1, duration_seconds)
        self._steps = max(1, steps)

    def run(
        self,
        authorization: WipeAuthorization,
        cancel_event: threading.Event,
        report: StatusReporter,
    ) -> BackendResult:
        total = authorization.size_bytes
        report(JobStatus.WIPING, "SIMULATION: no disk writes will occur", 0, total)
        delay = self._duration_seconds / self._steps
        for step in range(1, self._steps + 1):
            if cancel_event.wait(delay):
                processed = total * (step - 1) // self._steps
                return BackendResult(
                    JobStatus.CANCELLED_INCOMPLETE,
                    "Simulated wipe cancelled",
                    processed,
                )
            processed = total * step // self._steps
            report(
                JobStatus.WIPING,
                "SIMULATION: writing zero pattern",
                processed,
                total,
            )
        report(JobStatus.VERIFYING, "SIMULATION: checking completion", total, total)
        return BackendResult(
            JobStatus.COMPLETE,
            "Simulated zero overwrite completed; no physical data was changed",
            total,
        )


class DiskPartBackend:
    name = "diskpart-clean-all"
    simulated = False
    supports_cancel = False

    def __init__(
        self,
        discovery: DiskDiscovery,
        protection_policy: ProtectionPolicy,
        real_wipes_enabled: bool,
        is_admin: Callable[[], bool],
        process_runner: Callable[[Path], subprocess.CompletedProcess[bytes]] | None = None,
    ) -> None:
        self._discovery = discovery
        self._policy = protection_policy
        self._real_wipes_enabled = real_wipes_enabled
        self._is_admin = is_admin
        self._process_runner = process_runner or self._run_diskpart

    @staticmethod
    def script_for(disk_number: int) -> str:
        if disk_number < 0:
            raise ValueError("Disk number cannot be negative")
        return f"select disk {disk_number}\ndetail disk\nclean all\nexit\n"

    def run(
        self,
        authorization: WipeAuthorization,
        cancel_event: threading.Event,
        report: StatusReporter,
    ) -> BackendResult:
        del cancel_event  # DiskPart clean all has no reliable cooperative cancellation.
        if not self._real_wipes_enabled:
            raise BackendError("Real wipe gate is disabled")
        if not self._is_admin():
            raise BackendError("Administrator privileges are required")

        report(JobStatus.PREPARING, "Revalidating disk identity and protection", 0, None)
        disk = self._revalidate(authorization)
        script = self.script_for(disk.disk_number)

        script_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                prefix=f"diskwiper_disk_{disk.disk_number}_",
                suffix=".txt",
                encoding="ascii",
                newline="\r\n",
                delete=False,
            ) as script_file:
                script_file.write(script)
                script_path = Path(script_file.name)

            logger.warning(
                "Starting destructive DiskPart clean all for disk %s serial %s",
                disk.disk_number,
                disk.serial_number,
            )
            report(
                JobStatus.WIPING,
                "DiskPart clean all is running; percentage is unavailable",
                None,
                None,
            )
            completed = self._process_runner(script_path)
            output = _decode_process_output(completed.stdout, completed.stderr)
            logger.info("DiskPart output for disk %s:\n%s", disk.disk_number, output)
            if completed.returncode != 0:
                raise BackendError(
                    f"DiskPart exited with code {completed.returncode}: {output[-1000:]}"
                )

            report(JobStatus.VERIFYING, "Refreshing disk metadata", None, None)
            self._verify_completion(authorization)
            return BackendResult(
                JobStatus.COMPLETE,
                "DiskPart clean all completed and no partitions remain",
                authorization.size_bytes,
            )
        finally:
            if script_path is not None:
                try:
                    script_path.unlink(missing_ok=True)
                except OSError:
                    logger.exception("Could not remove temporary DiskPart script")

    def set_protection_policy(self, policy: ProtectionPolicy) -> None:
        """Apply newly persisted protections to subsequent revalidation checks."""
        self._policy = policy

    def _revalidate(self, authorization: WipeAuthorization):
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

    def _verify_completion(self, authorization: WipeAuthorization) -> None:
        try:
            inventory = self._discovery.discover()
        except DiscoveryError as exc:
            raise BackendError(f"Post-wipe discovery failed: {exc}") from exc
        current = inventory.disk_by_number(authorization.disk_number)
        if current is None:
            raise BackendError("Disk disappeared before completion could be verified")
        if not authorization.fingerprint.matches(current.fingerprint):
            raise BackendError("Disk identity changed before completion verification")
        if current.partition_count != 0:
            raise BackendError(
                f"Post-wipe verification found {current.partition_count} partition(s)"
            )

    @staticmethod
    def _run_diskpart(script_path: Path) -> subprocess.CompletedProcess[bytes]:
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.run(
            ["diskpart.exe", "/s", str(script_path)],
            check=False,
            capture_output=True,
            creationflags=creation_flags,
        )


def _decode_process_output(stdout: bytes, stderr: bytes) -> str:
    combined = stdout + (b"\n" if stdout and stderr else b"") + stderr
    for encoding in ("utf-8-sig", "utf-16", "mbcs"):
        try:
            return combined.decode(encoding).strip()
        except (UnicodeDecodeError, LookupError):
            continue
    return combined.decode("utf-8", errors="replace").strip()
