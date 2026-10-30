"""NASA's Astronomy Picture of the Day.

APOD moved to science.nasa.gov and its old api.nasa.gov endpoint now answers with
the NASA logo in place of each picture, so this reads the new site's posts.
"""

from __future__ import annotations

import html

from wallqueue.http import Http
from wallqueue.imaging import fits_screen
from wallqueue.models import Candidate
from wallqueue.sources.base import Source

_API = "https://science.nasa.gov/wp-json/wp/v2"
_TITLE_PREFIX = "APOD:"
_BATCH = 20


def _original_url(url: str) -> str:
    """Point at the full-size file; the media API links a 1280px rendition."""
    return url.replace("/dynamicimage/assets/science/", "/content/dam/science/")


class Apod(Source):
    name = "apod"
    label = "NASA APOD"

    def latest(self, http: Http) -> list[Candidate]:
        return self._posts(http, {})

    def older_than(self, http: Http, day: str) -> list[Candidate]:
        return self._posts(http, {"before": f"{day}T00:00:00"})

    def _posts(self, http: Http, filters: dict) -> list[Candidate]:
        params = {
            "search": "APOD",
            "per_page": _BATCH,
            "_fields": "date,link,title,featured_media",
            **filters,
        }
        posts = [
            post
            for post in http.json(f"{_API}/image-article", params)
            if post["title"]["rendered"].startswith(_TITLE_PREFIX) and post["featured_media"]
        ]
        media = self._media(http, [post["featured_media"] for post in posts])
        return [
            self._candidate(post, media[post["featured_media"]])
            for post in posts
            if post["featured_media"] in media
        ]

    def _media(self, http: Http, ids: list[int]) -> dict[int, dict]:
        """Fetch the attachments of `ids`, keeping those shaped like a wallpaper."""
        if not ids:
            return {}
        params = {
            "include": ",".join(map(str, ids)),
            "per_page": len(ids),
            "_fields": "id,source_url,media_details,mime_type",
        }
        usable = {}
        for item in http.json(f"{_API}/media", params):
            details = item.get("media_details") or {}
            shape = details.get("width", 0), details.get("height", 0)
            if item.get("mime_type", "").startswith("image/") and fits_screen(*shape):
                usable[item["id"]] = item
        return usable

    def _candidate(self, post: dict, media: dict) -> Candidate:
        title = html.unescape(post["title"]["rendered"])
        return Candidate(
            source=self.name,
            source_id=post["link"],
            title=title.partition("–")[2].strip() or title,
            image_url=_original_url(media["source_url"]),
            published=post["date"][:10],
            page_url=post["link"],
        )
