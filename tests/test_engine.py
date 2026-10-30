import random
import tempfile
import unittest
from pathlib import Path

import requests
from PIL import Image as PillowImage

from wallqueue.config import Config
from wallqueue.engine import MAX_TICK_GAP_SECONDS, Engine
from wallqueue.models import Candidate, State
from wallqueue.sources.base import Source
from wallqueue.store import Store

HOUR = 3600
TICK = 300


class FakeHttp:
    """Serves a distinct generated picture for each URL."""

    def __init__(self) -> None:
        self.offline = False
        self.size = (1920, 1080)

    def download(self, url: str, destination: Path) -> None:
        if self.offline:
            raise requests.ConnectionError("offline")
        noise = random.Random(url)
        tile = PillowImage.new("L", (16, 16))
        tile.putdata([noise.randrange(256) for _ in range(256)])
        tile.resize(self.size).convert("RGB").save(destination, "PNG")


class FakeSource(Source):
    def __init__(self, name: str, days: int, archive_days: int = 0) -> None:
        self.name = name
        self.label = name
        self.days = days
        self.archive_days = archive_days

    def _candidate(self, day: int) -> Candidate:
        return Candidate(
            source=self.name,
            source_id=str(day),
            title=f"{self.name} {day}",
            image_url=f"https://example.org/{self.name}/{day}",
            published=f"{2020 + day // 300}-{day // 28 % 12 + 1:02}-{day % 28 + 1:02}",
        )

    def latest(self, http: object) -> list[Candidate]:
        return [self._candidate(day + 1000) for day in range(self.days)]

    def older_than(self, http: object, day: str) -> list[Candidate]:
        batch = [self._candidate(n) for n in range(self.archive_days)]
        self.archive_days = 0
        return batch


class EngineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = 1_800_000_000.0
        self.shown: list[Path] = []
        self.http = FakeHttp()
        self.config = Config(interval_hours=2, low_water=3, ready_buffer=3)
        self.store = Store(self.root / "test.db")
        self.addCleanup(self.store.close)

    def engine(self, *sources: Source) -> Engine:
        return Engine(
            self.config,
            self.store,
            self.root / "images",
            sources=sources,
            http=self.http,
            apply_wallpaper=self.shown.append,
            clock=lambda: self.now,
        )

    def run_ticks(self, engine: Engine, count: int, step: float = TICK) -> None:
        for _ in range(count):
            self.now += step
            engine.tick()


