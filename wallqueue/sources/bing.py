"""Bing's homepage image of the day."""

from __future__ import annotations

from datetime import datetime

from wallqueue.http import Http
from wallqueue.models import Candidate
from wallqueue.sources.base import Source

_HOST = "https://www.bing.com"
_ARCHIVE_URL = f"{_HOST}/HPImageArchive.aspx"


class Bing(Source):
    name = "bing"
    label = "Bing"

    def latest(self, http: Http) -> list[Candidate]:
        params = {"format": "js", "idx": 0, "n": 8, "mkt": "en-US"}
        return [self._candidate(entry) for entry in http.json(_ARCHIVE_URL, params)["images"]]

    def _candidate(self, entry: dict) -> Candidate:
        published = datetime.strptime(entry["startdate"], "%Y%m%d").date()
        return Candidate(
            source=self.name,
            source_id=entry["urlbase"],
            title=entry["title"],
            image_url=f"{_HOST}{entry['urlbase']}_UHD.jpg",
            published=published.isoformat(),
            page_url=entry.get("copyrightlink", ""),
            credit=entry.get("copyright", ""),
        )
