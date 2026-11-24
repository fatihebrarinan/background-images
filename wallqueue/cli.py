"""Command line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path

from wallqueue import desktop, imaging
from wallqueue.engine import Engine, Focus
from wallqueue.models import State


def _tick(engine: Engine, _: argparse.Namespace) -> int:
    engine.tick()
    return 0


def _fetch(engine: Engine, _: argparse.Namespace) -> int:
    return 0 if engine.fetch() else 1


def _next(engine: Engine, arguments: argparse.Namespace) -> int:
    image = engine.advance()
    if image is None:
        print("No image available.")
        if arguments.notify:
            desktop.notify("Duvar kâğıdı değişmedi", "Sırada indirilmiş resim yok.")
        return 1
    print(f"[{image.source}] {image.title}")
    if arguments.notify:
        desktop.notify(image.title, image.credit)
    return 0


def _next_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--notify", action="store_true", help="also tell the result in a desktop notification"
    )


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


def _add_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("path", type=Path, help="image file to copy into the queue")
    parser.add_argument("--title", default="", help="title shown in the settings window")
    parser.add_argument("--credit", default="", help="author and license")
    parser.add_argument("--page-url", default="", help="page the picture comes from")
    parser.add_argument("--now", action="store_true", help="set it as the wallpaper now")


def _describe(focus: Focus) -> str:
    return f"{focus.source} ({'today only' if focus.until else 'until turned off'})"


def _focus(engine: Engine, arguments: argparse.Namespace) -> int:
    if arguments.source == "off":
        engine.set_focus(None)
        print("Focus off.")
        return 0
    try:
        focus = engine.set_focus(arguments.source, arguments.today)
    except ValueError as error:
        names = ", ".join(source.name for source in engine.sources)
        print(f"wallqueue: {error} (sources: {names})", file=sys.stderr)
        return 1

    print(f"Focus: {_describe(focus)}")
    shown = engine.show_focus()
    current = engine.store.current()
    if shown is not None:
        print(f"Showing: {shown.title}")
    elif current is None or current.source != focus.source:
        print(f"No {focus.source} picture is downloaded yet; it goes first once one is.")
    return 0


def _focus_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", help="source name as in `wallqueue status`, or 'off'")
    parser.add_argument("--today", action="store_true", help="only until the end of today")


def _status(engine: Engine, _: argparse.Namespace) -> int:
    status = engine.status()
    if status.current:
        print(f"Current: [{status.current.source}] {status.current.title}")
    print(f"Waiting: {status.waiting} ({status.ready} downloaded)")
    print(f"Disk:    {status.disk_bytes / 1024 / 1024:.0f} MB")
    print(f"Timer:   {status.active_seconds / 3600:.1f} of {engine.config.interval_hours} hours")
    if status.focus:
        print(f"Focus:   {_describe(status.focus)}")
    elif status.islamic_theme:
        print("Theme:   Islamic pictures first today (Ezan Vakti)")
    return 0


def _gui(engine: Engine, _: argparse.Namespace) -> int:
    from wallqueue.gui import run

    return run(engine)


@dataclass(frozen=True)
class Command:
    run: Callable[[Engine, argparse.Namespace], int]
    help: str
    options: Callable[[argparse.ArgumentParser], None] | None = None
    # Whether it changes the queue, so it must wait for any other change to finish.
    exclusive: bool = True


COMMANDS = {
    "tick": Command(_tick, "do whatever is due (run by the systemd timer)"),
    "fetch": Command(_fetch, "collect new images now"),
    "next": Command(_next, "show the next wallpaper", _next_options),
    "add": Command(_add, "queue a picture from disk as the next wallpaper", _add_options),
    "focus": Command(
        _focus, "switch to one source's pictures and show them first", _focus_options
    ),
    "status": Command(_status, "print the queue state", exclusive=False),
    "gui": Command(_gui, "open the settings window", exclusive=False),
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="wallqueue", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, command in COMMANDS.items():
        subparser = commands.add_parser(name, help=command.help)
        if command.options:
            command.options(subparser)
    arguments = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if arguments.verbose or arguments.command == "tick" else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    command = COMMANDS[arguments.command]
    engine = Engine.create()
    with engine.exclusive() if command.exclusive else nullcontext():
        return command.run(engine, arguments)
