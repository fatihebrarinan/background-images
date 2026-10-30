"""A small HTTP client with retries and a download size limit."""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from wallqueue import __version__

_USER_AGENT = f"wallqueue/{__version__} (personal desktop wallpaper app)"
_TIMEOUT = (10, 60)
_MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024
_CHUNK_BYTES = 256 * 1024


class DownloadTooLarge(Exception):
    pass


class Http:
    def __init__(self) -> None:
        retry = Retry(total=3, backoff_factor=1, status_forcelist=(500, 502, 503, 504))
        self._session = requests.Session()
        self._session.headers["User-Agent"] = _USER_AGENT
        self._session.mount("https://", HTTPAdapter(max_retries=retry))

    def _get(self, url: str, **options: Any) -> requests.Response:
        response = self._session.get(url, timeout=_TIMEOUT, **options)
        response.raise_for_status()
        return response

    def json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return self._get(url, params=params).json()

    def xml(self, url: str) -> ElementTree.Element:
        return ElementTree.fromstring(self._get(url).content)

    def download(self, url: str, destination: Path) -> None:
        with self._get(url, stream=True) as response:
            written = 0
            with destination.open("wb") as output:
                for chunk in response.iter_content(_CHUNK_BYTES):
                    written += len(chunk)
                    if written > _MAX_DOWNLOAD_BYTES:
                        raise DownloadTooLarge(url)
                    output.write(chunk)
