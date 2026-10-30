"""The interface every image source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from wallqueue.http import Http
from wallqueue.models import Candidate


class Source(ABC):
    name: str
    label: str

    @abstractmethod
    def latest(self, http: Http) -> list[Candidate]:
        """Return the images the source currently publishes."""

    def older_than(self, http: Http, day: str) -> list[Candidate]:
        """Return a batch of archive images published before the ISO date `day`.

        Sources without a reachable archive keep the default empty result.
        """
        return []
