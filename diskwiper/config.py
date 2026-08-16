from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REAL_WIPE_ENV_VALUE = "I_UNDERSTAND_THIS_DESTROYS_DATA"


def default_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "DiskWiper"
    return Path.home() / ".diskwiper"


@dataclass(frozen=True)
class AppConfig:
    data_dir: Path
    real_wipes_requested: bool = False
    simulation_seconds: int = 20
    refresh_seconds: int = 60

    @property
    def real_wipes_enabled(self) -> bool:
        return (
            self.real_wipes_requested
            and os.environ.get("DISKWIPER_ENABLE_REAL_WIPES")
            == REAL_WIPE_ENV_VALUE
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "history.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "diskwiper.log"
