"""Records shared between the sources, the store and the engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    QUEUED = "queued"  # Known, not downloaded yet.
    READY = "ready"  # Downloaded, waiting for its turn.
    SHOWN = "shown"  # Has been on screen; the file is kept for recycling.
    EXPIRED = "expired"  # Shown, file evicted to stay under the disk limit.
    DROPPED = "dropped"  # Fell off the tail of a full queue.
    REJECTED = "rejected"  # Unusable: wrong shape, duplicate, broken link.
    BANNED = "banned"  # The user never wants to see it again.


@dataclass(frozen=True)
class Candidate:
    """An image a source offers, before anything is downloaded."""

    source: str
    source_id: str
    title: str
    image_url: str
    published: str  # ISO date, so that text order equals date order.
    page_url: str = ""
    credit: str = ""


@dataclass(frozen=True)
class Image:
    """An image as tracked in the store."""

    id: int
    source: str
    source_id: str
    title: str
    credit: str
    page_url: str
    image_url: str
    published: str
    state: str
    path: str | None
    size: int
    dhash: str | None
    favorite: int
    attempts: int
    shown_at: float | None
