"""Islamic art and architecture, from the picture list the Ezan Vakti app keeps.

The list is a fixed set of about a hundred pictures, not a feed, so this source
invents a publishing schedule for it: every day one picture is "published", and
after as many days as there are pictures the cycle starts again. A picture's date
is the last day, up to today, on which its turn came.

- `latest()` offers the last few days of that schedule, so one new picture a day
  joins the queue, like the daily sources.
- `older_than()` walks back through the rest of the cycle in small batches when the
  queue runs low, like the APOD and Wikimedia archives.

Every picture therefore reaches the queue within one cycle, while the source never
adds more than a handful at a time and takes its turn like any other. The store
ignores pictures it already knows, so a later cycle only brings pictures that are
new to the list.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import date, timedelta

from wallqueue import ezanvakti
from wallqueue.http import Http
from wallqueue.imaging import fits_screen
from wallqueue.models import Candidate
from wallqueue.sources.base import Source

_RECENT_DAYS = 3
_ARCHIVE_BATCH = 7


def _order_key(entry: dict) -> str:
    """A stable shuffle, so mosques, tiles and calligraphy alternate."""
    return hashlib.sha1(entry["dosya"].encode()).hexdigest()


class Islami(Source):
    name = "islami"
    label = "İslami resimler (Ezan Vakti)"
    # The list is a local file; reading it says nothing about being online.
    needs_network = False

    def __init__(self, today: Callable[[], date] = date.today) -> None:
        self.today = today

    def latest(self, http: Http) -> list[Candidate]:
        since = (self.today() - timedelta(days=_RECENT_DAYS - 1)).isoformat()
        return [candidate for candidate in self.schedule() if candidate.published >= since]

    def older_than(self, http: Http, day: str) -> list[Candidate]:
        return [candidate for candidate in self.schedule() if candidate.published < day][
            :_ARCHIVE_BATCH
        ]

    def schedule(self) -> list[Candidate]:
        """Every usable picture with its date in the current cycle, newest first."""
        entries = [entry for entry in ezanvakti.load_images() if self._usable(entry)]
        entries.sort(key=_order_key)
        today = self.today()
        candidates = []
        for position, entry in enumerate(entries):
            days_ago = (today.toordinal() - position) % len(entries)
            candidates.append(self._candidate(entry, today - timedelta(days=days_ago)))
        return sorted(candidates, key=lambda candidate: candidate.published, reverse=True)

    @staticmethod
    def _usable(entry: dict) -> bool:
        try:
            return (
                isinstance(entry["dosya"], str)
                and entry["thumb_url"].startswith("https://")
                and fits_screen(int(entry["genislik"]), int(entry["yukseklik"]))
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            return False

    def _candidate(self, entry: dict, day: date) -> Candidate:
        credit = " · ".join(
            str(entry[key]) for key in ("yazar", "lisans") if entry.get(key)
        )
        return Candidate(
            source=self.name,
            source_id=entry["dosya"],
            title=str(entry.get("aciklama") or entry["dosya"].removeprefix("File:")),
            image_url=entry["thumb_url"],
            published=day.isoformat(),
            page_url=str(entry.get("sayfa_url") or ""),
            credit=credit,
        )
