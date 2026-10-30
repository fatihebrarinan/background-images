"""User settings and on-disk locations."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

MIN_INTERVAL_HOURS = 1
MAX_INTERVAL_HOURS = 5


def _xdg_dir(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback) / "wallqueue"


def config_path() -> Path:
    return _xdg_dir("XDG_CONFIG_HOME", ".config") / "config.json"


def data_dir() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share")


@dataclass
class Config:
    interval_hours: int = 3
    disabled_sources: list[str] = field(default_factory=list)
    max_disk_mb: int = 1000
    max_queue: int = 200
    # Backfill from the archives once fewer images than this are waiting.
    low_water: int = 20
    # How many upcoming images to keep downloaded, so offline days still work.
    ready_buffer: int = 20

    def __post_init__(self) -> None:
        self.interval_hours = max(
            MIN_INTERVAL_HOURS, min(MAX_INTERVAL_HOURS, int(self.interval_hours))
        )

    @classmethod
    def load(cls) -> Config:
        try:
            saved = json.loads(config_path().read_text())
        except FileNotFoundError:
            return cls()
        known = {key: value for key, value in saved.items() if key in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2) + "\n")
        temporary.replace(path)
