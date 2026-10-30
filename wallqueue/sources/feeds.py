"""Sources published as RSS feeds with image enclosures."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from email.utils import parsedate_to_datetime

from wallqueue.http import Http
from wallqueue.models import Candidate
from wallqueue.sources.base import Source


class RssSource(Source):
    feed_url: str

    def latest(self, http: Http) -> list[Candidate]:
        items = http.xml(self.feed_url).iterfind("channel/item")
        return [candidate for item in items if (candidate := self._candidate(item))]

    def _candidate(self, item: ElementTree.Element) -> Candidate | None:
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("type", "").startswith("image/"):
            return None
        return Candidate(
            source=self.name,
            source_id=item.findtext("guid") or enclosure.get("url"),
            title=(item.findtext("title") or "").strip(),
            image_url=self.full_size_url(enclosure.get("url")),
            published=parsedate_to_datetime(item.findtext("pubDate")).date().isoformat(),
            page_url=item.findtext("link") or "",
            credit=self.label,
        )

    def full_size_url(self, url: str) -> str:
        return url


class NasaImageOfTheDay(RssSource):
    name = "nasa_iotd"
    label = "NASA Image of the Day"
    feed_url = "https://www.nasa.gov/feeds/iotd-feed/"


class _ObservatoryFeed(RssSource):
    """ESO and ESA/Hubble share a publishing system: feeds link screen-sized copies."""

    def full_size_url(self, url: str) -> str:
        return url.replace("/images/screen/", "/images/large/")


class Eso(_ObservatoryFeed):
    name = "eso"
    label = "ESO"
    feed_url = "https://www.eso.org/public/images/potw/feed/"


class EsaHubble(_ObservatoryFeed):
    name = "hubble"
    label = "ESA/Hubble"
    feed_url = "https://esahubble.org/images/potm/feed/"
