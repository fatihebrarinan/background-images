import io
import threading
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from PIL import Image as PillowImage

from tests.test_engine import HOUR, EngineTestCase, FakeSource
from tests.test_ezanvakti import SharedFilesMixin, entry
from wallqueue import cli
from wallqueue.engine import FOCUS_READY, Engine
from wallqueue.models import State
from wallqueue.sources.islami import Islami

DAY = 24 * HOUR


class FocusTests(EngineTestCase):
    def prepare(self, b_days: int = 6, b_archive: int = 0) -> Engine:
        # Plain rotation would start with "a": it wins the tie by name.
        engine = self.engine(FakeSource("a", 10), FakeSource("b", b_days, b_archive))
        engine.fetch()
        return engine

    def test_focused_source_goes_first(self) -> None:
        engine = self.prepare()
        engine.set_focus("b")
        engine.replenish()
        self.assertEqual([engine.advance().source for _ in range(4)], ["b"] * 4)

    def test_falls_back_when_the_focused_source_runs_out(self) -> None:
        engine = self.prepare(b_days=2)
        engine.set_focus("b")
        sources = [engine.advance().source for _ in range(3)]
        self.assertEqual(sources, ["b", "b", "a"])

    def test_today_only_ends_at_midnight(self) -> None:
        engine = self.prepare()
        focus = engine.set_focus("b", today_only=True)
        self.assertEqual(focus.until, date.fromtimestamp(self.now).isoformat())
        self.now += DAY
        self.assertIsNone(engine.focus())
        self.assertEqual(engine.advance().source, "a")

    def test_until_turned_off(self) -> None:
        engine = self.prepare()
        engine.set_focus("b")
        self.now += 30 * DAY
        self.assertEqual(engine.focus().source, "b")
        engine.set_focus(None)
        self.assertIsNone(engine.focus())

    def test_turning_the_source_off_ends_the_focus(self) -> None:
        engine = self.prepare()
        engine.set_focus("b")
        self.config.disabled_sources = ["b"]
        self.assertIsNone(engine.focus())
        self.assertEqual(engine.advance().source, "a")

    def test_rejects_unknown_and_turned_off_sources(self) -> None:
        engine = self.prepare()
        with self.assertRaises(ValueError):
            engine.set_focus("nope")
        self.config.disabled_sources = ["b"]
        with self.assertRaises(ValueError):
            engine.set_focus("b")

    def test_downloads_focused_pictures_even_with_a_full_buffer(self) -> None:
        engine = self.prepare(b_days=FOCUS_READY + 2)
        ready = [i for i in self.store.waiting() if i.state == State.READY]
        self.assertEqual(len(ready), self.config.ready_buffer)
        engine.set_focus("b")
        engine.replenish()
        ready_b = [i for i in self.store.waiting() if i.state == State.READY and i.source == "b"]
        self.assertEqual(len(ready_b), FOCUS_READY)

    def test_refills_the_focused_source_from_its_archive(self) -> None:
        # Plenty waiting overall, so the usual low-water backfill would not run.
        engine = self.prepare(b_days=1, b_archive=5)
        engine.set_focus("b")
        engine.replenish()
        waiting_b = [i for i in self.store.waiting() if i.source == "b"]
        self.assertEqual(len(waiting_b), 6)

    def test_fetches_a_focused_source_that_has_nothing_yet(self) -> None:
        self.config.disabled_sources = ["b"]
        engine = self.prepare()
        self.config.disabled_sources = []
        engine.set_focus("b")
        engine.replenish()
        self.assertEqual(engine.advance().source, "b")

    def test_switches_to_the_focused_source_at_once(self) -> None:
        engine = self.prepare()
        engine.advance()
        self.assertEqual(self.store.current().source, "a")
        engine.set_focus("b")
        shown = engine.show_focus()
        self.assertEqual(shown.source, "b")
        self.assertEqual(self.store.current().id, shown.id)
        self.assertEqual(len(self.shown), 2)
        self.assertEqual(float(self.store.get("active_seconds")), 0)

    def test_keeps_a_wallpaper_already_from_the_source(self) -> None:
        engine = self.prepare()
        engine.set_focus("b")
        engine.show_focus()
        engine.set_focus("b", today_only=True)
        self.assertIsNone(engine.show_focus())
        self.assertEqual(len(self.shown), 1)

    def test_no_switch_without_focus_or_a_downloaded_picture(self) -> None:
        engine = self.prepare()
        engine.advance()
        self.assertIsNone(engine.show_focus())
        self.http.offline = True
        for image in self.store.waiting():
            if image.source == "b":
                self.store.clear_file(image.id, State.QUEUED)
        engine.set_focus("b")
        self.assertIsNone(engine.show_focus())
        self.assertEqual(self.store.current().source, "a")

    def test_status_reports_the_focus(self) -> None:
        engine = self.prepare()
        self.assertIsNone(engine.status().focus)
        engine.set_focus("b", today_only=True)
        self.assertEqual(engine.status().focus.source, "b")


