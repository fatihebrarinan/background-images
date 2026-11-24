"""Files shared with the Ezan Vakti prayer times app.

The two apps never import each other. Ezan Vakti writes a list of hand-picked
Wikimedia Commons pictures and a small hint about today; Wallqueue only reads them,
and a missing or broken file simply means there is nothing to use.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

_APP_DIR = "ezan-vakti"


def _xdg_dir(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback) / _APP_DIR


def images_path() -> Path:
    return _xdg_dir("XDG_DATA_HOME", ".local/share") / "resimler.json"


def hint_path() -> Path:
    return _xdg_dir("XDG_CACHE_HOME", ".cache") / "bugun.json"


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def load_images() -> list[dict]:
    """The picture list, or an empty list when it is missing or malformed."""
    saved = _read(images_path())
    images = saved.get("resimler") if isinstance(saved, dict) else None
    return [entry for entry in images if isinstance(entry, dict)] if isinstance(images, list) else []


def islamic_theme(day: date) -> bool:
    """Whether Ezan Vakti marks `day` (a local date) as a religious day."""
    hint = _read(hint_path())
    return (
        isinstance(hint, dict)
        and hint.get("tarih") == day.isoformat()
        and hint.get("islami_tema") is True
    )
