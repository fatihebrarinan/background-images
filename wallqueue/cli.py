"""Command line interface."""

from __future__ import annotations

import argparse
import logging

from wallqueue.engine import Engine


def _tick(engine: Engine) -> int:
    engine.tick()
    return 0


def _fetch(engine: Engine) -> int:
    return 0 if engine.fetch() else 1


def _next(engine: Engine) -> int:
    image = engine.advance()
    if image is None:
        print("No image available.")
        return 1
    print(f"[{image.source}] {image.title}")
    return 0


def _status(engine: Engine) -> int:
    status = engine.status()
    if status.current:
        print(f"Current: [{status.current.source}] {status.current.title}")
    print(f"Waiting: {status.waiting} ({status.ready} downloaded)")
    print(f"Disk:    {status.disk_bytes / 1024 / 1024:.0f} MB")
    print(f"Timer:   {status.active_seconds / 3600:.1f} of {engine.config.interval_hours} hours")
    return 0


def _gui(engine: Engine) -> int:
    from wallqueue.gui import run

    return run(engine)


COMMANDS = {
    "tick": (_tick, "do whatever is due (run by the systemd timer)"),
    "fetch": (_fetch, "collect new images now"),
    "next": (_next, "show the next wallpaper"),
    "status": (_status, "print the queue state"),
    "gui": (_gui, "open the settings window"),
}


def main() -> int:
    parser = argparse.ArgumentParser(prog="wallqueue", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, (_, description) in COMMANDS.items():
        commands.add_parser(name, help=description)
    arguments = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if arguments.verbose or arguments.command == "tick" else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    return COMMANDS[arguments.command][0](Engine.create())
