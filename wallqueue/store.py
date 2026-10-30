"""SQLite persistence for images and small pieces of runtime state."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

from wallqueue.models import Candidate, Image, State

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT NOT NULL,
    credit TEXT NOT NULL,
    page_url TEXT NOT NULL,
    image_url TEXT NOT NULL,
    published TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    path TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    dhash TEXT,
    favorite INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    shown_at REAL,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS images_state ON images (state);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The timer and the settings window may write at the same moment.
        self._db = sqlite3.connect(path, timeout=30, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def _images(self, query: str, *parameters: object) -> list[Image]:
        return [Image(**row) for row in self._db.execute(query, parameters)]

    # Runtime state

    def get(self, key: str, default: str | None = None) -> str | None:
        row = self._db.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def put(self, key: str, value: object) -> None:
        self._db.execute(
            "INSERT INTO state (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    # Queries

    def image(self, image_id: int) -> Image | None:
        found = self._images("SELECT * FROM images WHERE id = ?", image_id)
        return found[0] if found else None

    def current(self) -> Image | None:
        current_id = self.get("current_id")
        return self.image(int(current_id)) if current_id else None

    def waiting(self, disabled_sources: Iterable[str] = ()) -> list[Image]:
        """Images that have not been shown yet."""
        disabled = set(disabled_sources)
        images = self._images(
            "SELECT * FROM images WHERE state IN (?, ?)", State.QUEUED, State.READY
        )
        return [image for image in images if image.source not in disabled]

    def source_last_shown(self) -> dict[str, float]:
        rows = self._db.execute(
            "SELECT source, MAX(shown_at) AS shown_at FROM images "
            "WHERE shown_at IS NOT NULL GROUP BY source"
        )
        return {row["source"]: row["shown_at"] for row in rows}

    def oldest_published(self, source: str) -> str | None:
        row = self._db.execute(
            "SELECT MIN(published) AS published FROM images WHERE source = ?", (source,)
        ).fetchone()
        return row["published"]

    def recyclable(self) -> list[Image]:
        """Files already shown, the one left unseen the longest first."""
        return self._images(
            "SELECT * FROM images WHERE state = ? AND path IS NOT NULL "
            "ORDER BY shown_at",
            State.SHOWN,
        )

    def hashes(self) -> list[str]:
        rows = self._db.execute("SELECT dhash FROM images WHERE dhash IS NOT NULL")
        return [row["dhash"] for row in rows]

    def disk_usage(self) -> int:
        return self._db.execute(
            "SELECT COALESCE(SUM(size), 0) FROM images WHERE path IS NOT NULL"
        ).fetchone()[0]

    # Changes

    def add(self, candidates: Iterable[Candidate]) -> int:
        """Insert unknown candidates and return how many were new."""
        changes_before = self._db.total_changes
        for candidate in candidates:
            self._db.execute(
                "INSERT OR IGNORE INTO images "
                "(source, source_id, title, credit, page_url, image_url, published) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    candidate.source,
                    candidate.source_id,
                    candidate.title,
                    candidate.credit,
                    candidate.page_url,
                    candidate.image_url,
                    candidate.published,
                ),
            )
        return self._db.total_changes - changes_before

    def mark_ready(self, image_id: int, path: Path, size: int, dhash: str) -> None:
        self._db.execute(
            "UPDATE images SET state = ?, path = ?, size = ?, dhash = ? WHERE id = ?",
            (State.READY, str(path), size, dhash, image_id),
        )

    def mark_shown(self, image_id: int, when: float) -> None:
        self._db.execute(
            "UPDATE images SET state = ?, shown_at = ? WHERE id = ?",
            (State.SHOWN, when, image_id),
        )
        self.put("current_id", image_id)

    def set_state(self, image_id: int, state: State) -> None:
        self._db.execute("UPDATE images SET state = ? WHERE id = ?", (state, image_id))

    def clear_file(self, image_id: int, state: State) -> None:
        self._db.execute(
            "UPDATE images SET state = ?, path = NULL, size = 0 WHERE id = ?",
            (state, image_id),
        )

    def count_failure(self, image_id: int) -> int:
        self._db.execute(
            "UPDATE images SET attempts = attempts + 1 WHERE id = ?", (image_id,)
        )
        return self.image(image_id).attempts

    def set_favorite(self, image_id: int, favorite: bool) -> None:
        self._db.execute(
            "UPDATE images SET favorite = ? WHERE id = ?", (int(favorite), image_id)
        )
