"""Decides the order in which waiting images are shown."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from wallqueue.models import Image


def rotate(images: Iterable[Image], last_shown: Mapping[str, float]) -> list[Image]:
    """Order images so sources take turns, each offering its newest image first.

    The source shown longest ago goes first. The tail therefore holds the oldest
    images of the most plentiful sources, which makes it the right end to trim.
    """
    turns: Counter[str] = Counter()
    keyed = []
    for image in sorted(images, key=lambda image: image.published, reverse=True):
        turn = turns[image.source]
        turns[image.source] += 1
        keyed.append(((turn, last_shown.get(image.source, 0.0), image.source), image))
    return [image for _, image in sorted(keyed, key=lambda pair: pair[0])]
