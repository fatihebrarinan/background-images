"""Wikimedia Commons' picture of the day."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from wallqueue.http import Http
from wallqueue.imaging import MAX_EDGE, fits_screen
from wallqueue.models import Candidate
from wallqueue.sources.base import Source

_FEED_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{day:%Y/%m/%d}"
_FILE_URL = "https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width={width}"
_RECENT_DAYS = 3
_ARCHIVE_DAYS = 7


class Wikimedia(Source):
    name = "wikimedia"
    label = "Wikimedia"

    def latest(self, http: Http) -> list[Candidate]:
        # Pictures change at midnight UTC, so a local date can be a day too far.
        return self._days(http, datetime.now(timezone.utc).date(), _RECENT_DAYS)

    def older_than(self, http: Http, day: str) -> list[Candidate]:
        start = date.fromisoformat(day) - timedelta(days=1)
        return self._days(http, start, _ARCHIVE_DAYS)

    def _days(self, http: Http, start: date, count: int) -> list[Candidate]:
        candidates = []
        for offset in range(count):
            day = start - timedelta(days=offset)
            entry = http.json(_FEED_URL.format(day=day)).get("image")
            if entry and fits_screen(entry["image"]["width"], entry["image"]["height"]):
                candidates.append(self._candidate(entry, day))
        return candidates

    def _candidate(self, entry: dict, day: date) -> Candidate:
        name = entry["title"].removeprefix("File:")
        return Candidate(
            source=self.name,
            source_id=entry["title"],
            title=entry.get("description", {}).get("text") or name,
            image_url=self._sized_url(entry["image"], name),
            published=day.isoformat(),
            page_url=entry.get("file_page", ""),
            credit=entry.get("artist", {}).get("text", ""),
        )

    @staticmethod
    def _sized_url(original: dict, name: str) -> str:
        """Ask for a scaled copy, since originals often run to tens of megabytes."""
        if original["width"] <= MAX_EDGE:
            return original["source"]
        return _FILE_URL.format(name=quote(name), width=MAX_EDGE)
