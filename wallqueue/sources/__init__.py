"""All available image sources."""

from wallqueue.sources.apod import Apod
from wallqueue.sources.base import Source
from wallqueue.sources.bing import Bing
from wallqueue.sources.feeds import EsaHubble, Eso, NasaImageOfTheDay
from wallqueue.sources.wikimedia import Wikimedia

ALL_SOURCES: tuple[Source, ...] = (
    Bing(),
    Apod(),
    Wikimedia(),
    NasaImageOfTheDay(),
    EsaHubble(),
    Eso(),
)

__all__ = ["ALL_SOURCES", "Source"]
