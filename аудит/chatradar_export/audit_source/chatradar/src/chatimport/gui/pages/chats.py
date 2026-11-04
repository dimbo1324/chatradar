"""The Chats page: every library chat with its live state, download progress and age."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QPoint, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.format import Freshness, format_count, humanize_age
from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import chats as _chat_strings
from chatimport.gui.models.chats_model import (
    ChatsFilterProxy,
    ChatsTableModel,
    Column,
    FilterMode,
)
from chatimport.gui.models.snapshot import ChatRow, parse_snapshot
from chatimport.gui.models.ticker import shared_ticker
from chatimport.gui.pages.chats_actions import ChatActions
from chatimport.gui.pages.chats_delegate import ChatsDelegate
from chatimport.gui.pages.library_dialog import LibraryDialog
from chatimport.gui.pages.support import clear_layout
from chatimport.gui.strings import current_language
from chatimport.gui.theme import freshness_color
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.labels import make_label
from chatimport.gui.widgets.search_field import SearchField
from chatimport.gui.widgets.table import configure_table

if TYPE_CHECKING:
    from typing import Any

    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.snapshot import SnapshotView

_ = _chat_strings
ROW_HEIGHT: Final = 48
COLUMN_WIDTHS: Final = {
    Column.STATUS: 104,
    Column.HISTORY: 224,
    Column.LAST_MESSAGE: 156,
    Column.MESSAGES: 84,
    Column.SPAN: 136,
}
CHAT_MIN_WIDTH: Final = 190
FILTER_ORDER: Final = tuple(FilterMode)
PAGE_PADDING: Final = SPACE[8]


class ChatsPage(QWidget):
    title_key = "nav.chats"
    subtitle_key = "chats.subtitle"

    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        kit = gui.kit
        self._ticker = shared_ticker()
        self._animating = False
        self._snapshot = parse_snapshot(None)
        settings = gui.settings
        self.model = ChatsTableModel(
            self._ticker.now,
            lambda chat_id: settings.settings.thresholds_for(chat_id),
            absolute_time=settings.settings.chats_absolute_time,
        )
        self.proxy = ChatsFilterProxy(self.model, self._ticker.now)
        self.chat_actions = ChatActions(gui, self)

        self.search = SearchField(kit)
        self.search.setMinimumWidth(kit.px(220))
        self.search.setMaximumWidth(kit.px(340))
        self.filter = QComboBox()
        self.filter.setAccessibleName(tr("chats.filter.label"))
        self.count = QLabel()
        set_role(self.count, "muted")
        self.library = Button(kit, "", icon_name="sliders")
        self.library.clicked.connect(self.open_library)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(kit.px(SPACE[4]))
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.filter)
        toolbar.addStretch(1)
        toolbar.addWidget(self.count)
        toolbar.addWidget(self.library)

        self.selection_label = QLabel()
        set_role(self.selection_label, "muted")
        self.pause_button = Button(kit, "", size="sm", icon_name="pause")
        self.resume_button = Button(kit, "", size="sm", icon_name="play")
        self.recheck_button = Button(kit, "", size="sm", icon_name="refresh")
        self.deeper_button = Button(kit, "", size="sm", icon_name="download")
        self.more_button = IconButton(kit, "chevron-down", "", size="sm")
        self.more_button.clicked.connect(self._show_more_menu)
        self.pause_button.clicked.connect(lambda: self.chat_actions.pause(self.selected_rows()))
        self.resume_button.clicked.connect(lambda: self.chat_actions.resume(self.selected_rows()))
        self.recheck_button.clicked.connect(lambda: self.chat_actions.recheck(self.selected_rows()))
        self.deeper_button.clicked.connect(lambda: self.chat_actions.deeper(self.selected_rows()))
        selection_bar = QHBoxLayout()
        selection_bar.setSpacing(kit.px(SPACE[3]))
        selection_bar.addWidget(self.selection_label)
        selection_bar.addStretch(1)
        for button in (
            self.pause_button,
            self.resume_button,
            self.recheck_button,
            self.deeper_button,
            self.more_button,
        ):
            selection_bar.addWidget(button)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        configure_table(self.table, kit)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setWordWrap(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.delegate = ChatsDelegate(kit, self.model)
        self.table.setItemDelegate(self.delegate)
        self.table.sortByColumn(Column.LAST_MESSAGE, Qt.SortOrder.AscendingOrder)
        self.table.clicked.connect(self._on_clicked)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        self.table.setAccessibleName(tr("nav.chats"))
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(Column.CHAT, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(kit.px(64))

        self.library_action = Button(kit, "", variant="primary", icon_name="sliders")
        self.library_action.clicked.connect(self.open_library)
        self.empty = EmptyState(kit, "chats", "", "", action=self.library_action)
        self.no_matches = EmptyState(kit, "search", "", "")
        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.no_matches)

        self.legend = QHBoxLayout()
        self.legend.setSpacing(kit.px(SPACE[5]))
        self._legend_host = QWidget()
        self._legend_host.setLayout(self.legend)
        self._legend_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._column = QVBoxLayout(self)
        self._column.addLayout(toolbar)
        self._column.addLayout(selection_bar)
        self._column.addWidget(self.stack, 1)
        self._column.addWidget(self._legend_host)

        self.search.query_changed.connect(self._on_query)
        self.filter.currentIndexChanged.connect(self._on_filter)
        self.table.selectionModel().selectionChanged.connect(self._sync_selection)
        self.proxy.rowsInserted.connect(self._sync_stack)
        self.proxy.rowsRemoved.connect(self._sync_stack)
        self.proxy.layoutChanged.connect(self._sync_stack)
        self.proxy.modelReset.connect(self._sync_stack)
        self._ticker.second.connect(self._on_second)
        self._ticker.frame.connect(self._on_frame)
        gui.bridge.snapshot.connect(self.set_snapshot)
        bind_kit(kit, theme=self._rebuild_legend, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()
        last = gui.bridge.last_snapshot
        if last is not None:
            self.set_snapshot(last)
        self._sync_stack()

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def set_snapshot(self, raw: dict[str, Any]) -> None:
        view = parse_snapshot(raw)
        self._snapshot = view
        self.model.set_rows(view.chats)
        self.proxy.refresh_time()
        self._update_animation()
        self._sync_stack()
        self._sync_count()

    def selected_rows(self) -> list[ChatRow]:
        indexes = self.table.selectionModel().selectedRows()
        return [self.model.row_at(self.proxy.mapToSource(i).row()) for i in indexes]

    @property
    def snapshot(self) -> SnapshotView:
        return self._snapshot

    def open_library(self) -> None:
        dialog = LibraryDialog(self.gui, self.window())
        dialog.set_errors(self._snapshot.errors)
        dialog.exec()

    def _on_clicked(self, index: QModelIndex) -> None:
        if index.column() != Column.LAST_MESSAGE:
            return
        absolute = not self.model.absolute_time
        self.model.set_absolute_time(absolute)
        self.gui.settings.update(chats_absolute_time=absolute)

    def _on_context_menu(self, position: QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        selection = self.table.selectionModel()
        if not selection.isRowSelected(index.row(), QModelIndex()):
            selection.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        menu = self.chat_actions.build_menu(self.selected_rows(), self.table)
        menu.exec(self.table.viewport().mapToGlobal(position))

    def _show_more_menu(self) -> None:
        menu = self.chat_actions.build_menu(self.selected_rows(), self)
        menu.exec(self.more_button.mapToGlobal(QPoint(0, self.more_button.height())))

    def _on_query(self, text: str) -> None:
        self.proxy.set_query(text)
        self._sync_stack()
        self._sync_count()

    def _on_filter(self, position: int) -> None:
        mode = self.filter.itemData(position)
        if isinstance(mode, str):
            self.proxy.set_mode(FilterMode(mode))
            self._sync_stack()
            self._sync_count()

    def _on_second(self) -> None:
        self.model.tick()
        self.proxy.refresh_time()
        self._sync_count()

    def _on_frame(self, phase: float) -> None:
        self.delegate.phase = phase
        self.table.viewport().update()

    def _update_animation(self) -> None:
        running = any(row.backfill.state.value == "running" for row in self._snapshot.chats)
        if running and not self._animating:
            self._ticker.acquire_animation()
        elif not running and self._animating:
            self._ticker.release_animation()
        self._animating = running

    def _sync_selection(self) -> None:
        rows = self.selected_rows()
        have = bool(rows)
        if have:
            self.selection_label.setText(plural(len(rows), "chats.selection.count"))
        else:
            self.selection_label.setText(tr("chats.selection.none"))
        any_paused = any(row.is_paused for row in rows)
        self.pause_button.setEnabled(have and not all(row.is_paused for row in rows))
        self.resume_button.setEnabled(have and any_paused)
        self.recheck_button.setEnabled(have)
        self.deeper_button.setEnabled(have)
        self.more_button.setEnabled(have)

    def _sync_stack(self) -> None:
        if self.model.rowCount() == 0:
            self.stack.setCurrentWidget(self.empty)
        elif self.proxy.rowCount() == 0:
            self.stack.setCurrentWidget(self.no_matches)
        else:
            self.stack.setCurrentWidget(self.table)

    def _sync_count(self) -> None:
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        language = current_language()
        text = plural(total, "count.chats")
        if shown != total:
            text = f"{format_count(shown, language)} / {text}"
        self.count.setText(text)

    def _retranslate(self) -> None:
        current = self.proxy.mode.value
        self.filter.blockSignals(True)
        self.filter.clear()
        for mode in FILTER_ORDER:
            self.filter.addItem(tr(f"chats.filter.{mode.value}"), mode.value)
        self.filter.setCurrentIndex(self.filter.findData(current))
        self.filter.blockSignals(False)
        self.filter.setAccessibleName(tr("chats.filter.label"))
        self.library.setText(tr("chats.library"))
        self.library.setToolTip(tr("chats.library_tip"))
        self.library_action.setText(tr("chats.empty.action"))
        self.pause_button.setText(tr("chats.act.pause"))
        self.resume_button.setText(tr("chats.act.resume"))
        self.recheck_button.setText(tr("chats.act.recheck"))
        self.deeper_button.setText(tr("chats.act.deeper"))
        self.more_button.set_tooltip(tr("chats.act.more"))
        self.empty.set_texts(tr("chats.empty.title"), tr("chats.empty.text"))
        self.no_matches.set_texts(tr("empty.search.title"), tr("empty.search.text"))
        self.model.retranslate()
        self._sync_selection()
        self._sync_count()
        self._rebuild_legend()
        self.table.viewport().update()

    def _restyle(self) -> None:
        kit = self.gui.kit
        pad = kit.px(PAGE_PADDING)
        self._column.setContentsMargins(pad, kit.px(SPACE[6]), pad, kit.px(SPACE[5]))
        self._column.setSpacing(kit.px(SPACE[4]))
        self.table.verticalHeader().setDefaultSectionSize(kit.px(ROW_HEIGHT))
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(kit.px(CHAT_MIN_WIDTH))
        for column, width in COLUMN_WIDTHS.items():
            self.table.setColumnWidth(column, kit.px(width))
        self.table.horizontalHeader().setSectionResizeMode(
            Column.CHAT, QHeaderView.ResizeMode.Stretch
        )

    def _rebuild_legend(self) -> None:
        clear_layout(self.legend)
        palette = self.gui.theme.palette
        thresholds = self.gui.settings.settings.freshness
        language = current_language()
        self.legend.addWidget(make_label(tr("chats.legend.age"), "caption"))
        steps = (
            (Freshness.FRESH, f"< {humanize_age(thresholds.fresh_below, language)}"),
            (Freshness.RECENT, f"< {humanize_age(thresholds.recent_below, language)}"),
            (Freshness.STALE, f"< {humanize_age(thresholds.stale_below, language)}"),
            (Freshness.DORMANT, tr("chats.legend.older")),
        )
        for level, bound in steps:
            label = make_label(f"● {tr(f'freshness.{level.value}')} {bound}", "caption")
            label.setStyleSheet(f"color: {freshness_color(palette, level)};")
            self.legend.addWidget(label)
        self.legend.addStretch(1)
