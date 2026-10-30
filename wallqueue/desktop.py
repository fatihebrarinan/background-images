"""Applies a wallpaper to the Cinnamon desktop."""

from __future__ import annotations

import subprocess
from pathlib import Path

_SCHEMA = "org.cinnamon.desktop.background"


def set_wallpaper(path: Path) -> None:
    for key, value in (("picture-options", "zoom"), ("picture-uri", path.as_uri())):
        subprocess.run(["gsettings", "set", _SCHEMA, key, value], check=True)
