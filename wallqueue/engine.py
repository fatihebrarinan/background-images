"""The application logic: collect images, keep the queue healthy, show the next one."""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import requests

from wallqueue import ezanvakti, imaging
from wallqueue.config import Config, data_dir
from wallqueue.desktop import set_wallpaper
from wallqueue.http import DownloadTooLarge, Http
from wallqueue.models import Candidate, Image, State
from wallqueue.rotation import rotate
from wallqueue.sources import ALL_SOURCES, Source
from wallqueue.sources.islami import Islami
from wallqueue.store import Store

log = logging.getLogger(__name__)

# Ticks run every 5 minutes. A longer gap means the computer was off or asleep,
# and that time must not count towards the wallpaper interval.
MAX_TICK_GAP_SECONDS = 15 * 60
FETCH_RETRY_SECONDS = 15 * 60
MAX_DOWNLOAD_ATTEMPTS = 3
ARCHIVE_SKIP_DAYS = 30
# Pictures the user adds by hand with `wallqueue add`.
LOCAL_SOURCE = "yerel"


def _skip_back(day: str) -> str:
    return (date.fromisoformat(day) - timedelta(days=ARCHIVE_SKIP_DAYS)).isoformat()


@dataclass(frozen=True)
class Status:
    current: Image | None
    waiting: int
    ready: int
    disk_bytes: int
    active_seconds: float
    islamic_theme: bool = False


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
        """Ask every source for new images. Returns whether any online source answered."""
        self.store.put("last_fetch_attempt", self.clock())
        sources = self._enabled_sources()
        # Local sources always answer, so they must not stop the retries while offline.
        reached = not any(source.needs_network for source in sources)
        for source in sources:
            try:
                added = self.store.add(source.latest(self.http))
            except (requests.RequestException, ValueError, KeyError, SyntaxError) as error:
                log.warning("%s failed: %s", source.name, error)
                continue
            reached = reached or source.needs_network
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
        return self.show(image)

    def show(self, image: Image) -> Image:
        """Put a downloaded image on the desktop and restart the interval."""
        self.apply_wallpaper(Path(image.path))
        self.store.mark_shown(image.id, self.clock())
        self.store.put("active_seconds", 0)
        self._set_pinned([i for i in self._pinned() if i != image.id])
        log.info("showing %s: %s", image.source, image.title)
        self.replenish()
        return self.store.image(image.id)

    def add_local(
        self, path: Path, title: str = "", credit: str = "", page_url: str = ""
    ) -> tuple[Image, bool]:
        """Copy a picture from disk into the queue as the next one to show.

        The user chose it on purpose, so any readable image is taken whatever its
        shape. Adding the same file again reuses its entry. Returns the image and
        whether it was new. Raises OSError or imaging.Rejected when unusable.
        """
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        image = self.store.find(LOCAL_SOURCE, digest)
        created = image is None
        if image is None or not image.path or not Path(image.path).exists():
            partial = self.images_dir / f"{LOCAL_SOURCE}-{digest[:16]}.part"
            try:
                wallpaper = imaging.prepare(path, partial, require_fit=False)
                if image is None:
                    self.store.add([self._local_candidate(path, digest, title, credit, page_url)])
                    image = self.store.find(LOCAL_SOURCE, digest)
                destination = self.images_dir / f"{image.id}.jpg"
                partial.replace(destination)
            finally:
                partial.unlink(missing_ok=True)
            self.store.mark_ready(image.id, destination, wallpaper.size, wallpaper.dhash)

        # The picture on screen stays shown; anything else waits at the front.
        if str(image.id) == self.store.get("current_id"):
            self.store.set_state(image.id, State.SHOWN)
        else:
            self.store.set_state(image.id, State.READY)
            self._set_pinned([image.id, *(i for i in self._pinned() if i != image.id)])
        return self.store.image(image.id), created

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
            islamic_theme=self._islamic_theme(),
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
        """Waiting images in showing order.

        Pictures added by hand come first, newest addition first. On the religious
        days Ezan Vakti marks, its Islamic pictures come next, so the next ready one
        is shown and the next queued one is downloaded first. Everything else
        follows the usual rotation.
        """
        waiting = self.store.waiting(self.config.disabled_sources)
        pinned = self._pinned()
        theme = self._islamic_theme()

        def rank(image: Image) -> int:
            if image.id in pinned:
                return pinned.index(image.id)
            return len(pinned) + (0 if theme and image.source == Islami.name else 1)

        return sorted(rotate(waiting, self.store.source_last_shown()), key=rank)

    def _islamic_theme(self) -> bool:
        if all(source.name != Islami.name for source in self._enabled_sources()):
            return False
        return ezanvakti.islamic_theme(date.fromtimestamp(self.clock()))

    def _pinned(self) -> list[int]:
        return [int(i) for i in (self.store.get("pinned_ids") or "").split(",") if i]

    def _set_pinned(self, ids: list[int]) -> None:
        self.store.put("pinned_ids", ",".join(map(str, ids)))

    def _local_candidate(
        self, path: Path, digest: str, title: str, credit: str, page_url: str
    ) -> Candidate:
        return Candidate(
            source=LOCAL_SOURCE,
            source_id=digest,
            title=title or path.stem,
            image_url=path.resolve().as_uri(),
            published=date.fromtimestamp(self.clock()).isoformat(),
            page_url=page_url,
            credit=credit,
        )

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
