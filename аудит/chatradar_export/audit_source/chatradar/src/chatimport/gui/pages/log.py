"""The Log page: a live, filterable view of the service log with the full record below."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPersistentModelIndex, QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QMenu,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.format import format_count
from chatimport.gui.i18n import plural, tr
from chatimport.gui.icons import icon
from chatimport.gui.locales import log as _log_strings
from chatimport.gui.models.log_model import Column, LogFilterProxy, LogModel
from chatimport.gui.models.log_parser import Level
from chatimport.gui.models.log_source import LogSource
from chatimport.gui.pages.log_delegate import LogDelegate
from chatimport.gui.pages.log_widgets import DetailPane, FloatingHost, InlineSwitch
from chatimport.gui.pages.support import notify
from chatimport.gui.strings import current_language
from chatimport.gui.tokens import LAYOUT, SPACE
from chatimport.gui.widgets.base import bind_kit
from chatimport.gui.widgets.button import Button, IconButton
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.labels import ElidedLabel
from chatimport.gui.widgets.search_field import SearchField
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.gui.widgets.table import configure_table

if TYPE_CHECKING:
    from chatimport.gui.context import GuiContext
    from chatimport.gui.models.log_parser import LogRecord

_ = _log_strings
PAGE_PADDING: Final = SPACE[8]
ROW_HEIGHT: Final = 30
COLUMN_WIDTHS: Final = {Column.TIME: 138, Column.LEVEL: 106, Column.SOURCE: 152}
LEVEL_FILTERS: Final = (
    ("all", Level.DEBUG),
    ("info", Level.INFO),
    ("warning", Level.WARNING),
    ("error", Level.ERROR),
)
END_SLACK: Final = 2
FIT_MARGIN: Final = 6
RESIZE_DEBOUNCE_MS: Final = 80
SOURCE_MIN_WIDTH: Final = 130
DETAIL_MIN_HEIGHT: Final = 96
PATH_MIN_WIDTH: Final = 340
PATH_MAX_WIDTH: Final = 520
(LOADING, MISSING, EMPTY, NO_MATCHES, TABLE) = range(5)


class LogPage(QWidget):
    title_key = "nav.log"
    subtitle_key = "log.subtitle"

    def __init__(self, gui: GuiContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.gui = gui
        kit = gui.kit
        self._follow = True
        self._wrap = False
        self._programmatic = False
        self._end_pending = False
        self._row_heights_set = False
        self._loggers: set[str] = set()
        self._started = False
        self.source = LogSource(gui.service.paths.log_dir, self)
        self.model = LogModel(current_language())
        self.proxy = LogFilterProxy(self.model)

        self.search = SearchField(kit)
        self.search.setMinimumWidth(kit.px(160))
        self.levels = Segmented(kit, self._level_options(), "all", compact=True)
        self.copy_button = IconButton(kit, "copy", "")
        self.clear_button = IconButton(kit, "trash", "")
        self.open_button = IconButton(kit, "folder-open", "")
        top = QHBoxLayout()
        top.setSpacing(kit.px(SPACE[4]))
        top.addWidget(self.search, 1)
        top.addWidget(self.levels)

        self.sources = QComboBox()
        self.sources.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.follow_switch = InlineSwitch(kit, checked=True)
        self.wrap_switch = InlineSwitch(kit)
        self.traceback_switch = InlineSwitch(kit, checked=True)
        options = QHBoxLayout()
        options.setSpacing(kit.px(SPACE[4]))
        options.addWidget(self.sources)
        for switch in (self.follow_switch, self.wrap_switch, self.traceback_switch):
            options.addWidget(switch)
        options.addStretch(1)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        configure_table(self.table, kit)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setWordWrap(False)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setAccessibleName(tr("nav.log"))
        self.delegate = LogDelegate(kit)
        self.table.setItemDelegate(self.delegate)
        self.jump = Button(kit, "", variant="primary", size="sm", icon_name="arrow-down")
        self.table_host = FloatingHost(kit, self.table, self.jump)
        self.detail = DetailPane(kit)

        self.loading = EmptyState(kit, "log", "", "")
        self.missing_path = ElidedLabel("", "mono", mode=Qt.TextElideMode.ElideMiddle)
        self.missing = EmptyState(kit, "log", "", "", action=self.missing_path)
        self.empty = EmptyState(kit, "log", "", "")
        self.no_matches = EmptyState(kit, "search", "", "")
        self.stack = QStackedWidget()
        for widget in (self.loading, self.missing, self.empty, self.no_matches, self.table_host):
            self.stack.addWidget(widget)
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.detail)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)

        self.lines_chip = Chip(kit, "", "neutral", icon_name="log")
        self.warnings_chip = Chip(kit, "", "warning", icon_name="alert")
        self.errors_chip = Chip(kit, "", "danger", icon_name="x-circle")
        self.older_button = Button(kit, "", size="sm", icon_name="arrow-up")
        footer = QHBoxLayout()
        footer.setSpacing(kit.px(SPACE[3]))
        for chip in (self.lines_chip, self.warnings_chip, self.errors_chip):
            footer.addWidget(chip)
        footer.addStretch(1)
        for button in (self.copy_button, self.clear_button, self.open_button):
            footer.addWidget(button)
        footer.addWidget(self.older_button)

        self._column = QVBoxLayout(self)
        self._column.addLayout(top)
        self._column.addLayout(options)
        self._column.addWidget(self.splitter, 1)
        self._column.addLayout(footer)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._on_width_settled)
        self._connect()
        bind_kit(kit, zoom=self._restyle, language=self._retranslate)
        self._restyle()
        self._retranslate()
        self._sync_all()

    def _connect(self) -> None:
        self.search.query_changed.connect(self._on_query)
        self.levels.selected.connect(self._on_level)
        self.sources.currentIndexChanged.connect(self._on_source)
        self.follow_switch.toggled.connect(self._on_follow_toggled)
        self.wrap_switch.toggled.connect(self._on_wrap_toggled)
        self.traceback_switch.toggled.connect(self.proxy.set_show_tracebacks)
        self.copy_button.clicked.connect(self.copy_lines)
        self.clear_button.clicked.connect(self.clear_view)
        self.open_button.clicked.connect(self._show_open_menu)
        self.older_button.clicked.connect(self.source.load_older)
        self.jump.clicked.connect(self.jump_to_end)
        bar = self.table.verticalScrollBar()
        bar.valueChanged.connect(self._on_scrolled)
        bar.valueChanged.connect(self._fit_rows)
        self.table.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.table.selectionModel().currentRowChanged.connect(self._on_current)
        self.table.selectionModel().selectionChanged.connect(self._on_current)
        for signal in (
            self.proxy.rowsInserted,
            self.proxy.rowsRemoved,
            self.proxy.modelReset,
            self.proxy.layoutChanged,
        ):
            signal.connect(self._sync_all)
        self.model.rowsInserted.connect(self._on_rows_added)
        self.source.loaded.connect(self._on_loaded)
        self.source.appended.connect(self._on_appended)
        self.source.older.connect(self._on_older)
        self.source.exists_changed.connect(self._on_source_state)
        self.source.busy_changed.connect(self._on_source_state)
        self.source.rotated.connect(lambda: notify(self, "info", tr("log.toast.rotated")))
        self.source.failed.connect(lambda: notify(self, "danger", tr("log.toast.load_failed")))
        QShortcut(QKeySequence(Qt.Key.Key_Home), self.table, self.scroll_home)
        QShortcut(QKeySequence(Qt.Key.Key_End), self.table, self.jump_to_end)
        QShortcut(QKeySequence.StandardKey.Copy, self.table, self.copy_lines)

    def _on_section_resized(self, _section: int, _old: int, _new: int) -> None:
        self._resize_timer.start()

    def _on_source_state(self, _flag: bool) -> None:
        self._sync_all()

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # pyright: ignore[reportArgumentType]
        if not self._started:
            self._started = True
            self.source.start()
        self.source.set_following(True)

    def hideEvent(self, event: object) -> None:
        super().hideEvent(event)  # pyright: ignore[reportArgumentType]
        self.source.set_following(False)

    def _level_options(self) -> list[SegmentOption]:
        return [
            SegmentOption(name, tr(f"log.filter.{name}"), tooltip=tr(f"log.filter.{name}_tip"))
            for name, _level in LEVEL_FILTERS
        ]

    def _on_query(self, text: str) -> None:
        self.proxy.set_query(text)

    def _on_level(self, name: str) -> None:
        self.proxy.set_level(dict(LEVEL_FILTERS)[name])

    def _on_source(self, position: int) -> None:
        prefix = self.sources.itemData(position)
        self.proxy.set_logger_prefix(prefix if isinstance(prefix, str) else "")

    def _on_loaded(self, records: list[LogRecord], _has_older: bool) -> None:
        self.model.clear()
        self._loggers.clear()
        self.model.append(records)
        self._refresh_sources(records)
        self._schedule_end()

    def _on_appended(self, records: list[LogRecord]) -> None:
        self.model.append(records)
        self._refresh_sources(records)

    def _on_rows_added(self) -> None:
        if self._follow:
            self._schedule_end()
        else:
            self._fit_rows()

    def _on_older(self, records: list[LogRecord], exhausted: bool) -> None:
        anchor = self._top_anchor()
        inserted = self.model.prepend(records)
        self._refresh_sources(records)
        if self._follow:
            self._schedule_end()
        else:
            self._restore_anchor(anchor)
        if records and inserted < len(records):
            notify(
                self,
                "warning",
                tr(
                    "log.toast.older_capped",
                    limit=format_count(self.model.limit, current_language()),
                ),
            )
        elif inserted:
            notify(self, "success", plural(inserted, "log.toast.older"))
        elif exhausted:
            notify(self, "info", tr("log.toast.older_none"))
        self._sync_all()

    def _top_anchor(self) -> QPersistentModelIndex | None:
        row = self.table.rowAt(0)
        if row < 0:
            return None
        return QPersistentModelIndex(self.proxy.mapToSource(self.proxy.index(row, 0)))

    def _restore_anchor(self, anchor: QPersistentModelIndex | None) -> None:
        if anchor is None or not anchor.isValid():
            return
        index = self.proxy.mapFromSource(self.model.index(anchor.row(), 0))
        if index.isValid():
            self._programmatic = True
            self.table.scrollTo(index, QAbstractItemView.ScrollHint.PositionAtTop)
            self._programmatic = False

    def _refresh_sources(self, records: list[LogRecord]) -> None:
        fresh = {record.logger for record in records} - self._loggers
        if not fresh:
            return
        self._loggers |= fresh
        current = self.sources.currentData()
        self.sources.blockSignals(True)
        self.sources.clear()
        self.sources.addItem(tr("log.source.all"), "")
        for name in sorted(self._loggers):
            self.sources.addItem(name, name)
        self.sources.setCurrentIndex(max(self.sources.findData(current), 0))
        self.sources.blockSignals(False)

    def _on_current(self) -> None:
        selection = self.table.selectionModel()
        index = self.table.currentIndex()
        shown = index.isValid() and selection.hasSelection()
        self.detail.show_record(self.proxy.record_at(index.row()) if shown else None)

    def _schedule_end(self) -> None:
        if not self._end_pending:
            self._end_pending = True
            QTimer.singleShot(0, self._do_end)

    def _do_end(self) -> None:
        self._end_pending = False
        if self._follow:
            self._fit_rows()
            self._scroll_end()

    def _scroll_end(self) -> None:
        self._programmatic = True
        self.table.scrollToBottom()
        self._programmatic = False

    def _on_scrolled(self, value: int) -> None:
        if self._programmatic:
            return
        at_end = value >= self.table.verticalScrollBar().maximum() - END_SLACK
        if at_end != self._follow:
            self._set_follow(at_end)

    def _on_follow_toggled(self, follow: bool) -> None:
        self._follow = follow
        if follow:
            self._schedule_end()
        self._sync_jump()

    def _set_follow(self, follow: bool) -> None:
        self._follow = follow
        self.follow_switch.switch.blockSignals(True)
        self.follow_switch.set_checked(follow)
        self.follow_switch.switch.blockSignals(False)
        self._sync_jump()

    def jump_to_end(self) -> None:
        self._set_follow(True)
        self._schedule_end()

    def scroll_home(self) -> None:
        self._set_follow(False)
        self._programmatic = True
        self.table.scrollToTop()
        self._programmatic = False

    def _on_wrap_toggled(self, wrap: bool) -> None:
        self._wrap = wrap
        self.delegate.wrap = wrap
        self.detail.set_wrap(wrap)
        self._on_width_settled()

    def _on_width_settled(self) -> None:
        self.delegate.message_width = self.table.columnWidth(Column.MESSAGE)
        self._reset_row_heights()
        self._fit_rows()
        if self._follow:
            self._schedule_end()

    def _reset_row_heights(self) -> None:
        if not self._row_heights_set:
            return
        self._row_heights_set = False
        height = self.table.verticalHeader().defaultSectionSize()
        for row in range(self.proxy.rowCount()):
            self.table.setRowHeight(row, height)

    def _fit_rows(self) -> None:
        if not self._wrap:
            return
        count = self.proxy.rowCount()
        if count == 0:
            return
        first = max(self.table.rowAt(0), 0)
        last = self.table.rowAt(self.table.viewport().height() - 1)
        last = count - 1 if last < 0 else last
        minimum = self.table.verticalHeader().defaultSectionSize()
        font = self.table.font()
        for row in range(max(first - FIT_MARGIN, 0), min(last + FIT_MARGIN, count - 1) + 1):
            height = self.delegate.row_height(self.proxy.record_at(row), font, minimum)
            if self.table.rowHeight(row) != height:
                self.table.setRowHeight(row, height)
                self._row_heights_set = True

    def copy_lines(self) -> None:
        rows = sorted(index.row() for index in self.table.selectionModel().selectedRows())
        if not rows:
            rows = list(range(self.proxy.rowCount()))
        if not rows:
            return
        text = "\n".join(self.proxy.record_at(row).as_text() for row in rows)
        QGuiApplication.clipboard().setText(text)
        notify(self, "success", plural(len(rows), "log.toast.copied"))

    def clear_view(self) -> None:
        self.source.forget_older()
        self.model.clear()
        self.detail.show_record(None)
        self._sync_all()
        notify(self, "info", tr("log.toast.cleared"))

    def _show_open_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction(
            icon("file", self.gui.kit.palette.fg_secondary, self.gui.kit.px(LAYOUT["icon_md"])),
            tr("log.open_file"),
            self.open_file,
        )
        menu.addAction(
            icon(
                "folder-open", self.gui.kit.palette.fg_secondary, self.gui.kit.px(LAYOUT["icon_md"])
            ),
            tr("log.open_folder"),
            self.open_folder,
        )
        menu.exec(self.open_button.mapToGlobal(QPoint(0, self.open_button.height())))

    def open_file(self) -> None:
        self._open(self.source.tail.path)

    def open_folder(self) -> None:
        self._open(self.source.tail.path.parent)

    def _open(self, path: object) -> None:
        target = QUrl.fromLocalFile(str(path))
        if not QDesktopServices.openUrl(target):
            notify(self, "warning", tr("log.toast.open_failed"))

    def _sync_all(self) -> None:
        self._sync_stack()
        self._sync_summary()
        self._sync_jump()
        self.older_button.setEnabled(self.source.has_older and not self.source.busy)
        self.older_button.setText(tr("log.older_busy" if self.source.busy else "log.older"))

    def _sync_stack(self) -> None:
        if not self.source.ready:
            index = LOADING
        elif self.model.rowCount() == 0:
            index = EMPTY if self.source.exists else MISSING
        elif self.proxy.rowCount() == 0:
            index = NO_MATCHES
        else:
            index = TABLE
        self.stack.setCurrentIndex(index)
        self.detail.setVisible(index == TABLE)

    def _sync_summary(self) -> None:
        language = current_language()
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        if shown != total:
            text = tr(
                "log.summary.shown",
                shown=format_count(shown, language),
                total=format_count(total, language),
            )
        else:
            text = plural(total, "log.summary.lines")
        self.lines_chip.set_text(text)
        warnings, errors = self.model.warnings, self.model.errors
        self.warnings_chip.set_text(plural(warnings, "log.summary.warnings"))
        self.warnings_chip.set_tone("warning" if warnings else "muted")
        self.errors_chip.set_text(plural(errors, "log.summary.errors"))
        self.errors_chip.set_tone("danger" if errors else "muted")

    def _sync_jump(self) -> None:
        show = not self._follow and self.proxy.rowCount() > 0
        self.jump.setVisible(show)
        if show:
            self.table_host.place()

    def _retranslate(self) -> None:
        self.model.set_language(current_language())
        self.levels.set_options(self._level_options())
        self.levels.set_label("")
        self.levels.setAccessibleName(tr("log.filter.label"))
        current = self.sources.currentData()
        self.sources.blockSignals(True)
        if self.sources.count():
            self.sources.setItemText(0, tr("log.source.all"))
        self.sources.setCurrentIndex(max(self.sources.findData(current), 0))
        self.sources.blockSignals(False)
        self.sources.setAccessibleName(tr("log.source.label"))
        self.follow_switch.set_text(tr("log.follow"), tr("log.follow_tip"))
        self.wrap_switch.set_text(tr("log.wrap"), tr("log.wrap_tip"))
        self.traceback_switch.set_text(tr("log.tracebacks"), tr("log.tracebacks_tip"))
        self.jump.setText(tr("log.jump"))
        for button, key in (
            (self.copy_button, "log.copy"),
            (self.clear_button, "log.clear"),
            (self.open_button, "log.open_menu"),
        ):
            button.set_tooltip(tr(key))
        self.older_button.setToolTip(tr("log.older_tip"))
        self.loading.set_texts(tr("log.empty.loading"))
        self.missing.set_texts(tr("log.empty.missing.title"), tr("log.empty.missing.text"))
        self.missing_path.setText(str(self.source.tail.path))
        self.empty.set_texts(tr("log.empty.empty.title"), tr("log.empty.empty.text"))
        self.no_matches.set_texts(tr("empty.search.title"), tr("empty.search.text"))
        self._sync_all()
        self.table.viewport().update()

    def _restyle(self) -> None:
        kit = self.gui.kit
        pad = kit.px(PAGE_PADDING)
        self._column.setContentsMargins(pad, kit.px(SPACE[6]), pad, kit.px(SPACE[5]))
        self._column.setSpacing(kit.px(SPACE[4]))
        self.table.verticalHeader().setDefaultSectionSize(kit.px(ROW_HEIGHT))
        self.sources.setMinimumWidth(kit.px(SOURCE_MIN_WIDTH))
        self.detail.setMinimumHeight(kit.px(DETAIL_MIN_HEIGHT))
        self.missing_path.setMinimumWidth(kit.px(PATH_MIN_WIDTH))
        self.missing_path.setMaximumWidth(kit.px(PATH_MAX_WIDTH))
        self._row_heights_set = True
        header = self.table.horizontalHeader()
        for column, width in COLUMN_WIDTHS.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
            self.table.setColumnWidth(column, kit.px(width))
        self._resize_timer.start()
