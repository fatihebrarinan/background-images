"""The settings window."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from wallqueue.config import MAX_INTERVAL_HOURS, MIN_INTERVAL_HOURS  # noqa: E402
from wallqueue.desktop import BACKGROUND_SCHEMA, ICON  # noqa: E402
from wallqueue.engine import Engine  # noqa: E402
from wallqueue.sources import ALL_SOURCES  # noqa: E402

PREVIEW_WIDTH = 480
PREVIEW_HEIGHT = 270
MARGIN = 16
# After the desktop changes, how often and how many times to look for the change
# in the queue: the other process records it a moment after setting the picture.
RECORD_CHECK_MS = 250
RECORD_CHECKS = 12


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
        layout.add(self._focus_row())
        layout.add(Gtk.Separator())
        layout.add(self._sources_grid())
        layout.add(self.summary_label)
        self.add(layout)

        self.record_check: int | None = None
        self.record_checks = 0
        self.background = self._watch_background()

        self.refresh()
        self.show_all()

    def _watch_background(self) -> Gio.Settings | None:
        """Follow wallpaper changes made elsewhere: the timer, the desktop menu, a command."""
        schemas = Gio.SettingsSchemaSource.get_default()
        if schemas is None or schemas.lookup(BACKGROUND_SCHEMA, True) is None:
            return None
        background = Gio.Settings.new(BACKGROUND_SCHEMA)
        background.connect("changed::picture-uri", self._on_background_changed)
        return background

    def _on_background_changed(self, *_: object) -> None:
        if self.record_check is not None:
            GLib.source_remove(self.record_check)
        self.record_checks = 0
        self.record_check = GLib.timeout_add(RECORD_CHECK_MS, self._refresh_once_recorded)

    def _refresh_once_recorded(self) -> bool:
        """Refresh when the queue knows the picture now on the desktop.

        A picture chosen outside Wallqueue is never recorded, so give up waiting
        after a few seconds and show what the queue has.
        """
        self.record_checks += 1
        current = self.engine.store.current()
        recorded = bool(
            current
            and current.path
            and Path(current.path).as_uri() == self.background.get_string("picture-uri")
        )
        if not recorded and self.record_checks < RECORD_CHECKS:
            return GLib.SOURCE_CONTINUE
        self.record_check = None
        self.refresh()
        return GLib.SOURCE_REMOVE

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

    def _focus_row(self) -> Gtk.Widget:
        self.focus_combo = Gtk.ComboBoxText(hexpand=True)
        self.focus_handler = self.focus_combo.connect("changed", self._on_focus)
        self.today_check = Gtk.CheckButton(label="Sadece bugün", active=True)
        self.today_handler = self.today_check.connect("toggled", self._on_focus)

        row = Gtk.Box(spacing=12)
        row.add(Gtk.Label(label="Önce göster"))
        row.pack_start(self.focus_combo, True, True, 0)
        row.add(self.today_check)
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
        summary = (
            f"Sırada {status.waiting} resim, {status.ready} tanesi indirildi · "
            f"{status.disk_bytes / 1024 / 1024:.0f} MB"
        )
        if status.islamic_theme and status.focus is None:
            summary += " · Bugün İslami resimler önde (Ezan Vakti)"
        self.summary_label.set_text(summary)
        self._show_focus()
        self._show_preview(Path(current.path) if current and current.path else None)

        self.favorite_button.handler_block(self.favorite_handler)
        self.favorite_button.set_active(bool(current and current.favorite))
        self.favorite_button.handler_unblock(self.favorite_handler)
        self.favorite_button.set_sensitive(current is not None)
        self.ban_button.set_sensitive(current is not None)

        self.source_link.set_visible(bool(current and current.page_url))
        if current and current.page_url:
            self.source_link.set_uri(current.page_url)

    def _show_focus(self) -> None:
        """List the sources that are turned on and select the one in focus."""
        focus = self.engine.focus()
        self.focus_combo.handler_block(self.focus_handler)
        self.today_check.handler_block(self.today_handler)
        self.focus_combo.remove_all()
        self.focus_combo.append("", "Hepsi sırayla")
        for source in ALL_SOURCES:
            if source.name not in self.engine.config.disabled_sources:
                self.focus_combo.append(source.name, source.label)
        self.focus_combo.set_active_id(focus.source if focus else "")
        if focus:
            self.today_check.set_active(focus.until is not None)
        self.focus_combo.handler_unblock(self.focus_handler)
        self.today_check.handler_unblock(self.today_handler)

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
                with engine.exclusive():
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
        self.focus_combo.set_sensitive(not busy)
        self.today_check.set_sensitive(not busy)

    def _on_favorite(self, _: Gtk.ToggleButton) -> None:
        self.engine.toggle_favorite()

    def _on_focus(self, _: Gtk.Widget) -> None:
        source = self.focus_combo.get_active_id() or None
        self.engine.set_focus(source, self.today_check.get_active())
        if source is None:
            self.refresh()
        else:
            # Its pictures may still have to be fetched and downloaded first.
            self._in_background(Engine.show_focus)

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
    Gtk.Window.set_default_icon_name(ICON)
    application = Gtk.Application(application_id="io.github.wallqueue")
    application.connect("activate", lambda app: Window(app, engine).present())
    return application.run([])
