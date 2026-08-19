from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REAL_WIPE_ENV_VALUE = "I_UNDERSTAND_THIS_DESTROYS_DATA"
NATIVE_WIPE_ENV_VALUE = "I_UNDERSTAND_NATIVE_WIPES_ARE_EXPERIMENTAL"
INTERNAL_SATA_ENV_VALUE = "I_UNDERSTAND_INTERNAL_SATA_WIPES_DESTROY_DATA"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "DiskWiper"
    return Path.home() / ".diskwiper"


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    real_wipes_requested: bool = False
    real_backend: str = "diskpart"
    native_test_targets: tuple[str, ...] = ()
    simulation_seconds: int = 20
    refresh_seconds: int = 60

    @property
    def real_wipes_enabled(self) -> bool:
        general_gate = (
            self.real_wipes_requested
            and os.environ.get("DISKWIPER_ENABLE_REAL_WIPES")
            == REAL_WIPE_ENV_VALUE
        )
        if self.real_backend == "native":
            return (
                general_gate
                and bool(self.native_test_targets)
                and os.environ.get("DISKWIPER_ENABLE_NATIVE_WIPES")
                == NATIVE_WIPE_ENV_VALUE
            )
        return general_gate

    @property
    def internal_sata_wipes_enabled(self) -> bool:
        """Allow SATA disks past the bus check only for this process session."""
        return (
            os.environ.get("DISKWIPER_ENABLE_INTERNAL_SATA_WIPES")
            == INTERNAL_SATA_ENV_VALUE
        )

    @property
    def allowed_bus_types(self) -> frozenset[str]:
        allowed = {"USB"}
        if self.internal_sata_wipes_enabled:
            allowed.add("SATA")
        return frozenset(allowed)

    @property
    def destructive_mode_description(self) -> str:
        if self.real_backend == "native":
            return "EXPERIMENTAL native raw zero overwrite"
        return "DiskPart clean all"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "history.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "diskwiper.log"
