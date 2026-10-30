"""The application logic: collect images, keep the queue healthy, show the next one."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

from wallqueue import imaging
from wallqueue.config import Config, data_dir
from wallqueue.desktop import set_wallpaper
from wallqueue.http import DownloadTooLarge, Http
from wallqueue.models import Image, State
from wallqueue.rotation import rotate
from wallqueue.sources import ALL_SOURCES, Source
from wallqueue.store import Store

log = logging.getLogger(__name__)

# Ticks run every 5 minutes. A longer gap means the computer was off or asleep,
# and that time must not count towards the wallpaper interval.
MAX_TICK_GAP_SECONDS = 15 * 60
FETCH_RETRY_SECONDS = 15 * 60
MAX_DOWNLOAD_ATTEMPTS = 3
ARCHIVE_SKIP_DAYS = 30


def _skip_back(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=ARCHIVE_SKIP_DAYS)).isoformat()


@dataclass(frozen=True)
class Status:
    current: Image | None
    waiting: int
    ready: int
    disk_bytes: int
    active_seconds: float


class Engine:
    def __init__(
        self,
        config: Config,
        store: Store,
        images_dir: Path,
        sources: Sequence[Source] = ALL_SOURCES,
        http: Http | None = None,
        apply_wallpaper: Callable[[Path], None] = set_wallpaper,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.store = store
        self.images_dir = images_dir
        self.sources = sources
        self.http = http or Http()
        self.apply_wallpaper = apply_wallpaper
        self.clock = clock
        images_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def create(cls) -> Engine:
        root = data_dir()
        return cls(Config.load(), Store(root / "wallqueue.db"), root / "images")

    # Entry points

    def tick(self) -> None:
        """Do whatever is due. Runs every few minutes while the user is logged in."""
        active = self._count_active_time()
        self._fetch_if_due()
        if self.store.current() is None or active >= self.config.interval_hours * 3600:
            self.advance()

    def fetch(self) -> bool:
        """Ask every source for new images. Returns whether any source answered."""
        self.store.put("last_fetch_attempt", self.clock())
        reached = False
        for source in self._enabled_sources():
            try:
                added = self.store.add(source.latest(self.http))
            except (requests.RequestException, ValueError, KeyError, SyntaxError) as error:
                log.warning("%s failed: %s", source.name, error)
                continue
            reached = True
            log.info("%s: %d new", source.name, added)
        if reached:
            self.store.put("last_fetch_day", date.fromtimestamp(self.clock()).isoformat())
            self.replenish()
        return reached

    def advance(self) -> Image | None:
        """Show the next image, falling back to old ones so it never runs dry."""
        image = self._next_ready()
        if image is None:
            self.replenish()
            image = self._next_ready() or self._recycled()
        if image is None:
            log.warning("no image available; keeping the current wallpaper")
            return None

        self.apply_wallpaper(Path(image.path))
        self.store.mark_shown(image.id, self.clock())
        self.store.put("active_seconds", 0)
        log.info("showing %s: %s", image.source, image.title)
        self.replenish()
        return self.store.image(image.id)

    def replenish(self) -> None:
        """Bring the queue back to its target size and the disk under its limit."""
        self._backfill()
        self._trim_queue()
        self._download_upcoming()
        self._evict_old_files()

    def ban_current(self) -> None:
        current = self.store.current()
        if current is None:
            return
        self.advance()
        if self.store.get("current_id") != str(current.id):
            self._discard(current, State.BANNED)

    def toggle_favorite(self) -> bool:
        current = self.store.current()
        if current is None:
            return False
        self.store.set_favorite(current.id, not current.favorite)
        return not current.favorite

    def status(self) -> Status:
        waiting = self.store.waiting(self.config.disabled_sources)
        return Status(
            current=self.store.current(),
            waiting=len(waiting),
            ready=sum(image.state == State.READY for image in waiting),
            disk_bytes=self.store.disk_usage(),
            active_seconds=float(self.store.get("active_seconds", "0")),
        )

    # Scheduling

    def _count_active_time(self) -> float:
        now = self.clock()
        active = float(self.store.get("active_seconds", "0"))
        gap = now - float(self.store.get("last_tick", "0"))
        if 0 < gap <= MAX_TICK_GAP_SECONDS:
            active += gap
        self.store.put("last_tick", now)
        self.store.put("active_seconds", active)
        return active

    def _fetch_if_due(self) -> None:
        now = self.clock()
        today = date.fromtimestamp(now).isoformat()
        last_attempt = float(self.store.get("last_fetch_attempt", "0"))
        if self.store.get("last_fetch_day") != today and now - last_attempt >= FETCH_RETRY_SECONDS:
            self.fetch()

    # Queue

    def _enabled_sources(self) -> list[Source]:
        return [s for s in self.sources if s.name not in self.config.disabled_sources]

    def _queue(self) -> list[Image]:
        waiting = self.store.waiting(self.config.disabled_sources)
        return rotate(waiting, self.store.source_last_shown())

    def _next_ready(self) -> Image | None:
        return next((i for i in self._queue() if i.state == State.READY), None)

    def _recycled(self) -> Image | None:
        current_id = self.store.get("current_id")
        return next((i for i in self.store.recyclable() if str(i.id) != current_id), None)

    def _backfill(self) -> None:
        if len(self._queue()) >= self.config.low_water:
            return
        for source in self._enabled_sources():
            cursor_key = f"archive_cursor:{source.name}"
            cursor = self.store.get(cursor_key) or self.store.oldest_published(source.name)
            if cursor is None:
                continue
            try:
                batch = source.older_than(self.http, cursor)
            except (requests.RequestException, ValueError, KeyError) as error:
                log.warning("%s archive failed: %s", source.name, error)
                continue
            added = self.store.add(batch)
            if added:
                log.info("%s archive: %d added", source.name, added)
            # An all-filtered batch must still move on, or the archive stalls here.
            self.store.put(cursor_key, min(c.published for c in batch) if batch else _skip_back(cursor))

    def _trim_queue(self) -> None:
        for image in self._queue()[self.config.max_queue :]:
            self._discard(image, State.DROPPED)

    def _download_upcoming(self) -> None:
        queue = self._queue()
        missing = self.config.ready_buffer - sum(i.state == State.READY for i in queue)
        for image in (i for i in queue if i.state == State.QUEUED):
            if missing <= 0:
                return
            try:
                missing -= self._download(image)
            except (requests.ConnectionError, requests.Timeout) as error:
                log.warning("network unavailable, stopping downloads: %s", error)
                return

    def _download(self, image: Image) -> bool:
        partial = self.images_dir / f"{image.id}.part"
        destination = self.images_dir / f"{image.id}.jpg"
        try:
            self.http.download(image.image_url, partial)
            wallpaper = imaging.prepare(partial, destination)
            if imaging.is_duplicate(wallpaper.dhash, self.store.hashes()):
                destination.unlink()
                raise imaging.Rejected("duplicate of a known image")
        except (imaging.Rejected, DownloadTooLarge) as error:
            log.info("rejected %s: %s", image.image_url, error)
            self.store.set_state(image.id, State.REJECTED)
            return False
        except requests.HTTPError as error:
            log.warning("download failed: %s", error)
            if self.store.count_failure(image.id) >= MAX_DOWNLOAD_ATTEMPTS:
                self.store.set_state(image.id, State.REJECTED)
            return False
        finally:
            partial.unlink(missing_ok=True)
        self.store.mark_ready(image.id, destination, wallpaper.size, wallpaper.dhash)
        return True

    # Disk

    def _evict_old_files(self) -> None:
        excess = self.store.disk_usage() - self.config.max_disk_mb * 1024 * 1024
        current_id = self.store.get("current_id")
        for image in self.store.recyclable():
            if excess <= 0:
                return
            if image.favorite or str(image.id) == current_id:
                continue
            self._discard(image, State.EXPIRED)
            excess -= image.size

    def _discard(self, image: Image, state: State) -> None:
        if image.path:
            Path(image.path).unlink(missing_ok=True)
        self.store.clear_file(image.id, state)
