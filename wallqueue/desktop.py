"""Talks to the Cinnamon desktop: the wallpaper setting and notifications."""

from __future__ import annotations

import html
import subprocess
from pathlib import Path

BACKGROUND_SCHEMA = "org.cinnamon.desktop.background"
ICON = "wallqueue"


def set_wallpaper(path: Path) -> None:
    for key, value in (("picture-options", "zoom"), ("picture-uri", path.as_uri())):
        subprocess.run(["gsettings", "set", BACKGROUND_SCHEMA, key, value], check=True)


def notify(summary: str, body: str = "") -> None:
    """Show a short desktop notification; skipped quietly if that is not possible."""
    try:
        subprocess.run(
            [
                "notify-send",
                "--app-name=Wallqueue",
                f"--icon={ICON}",
                "--transient",
                "--expire-time=5000",
                summary,
                # The body is read as markup, and titles may contain "&" or "<".
                html.escape(body),
            ],
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        pass
