from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diskwiper.config import AppConfig
from diskwiper.disks.benchmark import (
    BenchmarkError,
    benchmark_read_speed,
    estimated_wipe_duration,
)
from diskwiper.disks.discovery import DiskDiscovery, DiskInventory, DiscoveryError
from diskwiper.disks.protection import ProtectionPolicy
from diskwiper.disks.protection import add_protected_stable_keys
from diskwiper.domain.models import DiskAssessment, DiskStatus, JobProgress, JobStatus
from diskwiper.gui.confirm_dialog import ConfirmWipeDialog
from diskwiper.history.database import HistoryStore
from diskwiper.wipe.backends import RealWipeBackend, SimulationBackend
from diskwiper.wipe.manager import JobManager


logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    DEFAULT_WIDTH = 1480
    DEFAULT_HEIGHT = 620
    COLUMNS = (
        "Select",
        "Disk",
        "Status",
        "Model",
        "Serial",
        "Capacity",
        "Interface",
        "Position",
        "Volumes",
        "Speed",
        "Est.",
        "Progress",
        "Elapsed",
        "Action",
    )
    COLUMN_WIDTHS = (
        55,
        45,
        180,
        165,
        130,
        95,
        75,
        75,
        90,
        105,
        120,
        85,
        85,
        95,
    )

    def __init__(
        self,
        config: AppConfig,
        discovery: DiskDiscovery,
        policy: ProtectionPolicy,
        history: HistoryStore,
        manager: JobManager,
        simulation_backend: SimulationBackend,
        real_backend: RealWipeBackend,
    ) -> None:
        super().__init__()
        self._config = config
        self._discovery = discovery
        self._policy = policy
        self._history = history
        self._manager = manager
        self._simulation_backend = simulation_backend
        self._real_backend = real_backend
        self._inventory: DiskInventory | None = None
        self._assessments: dict[int, DiskAssessment] = {}
        self._progress: dict[str, JobProgress] = {}
        self._discovery_pool = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="diskwiper-discovery",
        )
        self._refresh_future: Future[DiskInventory] | None = None
        self._benchmark_pool = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="diskwiper-benchmark",
        )
        self._benchmark_futures: dict[str, Future[float]] = {}
        self._read_speeds: dict[str, float | None] = {}

        self.setWindowTitle("DiskWiper 0.1")
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)

        mode_text = (
            f"DESTRUCTIVE MODE — {config.destructive_mode_description} is enabled"
            if config.real_wipes_enabled
            else "SIMULATION MODE — no physical erase command can execute"
        )
        self._mode_banner = QLabel(mode_text)
        self._mode_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mode_banner.setStyleSheet(
            "font-weight: bold; padding: 10px; color: white; background: "
            + ("#a40000;" if config.real_wipes_enabled else "#286090;")
        )

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self._table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        if len(self.COLUMN_WIDTHS) != len(self.COLUMNS):
            raise RuntimeError("Each table column must have an initial width")
        for column, width in enumerate(self.COLUMN_WIDTHS):
            self._table.setColumnWidth(column, width)

        self._refresh_button = QPushButton("Refresh Disks")
        self._refresh_button.clicked.connect(self.refresh_disks)
        self._wipe_button = QPushButton("Wipe All Selected Disks")
        self._wipe_button.clicked.connect(self._wipe_selected)
        self._cancel_button = QPushButton("Cancel All")
        self._cancel_button.clicked.connect(self._cancel_selected)
        self._protect_button = QPushButton("Protect Selected Permanently")
        self._protect_button.clicked.connect(self._protect_selected)
        self._status_label = QLabel("Waiting for disk inventory")

        controls = QHBoxLayout()
        controls.addWidget(self._refresh_button)
        controls.addWidget(self._wipe_button)
        controls.addWidget(self._cancel_button)
        controls.addWidget(self._protect_button)
        controls.addStretch()
        controls.addWidget(self._status_label)

        layout = QVBoxLayout()
        layout.addWidget(self._mode_banner)
        layout.addLayout(controls)
        layout.addWidget(self._table)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_background_work)
        self._poll_timer.start(200)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed_cells)
        self._elapsed_timer.start(1000)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh_disks)
        self._refresh_timer.start(config.refresh_seconds * 1000)
        QTimer.singleShot(0, self.refresh_disks)

    def refresh_disks(self) -> None:
        if self._refresh_future is not None:
            return
        self._refresh_button.setEnabled(False)
        self._status_label.setText("Refreshing disk inventory…")
        self._refresh_future = self._discovery_pool.submit(self._discovery.discover)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._manager.active_disk_numbers():
            QMessageBox.warning(
                self,
                "Jobs are active",
                "DiskWiper cannot close while wipe jobs are active.",
            )
            event.ignore()
            return
        self._discovery_pool.shutdown(wait=False, cancel_futures=True)
        self._benchmark_pool.shutdown(wait=False, cancel_futures=True)
        self._manager.shutdown()
        event.accept()

    def _poll_background_work(self) -> None:
        if self._refresh_future is not None and self._refresh_future.done():
            future = self._refresh_future
            self._refresh_future = None
            self._refresh_button.setEnabled(True)
            try:
                self._apply_inventory(future.result())
            except DiscoveryError as exc:
                logger.error("Disk discovery failed: %s", exc)
                self._status_label.setText(f"Discovery error: {exc}")
            except Exception as exc:
                logger.exception("Unexpected disk discovery failure")
                self._status_label.setText(f"Discovery error: {exc}")

        events = self._manager.drain_events()
        for progress in events:
            self._progress[progress.stable_key] = progress
            self._status_label.setText(
                f"Disk {progress.disk_number}: {progress.status.value} — {progress.message}"
            )
        if events and self._inventory is not None:
            self._render_table()
        self._poll_benchmarks()

    def _apply_inventory(self, inventory: DiskInventory) -> None:
        self._inventory = inventory
        self._assessments = {}
        for disk in inventory.disks:
            completed_at = self._history.last_completed_at(disk.fingerprint.stable_key)
            self._assessments[disk.disk_number] = self._policy.assess(
                disk,
                previously_wiped_at=completed_at,
            )
        self._schedule_benchmarks()
        self._status_label.setText(f"Detected {len(inventory.disks)} physical disk(s)")
        self._render_table()

    def _render_table(self) -> None:
        checked_keys = self._checked_stable_keys()
        self._table.setRowCount(0)
        for assessment in sorted(
            self._assessments.values(), key=lambda item: item.disk.disk_number
        ):
            disk = assessment.disk
            row = self._table.rowCount()
            self._table.insertRow(row)

            select_item = QTableWidgetItem()
            select_item.setData(Qt.ItemDataRole.UserRole, disk.fingerprint.stable_key)
            select_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
            )
            select_item.setCheckState(
                Qt.CheckState.Checked
                if disk.fingerprint.stable_key in checked_keys and assessment.can_wipe
                else Qt.CheckState.Unchecked
            )
            if not assessment.can_wipe:
                select_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self._table.setItem(row, 0, select_item)

            progress = self._progress.get(disk.fingerprint.stable_key)
            benchmark_key = disk.fingerprint.stable_key
            benchmark_pending = benchmark_key in self._benchmark_futures
            read_speed = self._read_speeds.get(benchmark_key)
            status = progress.status.value if progress else assessment.status.value
            active_write = progress is not None and progress.status is JobStatus.WIPING
            values = (
                str(disk.disk_number),
                status,
                disk.model or "Unknown",
                disk.serial_number or "Unavailable",
                _format_bytes(disk.size_bytes),
                disk.bus_type or "Unknown",
                disk.enclosure_position or "—",
                ", ".join(f"{letter}:" for letter in disk.drive_letters) or "—",
                _format_write_speed(progress)
                if active_write
                else ("Testing…" if benchmark_pending else _format_read_speed(read_speed)),
                _format_live_eta(progress)
                if active_write
                else (
                    "Testing…"
                    if benchmark_pending
                    else _format_wipe_estimate(disk.size_bytes, read_speed)
                ),
                _format_progress(progress),
                _format_elapsed(progress.elapsed_seconds) if progress else "—",
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                self._table.setItem(row, column, item)

            serial_item = self._table.item(row, 4)
            serial_item.setToolTip(disk.serial_number or "Unavailable")

            status_item = self._table.item(row, 2)
            status_item.setForeground(_status_color(status))
            status_font = status_item.font()
            status_font.setBold(True)
            status_item.setFont(status_font)
            if assessment.protection_reasons:
                tooltip = "\n".join(assessment.protection_reasons)
                for column in range(len(self.COLUMNS)):
                    item = self._table.item(row, column)
                    if item:
                        existing = item.toolTip()
                        item.setToolTip(
                            f"{existing}\n\n{tooltip}" if existing else tooltip
                        )

            action = QPushButton()
            active = disk.disk_number in self._manager.active_disk_numbers()
            if active:
                cancellable = self._manager.can_cancel_disk(disk.disk_number)
                action.setText("Cancel" if cancellable else "Running")
                action.setEnabled(cancellable)
                action.clicked.connect(
                    lambda _checked=False, number=disk.disk_number: self._cancel_disk(number)
                )
            else:
                action.setText("Wipe" if assessment.can_wipe else "Protected")
                action.setEnabled(assessment.can_wipe)
                action.clicked.connect(
                    lambda _checked=False, number=disk.disk_number: self._wipe_disk(number)
                )
            self._table.setCellWidget(row, 13, action)

    def _checked_stable_keys(self) -> set[str]:
        checked: set[str] = set()
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked.add(str(item.data(Qt.ItemDataRole.UserRole)))
        return checked

    def _selected_disk_numbers(self) -> list[int]:
        numbers: list[int] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                numbers.append(int(self._table.item(row, 1).text()))
        return numbers

    def _wipe_selected(self) -> None:
        numbers = self._selected_disk_numbers()
        if not numbers:
            QMessageBox.information(self, "No disks selected", "Select at least one READY disk.")
            return
        for number in numbers:
            if not self._wipe_disk(number):
                break

    def _wipe_disk(self, disk_number: int) -> bool:
        if self._inventory is None:
            return False
        assessment = self._assessments.get(disk_number)
        if assessment is None or not assessment.can_wipe:
            QMessageBox.warning(self, "Protected disk", "This disk is not eligible for wiping.")
            return False
        simulated = not self._config.real_wipes_enabled
        dialog = ConfirmWipeDialog(assessment, simulated=simulated, parent=self)
        if dialog.exec() != ConfirmWipeDialog.DialogCode.Accepted:
            return False
        backend = self._simulation_backend if simulated else self._real_backend
        try:
            self._manager.start(assessment, self._inventory.generation, backend)
        except ValueError as exc:
            QMessageBox.warning(self, "Job not started", str(exc))
            return False
        self._render_table()
        return True

    def _cancel_selected(self) -> None:
        for number in self._selected_disk_numbers():
            self._cancel_disk(number)

    def _protect_selected(self) -> None:
        numbers = self._selected_disk_numbers()
        if not numbers:
            QMessageBox.information(
                self,
                "No disks selected",
                "Select at least one READY disk to protect.",
            )
            return
        active = set(numbers) & set(self._manager.active_disk_numbers())
        if active:
            QMessageBox.warning(
                self,
                "Jobs are active",
                "Wait for active jobs to finish before changing protection.",
            )
            return
        assessments = [self._assessments[number] for number in numbers]
        details = "\n".join(
            f"Disk {item.disk.disk_number} {item.disk.enclosure_position or ''} — "
            f"{_format_bytes(item.disk.size_bytes)} — {item.disk.serial_number}"
            for item in assessments
        )
        answer = QMessageBox.question(
            self,
            "Protect selected disks permanently",
            "These exact device fingerprints will be blocked from wiping:\n\n"
            + details
            + "\n\nContinue?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        keys = {item.disk.fingerprint.stable_key for item in assessments}
        try:
            protected = add_protected_stable_keys(
                self._config.data_dir / "protected_devices.json", keys
            )
        except OSError as exc:
            QMessageBox.critical(self, "Protection was not saved", str(exc))
            return
        self._policy = replace(
            self._policy,
            protected_stable_keys=protected.stable_keys,
            protected_serial_numbers=protected.serial_numbers,
            protected_unique_ids=protected.unique_ids,
        )
        self._real_backend.set_protection_policy(self._policy)
        for key in keys:
            self._progress.pop(key, None)
        if self._inventory is not None:
            self._apply_inventory(self._inventory)
        self._status_label.setText(f"Permanently protected {len(keys)} disk(s)")

    def _cancel_disk(self, disk_number: int) -> None:
        if not self._manager.cancel_disk(disk_number):
            QMessageBox.information(
                self,
                "Cannot cancel",
                "No cancellable wipe is active for this disk.",
            )

    def _refresh_elapsed_cells(self) -> None:
        elapsed_by_disk = self._manager.active_elapsed_seconds()
        for row in range(self._table.rowCount()):
            disk_item = self._table.item(row, 1)
            elapsed_item = self._table.item(row, 12)
            if disk_item is None or elapsed_item is None:
                continue
            elapsed = elapsed_by_disk.get(int(disk_item.text()))
            if elapsed is not None:
                elapsed_item.setText(_format_elapsed(elapsed))

    def _schedule_benchmarks(self) -> None:
        active = self._manager.active_disk_numbers()
        for assessment in self._assessments.values():
            disk = assessment.disk
            key = disk.fingerprint.stable_key
            if (
                not assessment.can_wipe
                or disk.disk_number in active
                or key in self._read_speeds
                or key in self._benchmark_futures
            ):
                continue
            self._benchmark_futures[key] = self._benchmark_pool.submit(
                benchmark_read_speed,
                disk.disk_number,
                disk.size_bytes,
            )

    def _poll_benchmarks(self) -> None:
        changed = False
        for key, future in tuple(self._benchmark_futures.items()):
            if not future.done():
                continue
            del self._benchmark_futures[key]
            try:
                self._read_speeds[key] = future.result()
            except BenchmarkError as exc:
                logger.info("Read benchmark unavailable: %s", exc)
                self._read_speeds[key] = None
            except Exception:
                logger.exception("Unexpected read benchmark failure")
                self._read_speeds[key] = None
            changed = True
        if changed and self._inventory is not None:
            self._render_table()

def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1000 or unit == "PB":
            return f"{value:.2f} {unit}"
        value /= 1000
    return f"{size} B"


def _format_progress(progress: JobProgress | None) -> str:
    if (
        progress is None
        or progress.bytes_processed is None
        or not progress.total_bytes
    ):
        return "—"
    percentage = progress.bytes_processed / progress.total_bytes * 100
    return f"{percentage:.1f}%"


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _format_read_speed(bytes_per_second: float | None) -> str:
    if bytes_per_second is None:
        return "Unavailable"
    return f"{bytes_per_second / 1_000_000:.1f} MB/s"


def _format_write_speed(progress: JobProgress | None) -> str:
    if (
        progress is None
        or not progress.bytes_processed
        or progress.elapsed_seconds <= 0
    ):
        return "Starting…"
    return _format_read_speed(progress.bytes_processed / progress.elapsed_seconds)


def _format_live_eta(progress: JobProgress | None) -> str:
    if (
        progress is None
        or not progress.bytes_processed
        or not progress.total_bytes
        or progress.elapsed_seconds <= 0
    ):
        return "Calculating…"
    rate = progress.bytes_processed / progress.elapsed_seconds
    remaining = max(0, progress.total_bytes - progress.bytes_processed)
    return _format_approx_duration(remaining / rate) if remaining else "Done"


def _format_wipe_estimate(
    size_bytes: int, read_bytes_per_second: float | None
) -> str:
    if read_bytes_per_second is None:
        return "Unavailable"
    estimate = estimated_wipe_duration(size_bytes, read_bytes_per_second)
    return _format_approx_duration(estimate)


def _format_approx_duration(seconds: float) -> str:
    total_minutes = max(1, round(seconds / 60))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"~{hours}h {minutes:02d}m"
    return f"~{minutes}m"


def _status_color(status: str) -> QColor:
    if status in {DiskStatus.PROTECTED.value, JobStatus.ERROR.value}:
        return QColor("#ff5c5c")
    if status == DiskStatus.READY.value:
        return QColor("#ffffff")
    if status == JobStatus.COMPLETE.value:
        return QColor("#39d353")
    if status in {
        JobStatus.CANCELLED_INCOMPLETE.value,
        JobStatus.INTERRUPTED.value,
        JobStatus.DISCONNECTED_INCOMPLETE.value,
    }:
        return QColor("#ffb347")
    if status in {JobStatus.WIPING.value, JobStatus.VERIFYING.value}:
        return QColor("#f2c14e")
    return QColor("#e6e6e6")
