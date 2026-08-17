from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from diskwiper.domain.models import DiskAssessment


class ConfirmWipeDialog(QDialog):
    def __init__(
        self,
        assessment: DiskAssessment,
        simulated: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._challenge = (
            _serial_challenge(assessment.disk.serial_number)
            if simulated
            else assessment.disk.serial_number.strip().upper()
        )
        self.setWindowTitle("Confirm simulated wipe" if simulated else "SECURE ERASE")
        self.setModal(True)
        self.setMinimumWidth(500)

        disk = assessment.disk
        heading = QLabel(
            "SIMULATION — no data will be changed"
            if simulated
            else "ALL DATA ON THIS DEVICE WILL BE DESTROYED"
        )
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            "font-weight: bold; padding: 10px; color: "
            + ("#145a32;" if simulated else "#a40000;")
        )

        form = QFormLayout()
        form.addRow("Disk:", QLabel(str(disk.disk_number)))
        form.addRow("Model:", QLabel(disk.model or "Unknown"))
        form.addRow("Serial:", QLabel(disk.serial_number))
        form.addRow("Capacity:", QLabel(_format_bytes(disk.size_bytes)))
        form.addRow("Unique ID:", _wrapping_label(disk.unique_id))

        instruction = QLabel(
            f"Type {'the first four characters of ' if simulated else 'the complete '}"
            f"serial number ({self._challenge}) "
            "to authorize this job:"
        )
        instruction.setWordWrap(True)
        self._entry = QLineEdit()
        self._entry.setMaxLength(max(4, len(self._challenge)))
        self._entry.textChanged.connect(self._validate)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        self._erase_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._erase_button.setText("START SIMULATION" if simulated else "ERASE DISK")
        self._erase_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addLayout(form)
        layout.addWidget(instruction)
        layout.addWidget(self._entry)
        layout.addWidget(buttons)
        self._entry.setFocus()

    def _validate(self, text: str) -> None:
        self._erase_button.setEnabled(text.strip().upper() == self._challenge)


def _wrapping_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return label


def _serial_challenge(serial_number: str) -> str:
    return serial_number.strip()[:4].upper()


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if value < 1000 or unit == "PB":
            return f"{value:.2f} {unit}"
        value /= 1000
    return f"{size} B"
