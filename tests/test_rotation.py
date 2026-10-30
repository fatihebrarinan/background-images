import unittest

from wallqueue.models import Image, State
from wallqueue.rotation import rotate


def image(source: str, published: str) -> Image:
    return Image(
        id=0,
        source=source,
        source_id=published,
        title="",
        credit="",
        page_url="",
        image_url="",
        published=published,
        state=State.QUEUED,
        path=None,
        size=0,
        dhash=None,
        favorite=0,
        attempts=0,
        shown_at=None,
    )


class RotateTests(unittest.TestCase):
    def test_sources_take_turns_newest_first(self) -> None:
        images = [
            image("a", "2026-01-01"),
            image("a", "2026-01-03"),
            image("b", "2026-01-02"),
            image("b", "2026-01-04"),
        ]
        order = [(i.source, i.published) for i in rotate(images, {})]
        self.assertEqual(
            order,
            [
                ("a", "2026-01-03"),
                ("b", "2026-01-04"),
                ("a", "2026-01-01"),
                ("b", "2026-01-02"),
            ],
        )

    def test_source_shown_longest_ago_goes_first(self) -> None:
        images = [image("a", "2026-01-01"), image("b", "2026-01-01")]
        order = rotate(images, {"a": 200.0, "b": 100.0})
        self.assertEqual([i.source for i in order], ["b", "a"])

    def test_plentiful_source_fills_the_tail(self) -> None:
        images = [image("a", f"2026-01-0{day}") for day in range(1, 5)]
        images.append(image("b", "2026-01-01"))
        self.assertEqual(rotate(images, {})[-1].published, "2026-01-01")
        self.assertEqual(rotate(images, {})[-1].source, "a")
