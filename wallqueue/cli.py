"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wallqueue import imaging
from wallqueue.engine import Engine
from wallqueue.models import State


def _tick(engine: Engine, _: argparse.Namespace) -> int:
    engine.tick()
    return 0


def _fetch(engine: Engine, _: argparse.Namespace) -> int:
    return 0 if engine.fetch() else 1


def _next(engine: Engine, _: argparse.Namespace) -> int:
    image = engine.advance()
    if image is None:
        print("No image available.")
        return 1
    print(f"[{image.source}] {image.title}")
    return 0


def _add(engine: Engine, arguments: argparse.Namespace) -> int:
    path: Path = arguments.path
    if not path.is_file():
        problem = "not a file" if path.exists() else "no such file"
        print(f"wallqueue: {problem}: {path}", file=sys.stderr)
        return 1
    try:
        image, created = engine.add_local(
            path, arguments.title, arguments.credit, arguments.page_url
        )
    except (OSError, imaging.Rejected) as error:
        print(f"wallqueue: cannot add {path}: {error}", file=sys.stderr)
        return 1

    if not imaging.fits_screen(*imaging.dimensions(Path(image.path))):
        print(
            "wallqueue: note: not a landscape wallpaper shape; the desktop will crop it",
            file=sys.stderr,
        )
    if arguments.now:
        image = engine.show(image)
        print(f"Showing: {image.title}")
    elif image.state == State.SHOWN:
        print(f"Already the current wallpaper: {image.title}")
    else:
        print(f"{'Added' if created else 'Already added'}, showing next: {image.title}")
    return 0


def _status(engine: Engine, _: argparse.Namespace) -> int:
    status = engine.status()
    if status.current:
        print(f"Current: [{status.current.source}] {status.current.title}")
    print(f"Waiting: {status.waiting} ({status.ready} downloaded)")
    print(f"Disk:    {status.disk_bytes / 1024 / 1024:.0f} MB")
    print(f"Timer:   {status.active_seconds / 3600:.1f} of {engine.config.interval_hours} hours")
    if status.islamic_theme:
        print("Theme:   Islamic pictures first today (Ezan Vakti)")
    return 0


def _gui(engine: Engine, _: argparse.Namespace) -> int:
    from wallqueue.gui import run

    return run(engine)


COMMANDS = {
    "tick": (_tick, "do whatever is due (run by the systemd timer)"),
    "fetch": (_fetch, "collect new images now"),
    "next": (_next, "show the next wallpaper"),
    "add": (_add, "queue a picture from disk as the next wallpaper"),
    "status": (_status, "print the queue state"),
    "gui": (_gui, "open the settings window"),
}


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path, help="image file to copy into the queue")
    parser.add_argument("--title", default="", help="title shown in the settings window")
    parser.add_argument("--credit", default="", help="author and license")
    parser.add_argument("--page-url", default="", help="page the picture comes from")
    parser.add_argument("--now", action="store_true", help="set it as the wallpaper now")


def main() -> int:
    parser = argparse.ArgumentParser(prog="wallqueue", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_, description) in COMMANDS.items():
        command = commands.add_parser(name, help=description)
        if name == "add":
            _add_options(command)
    arguments = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if arguments.verbose or arguments.command == "tick" else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    return COMMANDS[arguments.command][0](Engine.create(), arguments)
