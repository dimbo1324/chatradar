"""The Overview's "recent events" card: newest first, relative times that keep counting."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from chatimport.gui.format import format_ago
from chatimport.gui.i18n import tr
from chatimport.gui.icons import icon_pixmap
from chatimport.gui.locales import overview as _overview_strings
from chatimport.gui.strings import current_language
from chatimport.gui.stylesheet import tone_colors
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.card import Card
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.labels import ElidedLabel, make_label

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from chatimport.gui.kit import UiKit
    from chatimport.gui.models.feed import FeedEvent

_ = _overview_strings


class FeedRow(QFrame):
    def __init__(self, kit: UiKit, event: FeedEvent) -> None:
        super().__init__()
        self.kit = kit
        self.item = event
        self._icon = QLabel()
        self._text = ElidedLabel()
        self._when = QLabel()
        self._when.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._when.setProperty("role", "muted")
        self._row = QHBoxLayout(self)
        self._row.addWidget(self._icon)
        self._row.addWidget(self._text, 1)
        self._row.addWidget(self._when)
        bind_kit(kit, theme=self._restyle, zoom=self._restyle, language=self.retranslate)
        self._restyle()
        self.retranslate()

    def retranslate(self) -> None:
        self._text.setText(tr(f"overview.{self.item.key}", title=self.item.title))
        self.setAccessibleName(self._text.full_text())

    def refresh_time(self, now: datetime) -> None:
        age = max((now - self.item.at).total_seconds(), 0.0)
        self._when.setText(format_ago(age, current_language()))

    def _restyle(self) -> None:
        px = self.kit.px
        self._row.setContentsMargins(0, px(SPACE[2]), 0, px(SPACE[2]))
        self._row.setSpacing(px(SPACE[4]))
        color = tone_colors(self.kit.palette, self.item.tone)[2]
        self._icon.setPixmap(icon_pixmap(self.item.icon, color, px(LAYOUT["icon_md"])))
        self._icon.setFixedWidth(px(LAYOUT["icon_md"]))


class FeedList(Card):
    def __init__(self, kit: UiKit, parent: QWidget | None = None) -> None:
        super().__init__(kit, parent=parent)
        self._title = make_label("", "section")
        self._rows_host = QWidget()
        self._rows = QVBoxLayout(self._rows_host)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(0)
        self._empty = EmptyState(kit, "activity", "", "")
        self.body.addWidget(self._title)
        self.body.addWidget(self._rows_host)
        self.body.addWidget(self._empty)
        self._widgets: list[FeedRow] = []
        bind_kit(kit, language=self._retranslate)
        self._retranslate()

    def set_events(self, events: Sequence[FeedEvent], now: datetime) -> None:
        known = {id(row.item) for row in self._widgets}
        if known == {id(event) for event in events} and len(known) == len(self._widgets):
            self.refresh_time(now)
            return
        for row in self._widgets:
            self._rows.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._widgets = [FeedRow(self.kit, event) for event in events]
        for row in self._widgets:
            self._rows.addWidget(row)
        self._empty.setVisible(not events)
        self._rows_host.setVisible(bool(events))
        self.refresh_time(now)

    def refresh_time(self, now: datetime) -> None:
        for row in self._widgets:
            row.refresh_time(now)

    def _retranslate(self) -> None:
        self._title.setText(tr("overview.feed.title"))
        self._empty.set_texts(tr("overview.feed.empty.title"), tr("overview.feed.empty.text"))
