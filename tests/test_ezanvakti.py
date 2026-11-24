import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import requests
from PIL import Image as PillowImage

from tests.test_engine import HOUR, EngineTestCase, FakeSource
from wallqueue import cli, ezanvakti
from wallqueue.engine import LOCAL_SOURCE, Engine
from wallqueue.models import State
from wallqueue.sources.islami import Islami

class OfflineSource(FakeSource):
    def latest(self, http: object) -> list:
        raise requests.ConnectionError("offline")


SAMPLE = (
    Path(__file__).resolve().parents[2] / "linux-ezan-vakti" / "data" / "resimler.json"
)


def entry(number: int, width: int = 1920, height: int = 1080) -> dict:
    return {
        "dosya": f"File:Picture {number}.jpg",
        "aciklama": f"Resim {number}",
        "kategori": "cami",
        "sayfa_url": f"https://commons.wikimedia.org/wiki/File:Picture_{number}.jpg",
        "thumb_url": f"https://example.org/islami/{number}.jpg",
        "genislik": width,
        "yukseklik": height,
        "yazar": "Someone",
        "lisans": "CC BY-SA 4.0",
        "lisans_url": None,
        "atif_gerekli": True,
    }


class SharedFilesMixin(unittest.TestCase):
    """Points the XDG directories at a temporary folder for the whole test."""

    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.xdg = Path(directory.name)
        environment = {
            "XDG_DATA_HOME": str(self.xdg / "data"),
            "XDG_CACHE_HOME": str(self.xdg / "cache"),
            "XDG_CONFIG_HOME": str(self.xdg / "config"),
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_list(self, entries: list[dict] | str) -> None:
        path = ezanvakti.images_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        text = entries if isinstance(entries, str) else json.dumps({"resimler": entries})
        path.write_text(text, encoding="utf-8")

    def write_hint(self, day: date, theme: bool = True) -> None:
        path = ezanvakti.hint_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        hint = {"tarih": day.isoformat(), "islami_tema": theme, "hicri": "1 Ramazan 1448"}
        path.write_text(json.dumps(hint), encoding="utf-8")


class SharedFileTests(SharedFilesMixin):
    def test_missing_or_broken_files_give_nothing(self) -> None:
        self.assertEqual(ezanvakti.load_images(), [])
        self.assertFalse(ezanvakti.islamic_theme(date(2027, 2, 8)))
        for broken in ("{not json", "[]", '{"resimler": {}}', '{"resimler": [1, "x"]}'):
            self.write_list(broken)
            self.assertEqual(ezanvakti.load_images(), [])

    def test_theme_only_on_the_hinted_day(self) -> None:
        day = date(2027, 2, 8)
        self.write_hint(day)
        self.assertTrue(ezanvakti.islamic_theme(day))
        self.assertFalse(ezanvakti.islamic_theme(day + timedelta(days=1)))
        self.write_hint(day, theme=False)
        self.assertFalse(ezanvakti.islamic_theme(day))
        ezanvakti.hint_path().write_text("broken")
        self.assertFalse(ezanvakti.islamic_theme(day))


class IslamiSourceTests(SharedFilesMixin):
    def source(self, day: date) -> Islami:
        return Islami(today=lambda: day)

    @unittest.skipUnless(SAMPLE.exists(), "Ezan Vakti sample list not found")
    def test_reads_the_sample_list(self) -> None:
        self.write_list(SAMPLE.read_text(encoding="utf-8"))
        schedule = self.source(date(2026, 11, 24)).schedule()
        self.assertGreater(len(schedule), 50)
        by_file = {candidate.source_id: candidate for candidate in schedule}
        suleymaniye = by_file[
            "File:Mezquita de Solimán, Estambul, Turquía, 2024-09-28, DD 147-149 HDR.jpg"
        ]
        self.assertEqual(suleymaniye.title, "Süleymaniye Camii, İstanbul")
        self.assertEqual(suleymaniye.credit, "Diego Delso · CC BY-SA 4.0")
        self.assertTrue(suleymaniye.image_url.startswith("https://thumb.wikimedia.org/"))
        self.assertTrue(suleymaniye.page_url.startswith("https://commons.wikimedia.org/"))

    def test_skips_pictures_that_do_not_fit_the_screen(self) -> None:
        self.write_list([entry(1), entry(2, 1920, 1920), {"dosya": "File:broken.jpg"}])
        schedule = self.source(date(2026, 11, 24)).schedule()
        self.assertEqual([c.source_id for c in schedule], ["File:Picture 1.jpg"])

    def test_one_new_picture_a_day_and_the_whole_list_in_one_cycle(self) -> None:
        self.write_list([entry(n) for n in range(10)])
        start = date(2026, 11, 24)
        first = self.source(start).latest(None)
        self.assertEqual(len(first), 3)
        seen = {c.source_id for c in first}
        # The first answer already covers two earlier days, so 7 more days finish it.
        for offset in range(1, 8):
            today = {c.source_id for c in self.source(start + timedelta(days=offset)).latest(None)}
            self.assertEqual(len(today - seen), 1)
            seen |= today
        self.assertEqual(len(seen), 10)

    def test_archive_walks_back_through_the_rest(self) -> None:
        self.write_list([entry(n) for n in range(20)])
        source = self.source(date(2026, 11, 24))
        seen = {c.source_id for c in source.latest(None)}
        cursor = min(c.published for c in source.latest(None))
        while batch := source.older_than(None, cursor):
            self.assertLessEqual(len(batch), 7)
            seen |= {c.source_id for c in batch}
            cursor = min(c.published for c in batch)
        self.assertEqual(len(seen), 20)


class IslamicThemeTests(SharedFilesMixin, EngineTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_list([entry(n) for n in range(5)])
        self.today = date.fromtimestamp(self.now)
        self.islami = Islami(today=lambda: self.today)

    def prepare(self) -> Engine:
        # With nothing shown yet, plain rotation breaks the tie by name: "a" first.
        engine = self.engine(FakeSource("a", 6), self.islami)
        engine.fetch()
        return engine

    def test_normal_days_keep_the_rotation(self) -> None:
        engine = self.prepare()
        self.assertEqual(engine.advance().source, "a")

    def test_religious_days_show_a_ready_islamic_picture_first(self) -> None:
        self.write_hint(self.today)
        engine = self.prepare()
        self.assertTrue(engine.status().islamic_theme)
        sources = [engine.advance().source for _ in range(3)]
        self.assertEqual(sources, [Islami.name] * 3)

    def test_hint_for_another_day_is_ignored(self) -> None:
        self.write_hint(self.today - timedelta(days=1))
        engine = self.prepare()
        self.assertEqual(engine.advance().source, "a")

    def test_turned_off_source_turns_off_the_theme(self) -> None:
        self.write_hint(self.today)
        engine = self.prepare()
        self.config.disabled_sources = [Islami.name]
        self.assertFalse(engine.status().islamic_theme)
        self.assertEqual(engine.advance().source, "a")

    def test_falls_back_when_no_islamic_picture_is_ready(self) -> None:
        self.write_hint(self.today)
        engine = self.prepare()
        for image in self.store.waiting():
            if image.source == Islami.name:
                self.store.set_state(image.id, State.REJECTED)
        self.assertEqual(engine.advance().source, "a")

    def test_local_list_does_not_hide_being_offline(self) -> None:
        self.http.offline = True
        engine = self.engine(OfflineSource("a", 3), self.islami)
        self.assertFalse(engine.fetch())
        self.assertIsNone(self.store.get("last_fetch_day"))
        self.assertGreater(len(self.store.waiting()), 0)


class AddTests(SharedFilesMixin, EngineTestCase):
    def picture(
        self, name: str, size: tuple[int, int] = (2400, 1350), color: str = "teal"
    ) -> Path:
        path = self.root / name
        PillowImage.new("RGB", size, color).save(path)
        return path

    def test_added_picture_is_shown_next(self) -> None:
        engine = self.engine(FakeSource("a", 4))
        engine.fetch()
        image, created = engine.add_local(self.picture("x.png"), "Başlık", "Ben", "https://x")
        self.assertTrue(created)
        self.assertEqual(
            (image.source, image.title, image.state), (LOCAL_SOURCE, "Başlık", State.READY)
        )
        self.assertEqual(engine.advance().id, image.id)
        self.assertNotEqual(engine.advance().source, LOCAL_SOURCE)

    def test_latest_addition_goes_first_and_beats_the_theme(self) -> None:
        self.write_hint(date.fromtimestamp(self.now))
        self.write_list([entry(n) for n in range(3)])
        islami = Islami(today=lambda: date.fromtimestamp(self.now))
        engine = self.engine(FakeSource("a", 2), islami)
        engine.fetch()
        first, _ = engine.add_local(self.picture("1.png", color="red"))
        second, _ = engine.add_local(self.picture("2.png", color="blue"))
        self.assertEqual([engine.advance().id for _ in range(2)], [second.id, first.id])
        self.assertEqual(engine.advance().source, Islami.name)

    def test_same_file_twice_is_not_duplicated(self) -> None:
        engine = self.engine(FakeSource("a", 2))
        path = self.picture("x.png")
        first, _ = engine.add_local(path)
        copy = self.root / "copy.png"
        shutil.copy(path, copy)
        again, created = engine.add_local(copy)
        self.assertFalse(created)
        self.assertEqual(again.id, first.id)
        local = [i for i in self.store.waiting() if i.source == LOCAL_SOURCE]
        self.assertEqual(len(local), 1)

    def test_re_adding_a_shown_picture_queues_it_again(self) -> None:
        engine = self.engine(FakeSource("a", 3))
        engine.fetch()
        path = self.picture("x.png")
        image, _ = engine.add_local(path)
        engine.advance()
        self.now += HOUR
        engine.advance()
        again, created = engine.add_local(path)
        self.assertFalse(created)
        self.assertEqual(again.state, State.READY)
        self.assertEqual(engine.advance().id, image.id)

    def test_any_shape_is_accepted(self) -> None:
        engine = self.engine()
        image, _ = engine.add_local(self.picture("square.png", (800, 800)))
        self.assertTrue(Path(image.path).exists())

    def test_added_pictures_survive_trimming(self) -> None:
        self.config.max_queue = 3
        engine = self.engine(FakeSource("a", 6))
        engine.fetch()
        image, _ = engine.add_local(self.picture("x.png"))
        engine.replenish()
        self.assertEqual(self.store.image(image.id).state, State.READY)

    def run_cli(self, *arguments: str) -> tuple[int, str, str]:
        engine = self.engine(FakeSource("a", 2))
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch("sys.argv", ["wallqueue", *arguments]),
            mock.patch.object(cli.Engine, "create", return_value=engine),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli.main()
        return code, out.getvalue(), err.getvalue()

    def test_cli_add_now_sets_the_wallpaper(self) -> None:
        path = self.picture("x.png")
        code, out, _ = self.run_cli("add", str(path), "--title", "Kubbe", "--now")
        self.assertEqual(code, 0)
        self.assertIn("Kubbe", out)
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.store.current().title, "Kubbe")

    def test_cli_add_without_now_leaves_the_wallpaper(self) -> None:
        code, out, err = self.run_cli("add", str(self.picture("x.png", (800, 800))))
        self.assertEqual(code, 0)
        self.assertIn("showing next", out)
        self.assertIn("note", err)
        self.assertEqual(self.shown, [])

    def test_cli_add_reports_missing_and_unreadable_files(self) -> None:
        code, _, err = self.run_cli("add", str(self.root / "nope.jpg"))
        self.assertEqual(code, 1)
        self.assertIn("no such file", err)
        text = self.root / "notes.jpg"
        text.write_text("not a picture")
        code, _, err = self.run_cli("add", str(text))
        self.assertEqual(code, 1)
        self.assertIn("cannot add", err)
        self.assertEqual(self.store.waiting(), [])
