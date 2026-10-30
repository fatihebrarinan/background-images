import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from wallqueue.models import Candidate
from wallqueue.sources.apod import Apod
from wallqueue.sources.bing import Bing
from wallqueue.sources.feeds import Eso
from wallqueue.store import Store

ESO_FEED = """<rss><channel>
<item>
  <title>A video</title>
  <pubDate>Mon, 26 Oct 2026 06:00:00 +0100</pubDate>
  <enclosure url="https://cdn.eso.org/videos/potw1.m4v" type="video/x-m4v"/>
</item>
<item>
  <title>A nebula</title>
  <link>https://www.eso.org/public/images/potw2/</link>
  <guid>potw2</guid>
  <pubDate>Mon, 19 Oct 2026 06:00:00 +0100</pubDate>
  <enclosure url="https://cdn.eso.org/images/screen/potw2.jpg" type="image/jpeg"/>
</item>
</channel></rss>"""


class StubHttp:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)

    def json(self, url: str, params: dict | None = None) -> object:
        return self.responses.pop(0)

    def xml(self, url: str) -> ElementTree.Element:
        return ElementTree.fromstring(self.responses.pop(0))


class ParsingTests(unittest.TestCase):
    def test_bing_uses_the_uhd_image(self) -> None:
        entry = {"startdate": "20261030", "urlbase": "/th?id=OHR.X", "title": "T"}
        [candidate] = Bing().latest(StubHttp({"images": [entry]}))
        self.assertEqual(candidate.image_url, "https://www.bing.com/th?id=OHR.X_UHD.jpg")
        self.assertEqual(candidate.published, "2026-10-30")

    def test_eso_skips_videos_and_uses_the_large_image(self) -> None:
        [candidate] = Eso().latest(StubHttp(ESO_FEED))
        self.assertEqual(candidate.image_url, "https://cdn.eso.org/images/large/potw2.jpg")
        self.assertEqual(candidate.published, "2026-10-19")

    def test_apod_finds_the_original_and_skips_small_or_other_posts(self) -> None:
        post = {
            "date": "2026-10-30T00:05:00",
            "link": "https://science.nasa.gov/image-article/apod-1/",
            "title": {"rendered": "APOD: 2026 October 30 &#8211; Haunting"},
            "featured_media": 1,
        }
        small = {**post, "featured_media": 2}
        other = {**post, "title": {"rendered": "Not an APOD"}, "featured_media": 3}
        base = "https://assets.science.nasa.gov"
        media = [
            {
                "id": 1,
                "mime_type": "image/jpeg",
                "source_url": f"{base}/dynamicimage/assets/science/cds/a.jpg",
                "media_details": {"width": 6000, "height": 4000},
            },
            {
                "id": 2,
                "mime_type": "image/jpeg",
                "source_url": f"{base}/dynamicimage/assets/science/cds/b.jpg",
                "media_details": {"width": 800, "height": 600},
            },
        ]
        [candidate] = Apod().latest(StubHttp([post, small, other], media))
        self.assertEqual(candidate.image_url, f"{base}/content/dam/science/cds/a.jpg")
        self.assertEqual(candidate.title, "Haunting")


class StoreTests(unittest.TestCase):
    def test_add_counts_only_new_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.db")
            self.addCleanup(store.close)
            candidate = Candidate("a", "1", "t", "https://example.org", "2026-01-01")
            self.assertEqual(store.add([candidate]), 1)
            self.assertEqual(store.add([candidate]), 0)