class FocusAndThemeTests(SharedFilesMixin, EngineTestCase):
    def test_the_users_focus_beats_the_theme_and_added_pictures_beat_both(self) -> None:
        today = date.fromtimestamp(self.now)
        self.write_list([entry(n) for n in range(5)])
        self.write_hint(today)
        engine = self.engine(FakeSource("a", 6), Islami(today=lambda: today))
        engine.fetch()
        picture = self.root / "x.png"
        PillowImage.new("RGB", (2400, 1350), "teal").save(picture)
        added, _ = engine.add_local(picture)
        engine.set_focus("a")
        # The switch picks the focused source; the added picture keeps its place.
        self.assertEqual(engine.show_focus().source, "a")
        self.assertEqual(engine.advance().id, added.id)
        self.assertEqual(engine.advance().source, "a")
        engine.set_focus(None)
        self.assertEqual(engine.advance().source, Islami.name)


class CommandLineTests(EngineTestCase):
    def run_cli(self, *arguments: str) -> tuple[int, str, str, list]:
        engine = self.engine(FakeSource("a", 10), FakeSource("b", 6))
        out, err, notes = io.StringIO(), io.StringIO(), []
        with (
            mock.patch("sys.argv", ["wallqueue", *arguments]),
            mock.patch.object(cli.Engine, "create", return_value=engine),
            mock.patch.object(cli.desktop, "notify", lambda *text: notes.append(text)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = cli.main()
        return code, out.getvalue(), err.getvalue(), notes

    def test_next_with_notify_names_the_new_wallpaper(self) -> None:
        self.engine(FakeSource("a", 3)).fetch()
        code, out, _, notes = self.run_cli("next", "--notify")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(notes, [(self.store.current().title, "")])

    def test_next_without_notify_stays_quiet(self) -> None:
        self.engine(FakeSource("a", 3)).fetch()
        _, _, _, notes = self.run_cli("next")
        self.assertEqual(notes, [])

    def test_next_with_nothing_ready_says_so(self) -> None:
        self.http.offline = True
        code, _, _, notes = self.run_cli("next", "--notify")
        self.assertEqual(code, 1)
        self.assertEqual(notes[0][0], "Duvar kâğıdı değişmedi")

    def test_focus_switches_to_the_source(self) -> None:
        code, out, _, _ = self.run_cli("focus", "b", "--today")
        self.assertEqual(code, 0)
        self.assertIn("today only", out)
        self.assertIn("Showing: b", out)
        self.assertEqual(self.store.current().source, "b")

    def test_focus_offline_says_it_waits(self) -> None:
        self.http.offline = True
        code, out, _, _ = self.run_cli("focus", "b")
        self.assertEqual(code, 0)
        self.assertIn("No b picture is downloaded yet", out)
        self.assertEqual(self.shown, [])

    def test_focus_off_and_unknown(self) -> None:
        self.run_cli("focus", "b")
        code, out, _, _ = self.run_cli("focus", "off")
        self.assertEqual((code, out.strip()), (0, "Focus off."))
        code, _, err, _ = self.run_cli("focus", "nope")
        self.assertEqual(code, 1)
        self.assertIn("unknown source", err)
        self.assertIn("a, b", err)

    def test_status_shows_the_focus(self) -> None:
        self.run_cli("focus", "b")
        _, out, _, _ = self.run_cli("status")
        self.assertIn("Focus:   b (until turned off)", out)


class ExclusiveTests(EngineTestCase):
    def test_a_second_change_waits_for_the_first(self) -> None:
        engine = self.engine()
        other = self.engine()
        order = []

        def other_change() -> None:
            with other.exclusive():
                order.append("other")

        with engine.exclusive():
            thread = threading.Thread(target=other_change)
            thread.start()
            thread.join(0.2)
            order.append("first")
        thread.join(5)
        self.assertEqual(order, ["first", "other"])
        self.assertTrue(Path(engine.lock_path).exists())
