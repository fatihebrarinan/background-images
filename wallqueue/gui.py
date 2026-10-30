"""The settings window."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, GLib, Gtk  # noqa: E402

from wallqueue.config import MAX_INTERVAL_HOURS, MIN_INTERVAL_HOURS  # noqa: E402
from wallqueue.engine import Engine  # noqa: E402
from wallqueue.sources import ALL_SOURCES  # noqa: E402

PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 270
MARGIN = 16


class Window(Gtk.ApplicationWindow):
    def __init__(self, application: Gtk.Application, engine: Engine) -> None:
        super().__init__(application=application, title="Wallqueue", resizable=False)
        self.engine = engine
        self.connect("destroy", lambda _: engine.store.close())

        self.preview = Gtk.Image()
        self.preview.set_size_request(PREVIEW_WIDTH, PREVIEW_HEIGHT)
        self.title_label = self._label(wrap=True)
        self.credit_label = self._label(wrap=True, dim=True)
        self.summary_label = self._label(dim=True)

        self.next_button = Gtk.Button(label="Sonraki resim")
        self.next_button.connect("clicked", lambda _: self._in_background(Engine.advance))
        self.favorite_button = Gtk.ToggleButton(label="Favori")
        self.favorite_handler = self.favorite_button.connect("toggled", self._on_favorite)
        self.ban_button = Gtk.Button(label="Bir daha gösterme")
        self.ban_button.connect("clicked", lambda _: self._in_background(Engine.ban_current))
        self.source_link = Gtk.LinkButton(uri="https://example.org", label="Kaynak")

        buttons = Gtk.Box(spacing=6)
        for button in (self.next_button, self.favorite_button, self.ban_button):
            buttons.pack_start(button, False, False, 0)
        buttons.pack_end(self.source_link, False, False, 0)

        layout = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=MARGIN)
        layout.add(self.preview)
        layout.add(self.title_label)
        layout.add(self.credit_label)
        layout.add(buttons)
        layout.add(Gtk.Separator())
        layout.add(self._interval_row())
        layout.add(Gtk.Separator())
        layout.add(self._sources_grid())
        layout.add(self.summary_label)
        self.add(layout)

        self.refresh()
        self.show_all()

    @staticmethod
    def _label(wrap: bool = False, dim: bool = False) -> Gtk.Label:
        label = Gtk.Label(xalign=0, wrap=wrap, max_width_chars=60)
        if dim:
            label.get_style_context().add_class("dim-label")
        return label

    def _interval_row(self) -> Gtk.Widget:
        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, MIN_INTERVAL_HOURS, MAX_INTERVAL_HOURS, 1
        )
        scale.set_value(self.engine.config.interval_hours)
        scale.set_round_digits(0)
        scale.set_hexpand(True)
        scale.connect("format-value", lambda _, value: f"{value:.0f} saat")
        scale.connect("value-changed", self._on_interval)

        row = Gtk.Box(spacing=12)
        row.add(Gtk.Label(label="Değişim sıklığı"))
        row.pack_start(scale, True, True, 0)
        return row

    def _sources_grid(self) -> Gtk.Widget:
        grid = Gtk.Grid(row_spacing=6, column_spacing=24, column_homogeneous=True)
        for index, source in enumerate(ALL_SOURCES):
            check = Gtk.CheckButton(label=source.label)
            check.set_active(source.name not in self.engine.config.disabled_sources)
            check.connect("toggled", self._on_source, source.name)
            grid.attach(check, index % 2, index // 2, 1, 1)
        return grid

    def refresh(self) -> None:
        status = self.engine.status()
        current = status.current
        self.title_label.set_text(current.title if current else "Henüz duvar kağıdı yok")
        self.credit_label.set_text(current.credit if current else "")
        self.summary_label.set_text(
            f"Sırada {status.waiting} resim, {status.ready} tanesi indirildi · "
            f"{status.disk_bytes / 1024 / 1024:.0f} MB"
        )
        self._show_preview(Path(current.path) if current and current.path else None)

        self.favorite_button.handler_block(self.favorite_handler)
        self.favorite_button.set_active(bool(current and current.favorite))
        self.favorite_button.handler_unblock(self.favorite_handler)
        self.favorite_button.set_sensitive(current is not None)
        self.ban_button.set_sensitive(current is not None)

        self.source_link.set_visible(bool(current and current.page_url))
        if current and current.page_url:
            self.source_link.set_uri(current.page_url)

    def _show_preview(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.preview.clear()
            return
        self.preview.set_from_pixbuf(
            GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), PREVIEW_WIDTH, PREVIEW_HEIGHT)
        )

    def _in_background(self, action: Callable[[Engine], object]) -> None:
        """Run an engine action off the UI thread; it may download for a while."""

        def work() -> None:
            # SQLite connections belong to their thread, so this needs its own engine.
            engine = Engine.create()
            try:
                action(engine)
            finally:
                engine.store.close()
                GLib.idle_add(self._finish_background)

        self._set_busy(True)
        threading.Thread(target=work, daemon=True).start()

    def _finish_background(self) -> bool:
        self._set_busy(False)
        self.refresh()
        return GLib.SOURCE_REMOVE

    def _set_busy(self, busy: bool) -> None:
        self.next_button.set_sensitive(not busy)
        self.ban_button.set_sensitive(not busy)

    def _on_favorite(self, _: Gtk.ToggleButton) -> None:
        self.engine.toggle_favorite()

    def _on_interval(self, scale: Gtk.Scale) -> None:
        self.engine.config.interval_hours = round(scale.get_value())
        self.engine.config.save()

    def _on_source(self, check: Gtk.CheckButton, name: str) -> None:
        disabled = set(self.engine.config.disabled_sources)
        if check.get_active():
            disabled.discard(name)
        else:
            disabled.add(name)
        self.engine.config.disabled_sources = sorted(disabled)
        self.engine.config.save()
        self.refresh()


def run(engine: Engine) -> int:
    application = Gtk.Application(application_id="io.github.wallqueue")
    application.connect("activate", lambda app: Window(app, engine).present())
    return application.run([])