class ScheduleTests(EngineTestCase):
    def test_first_tick_sets_a_wallpaper(self) -> None:
        self.engine(FakeSource("a", 5)).tick()
        self.assertEqual(len(self.shown), 1)

    def test_changes_after_interval_of_active_time(self) -> None:
        engine = self.engine(FakeSource("a", 8))
        engine.tick()
        self.run_ticks(engine, 2 * HOUR // TICK - 1)
        self.assertEqual(len(self.shown), 1)
        self.run_ticks(engine, 1)
        self.assertEqual(len(self.shown), 2)

    def test_time_powered_off_does_not_count(self) -> None:
        engine = self.engine(FakeSource("a", 8))
        engine.tick()
        self.run_ticks(engine, 12)  # One hour on.
        self.now += 10 * HOUR  # Asleep. The first tick after waking adds nothing.
        self.run_ticks(engine, 12)
        self.assertEqual(len(self.shown), 1)
        self.run_ticks(engine, 1)
        self.assertEqual(len(self.shown), 2)

    def test_active_time_survives_a_gap(self) -> None:
        engine = self.engine(FakeSource("a", 8))
        engine.tick()
        self.run_ticks(engine, 6)
        self.now += MAX_TICK_GAP_SECONDS + 1
        engine.tick()
        self.assertEqual(float(self.store.get("active_seconds")), 6 * TICK)

    def test_fetches_once_per_day(self) -> None:
        source = FakeSource("a", 4)
        calls = []
        original = source.latest
        source.latest = lambda http: calls.append(1) or original(http)
        engine = self.engine(source)
        self.run_ticks(engine, 3)
        self.assertEqual(len(calls), 1)
        self.run_ticks(engine, 1, step=24 * HOUR)
        self.assertEqual(len(calls), 2)


class QueueTests(EngineTestCase):
    def test_never_shows_the_same_image_while_new_ones_wait(self) -> None:
        engine = self.engine(FakeSource("a", 6), FakeSource("b", 6))
        engine.fetch()
        shown = [engine.advance().id for _ in range(12)]
        self.assertEqual(len(set(shown)), 12)

    def test_backfills_from_archive_when_low(self) -> None:
        engine = self.engine(FakeSource("a", 1, archive_days=10))
        engine.fetch()
        self.assertGreater(engine.status().waiting, 3)

    def test_archive_moves_past_a_batch_with_nothing_usable(self) -> None:
        source = FakeSource("a", 1)
        asked = []
        source.older_than = lambda http, day: asked.append(day) or []
        engine = self.engine(source)
        engine.fetch()
        engine.replenish()
        self.assertEqual(len(asked), 2)
        self.assertLess(asked[1], asked[0])

    def test_recycles_when_nothing_new_is_left(self) -> None:
        engine = self.engine(FakeSource("a", 3))
        engine.fetch()
        first = []
        for _ in range(3):
            self.now += HOUR
            first.append(engine.advance().id)
        self.now += HOUR
        self.assertEqual(engine.advance().id, first[0])

    def test_keeps_working_offline_from_the_buffer(self) -> None:
        engine = self.engine(FakeSource("a", 6))
        engine.fetch()
        self.http.offline = True
        self.assertIsNotNone(engine.advance())

    def test_no_images_at_all_keeps_the_wallpaper(self) -> None:
        self.http.offline = True
        engine = self.engine(FakeSource("a", 3))
        engine.fetch()
        self.assertIsNone(engine.advance())
        self.assertEqual(self.shown, [])

    def test_trims_the_oldest_from_the_tail(self) -> None:
        self.config.max_queue = 5
        engine = self.engine(FakeSource("a", 8))
        engine.fetch()
        waiting = self.store.waiting()
        self.assertEqual(len(waiting), 5)
        self.assertEqual(min(i.source_id for i in waiting), "1003")

    def test_rejects_portrait_images(self) -> None:
        self.http.size = (1080, 1920)
        engine = self.engine(FakeSource("a", 2))
        engine.fetch()
        self.assertEqual(engine.status().waiting, 0)

    def test_rejects_identical_pictures(self) -> None:
        original = self.http.download
        self.http.download = lambda url, destination: original("same", destination)
        engine = self.engine(FakeSource("a", 3))
        engine.fetch()
        self.assertEqual(engine.status().ready, 1)


class DiskTests(EngineTestCase):
    def test_evicts_shown_files_but_not_current_or_favorites(self) -> None:
        self.config.ready_buffer = 1
        engine = self.engine(FakeSource("a", 5))
        engine.fetch()
        favorite = engine.advance()
        engine.toggle_favorite()
        for _ in range(3):
            current = engine.advance()

        self.config.max_disk_mb = 0
        engine.replenish()

        self.assertTrue(Path(self.store.image(favorite.id).path).exists())
        self.assertTrue(Path(self.store.image(current.id).path).exists())
        self.assertEqual(
            sum(i.state == State.SHOWN and i.path is not None for i in self.store.recyclable()),
            2,
        )

    def test_ban_removes_the_file_and_moves_on(self) -> None:
        engine = self.engine(FakeSource("a", 4))
        engine.fetch()
        banned = engine.advance()
        engine.ban_current()
        record = self.store.image(banned.id)
        self.assertEqual(record.state, State.BANNED)
        self.assertFalse(Path(banned.path).exists())
        self.assertNotEqual(engine.store.current().id, banned.id)
