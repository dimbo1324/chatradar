"""The Storage card: archive, media and free disk, and the size of every chat."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QHeaderView, QTableView

from chatimport.config import GIB
from chatimport.gui.format import format_bytes, format_count
from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.models.data_models import UsageColumn, UsageModel
from chatimport.gui.pages.data_common import (
    ShareBarDelegate,
    fit_table,
    prepare_table,
)
from chatimport.gui.pages.data_section import Section
from chatimport.gui.strings import current_language
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.chip import Dot
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.labels import make_label
from chatimport.gui.widgets.stat_card import StatCard
from chatimport.gui.widgets.table import configure_table

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from chatimport.gui.pages.data_common import DataEnv
    from chatimport.gui.strings import Language
    from chatimport.usage import ArchiveUsage

_ = _data_strings
LOW_DISK_WARNING_FACTOR: Final = 1.5
COLUMNS: Final = 4
SHARE_WIDTH: Final = 150
NUMBER_WIDTHS: Final = {UsageColumn.SIZE: 80, UsageColumn.MESSAGES: 104, UsageColumn.PARTS: 64}


def free_disk_tone(free_bytes: int | None, low_bytes: int) -> Tone:
    if free_bytes is None or low_bytes <= 0:
        return "neutral"
    if free_bytes < low_bytes:
        return "danger"
    return "warning" if free_bytes < low_bytes * LOW_DISK_WARNING_FACTOR else "success"


class StorageCard(Section):
    def __init__(self, env: DataEnv, parent: QWidget | None = None) -> None:
        self.calculate = Button(env.gui.kit, "", icon_name="refresh")
        trailing = QHBoxLayout()
        trailing.addWidget(self.calculate)
        super().__init__(env, "storage", "disk", trailing=trailing, parent=parent)
        kit = self.kit
        self._busy = False
        self.calculate.clicked.connect(env.request_usage)
        self.cards = {
            "archive": StatCard(kit, "", icon_name="package"),
            "media": StatCard(kit, "", icon_name="download"),
            "free": StatCard(kit, "", icon_name="disk"),
            "chats": StatCard(kit, "", icon_name="chats"),
        }
        self._grid = QGridLayout()
        for position, card in enumerate(self.cards.values()):
            self._grid.addWidget(card, 0, position)
            self._grid.setColumnStretch(position, 1)
        self.model = UsageModel()
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_table(self.table, kit)
        prepare_table(self.table)
        self.table.setItemDelegate(ShareBarDelegate(kit))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(UsageColumn.CHAT, QHeaderView.ResizeMode.Stretch)
        for number in (UsageColumn.SIZE, UsageColumn.MESSAGES, UsageColumn.PARTS):
            header.setSectionResizeMode(number, QHeaderView.ResizeMode.Fixed)
        self.empty = EmptyState(kit, "chats", "", "")
        self._legend_messages = make_label("", "caption")
        self._legend_media = make_label("", "caption")
        self._legend = QHBoxLayout()
        self._legend.addWidget(Dot(kit, "accent"))
        self._legend.addWidget(self._legend_messages)
        self._legend.addWidget(Dot(kit, "live"))
        self._legend.addWidget(self._legend_media)
        self._legend.addStretch(1)
        self.content.addLayout(self._grid)
        self.content.addWidget(self.table)
        self.content.addWidget(self.empty)
        self.content.addLayout(self._legend)
        env.usage_changed.connect(self._render)
        bind_kit(kit, zoom=self._apply_sizes)
        self._apply_sizes()
        self.retranslate()

    def set_busy(self, busy: bool) -> None:
        super().set_busy(busy)
        self._busy = busy
        self.calculate.setEnabled(not busy)
        self.calculate.setText(tr("data.storage.calculating" if busy else "data.storage.calculate"))

    def retranslate(self) -> None:
        self.set_busy(self._busy)
        self.model.retranslate()
        self._legend_messages.setText(tr("data.storage.legend.messages"))
        self._legend_media.setText(tr("data.storage.legend.media"))
        self.empty.set_texts(tr("data.storage.empty"), tr("data.storage.empty_text"))
        self._render()

    def _apply_sizes(self) -> None:
        px = self.kit.px
        self._grid.setSpacing(px(SPACE[4]))
        self._legend.setSpacing(px(SPACE[3]))
        header = self.table.horizontalHeader()
        header.resizeSection(UsageColumn.SHARE, px(SHARE_WIDTH))
        for number in (UsageColumn.SIZE, UsageColumn.MESSAGES, UsageColumn.PARTS):
            header.resizeSection(number, px(NUMBER_WIDTHS[number]))
        header.setSectionResizeMode(UsageColumn.SHARE, QHeaderView.ResizeMode.Fixed)
        self.table.setAlternatingRowColors(False)
        fit_table(self.table, self.kit, self.model.rowCount())

    def _show_table(self, shown: bool) -> None:
        self.table.setVisible(shown)
        self.empty.setVisible(not shown)

    def _render(self) -> None:
        usage = self.env.usage
        language = current_language()
        cards = self.cards
        cards["archive"].set_label(tr("data.storage.stat.archive"))
        cards["media"].set_label(tr("data.storage.stat.media"))
        cards["media"].set_hint(tr("data.storage.stat.media_hint"))
        cards["free"].set_label(tr("data.storage.stat.free"))
        cards["chats"].set_label(tr("data.storage.stat.chats"))
        if usage is None:
            for card in cards.values():
                card.set_value("-")
            cards["archive"].set_hint("")
            cards["free"].set_hint("")
            cards["chats"].set_hint("")
            self.model.set_usage(())
            self._show_table(False)
            return
        self._render_totals(usage, language)
        self.model.set_usage(usage.chats)
        self._show_table(bool(usage.chats))
        fit_table(self.table, self.kit, self.model.rowCount())

    def _render_totals(self, usage: ArchiveUsage, language: Language) -> None:
        cards = self.cards
        cards["archive"].set_value(format_bytes(usage.total_bytes, language))
        cards["archive"].set_hint(
            tr(
                "data.storage.stat.archive_hint",
                jsonl=format_bytes(usage.jsonl_total, language),
                service=format_bytes(usage.service_files_total, language),
            )
        )
        cards["media"].set_value(format_bytes(usage.media_total, language))
        low_bytes = self.env.gui.service.config.disk.low_watermark_gb * GIB
        if usage.free_bytes is None:
            cards["free"].set_value(tr("data.storage.stat.free_unknown"))
            cards["free"].set_hint("")
        else:
            cards["free"].set_value(format_bytes(usage.free_bytes, language))
            cards["free"].set_hint(
                tr("data.storage.stat.free_hint", limit=format_bytes(low_bytes, language))
            )
        cards["free"].set_tone(free_disk_tone(usage.free_bytes, low_bytes))
        cards["chats"].set_value(format_count(len(usage.chats), language))
        records = sum(chat.records or 0 for chat in usage.chats)
        cards["chats"].set_hint(plural(records, "data.storage.stat.chats_hint"))
