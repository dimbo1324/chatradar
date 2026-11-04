"""The Search page: type-ahead substring search over every stored message.

The index lives behind `SearchBackend` and is touched only by `SearchWorker`'s thread. Each
typed query gets a sequence number; an answer that arrives for an older number is dropped, so
the list always belongs to the latest text. The window never waits for the index.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QModelIndex, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chatimport.gui.format import format_count
from chatimport.gui.i18n import plural, tr
from chatimport.gui.locales import search as _search_strings
from chatimport.gui.models.search_model import SearchResultsModel
from chatimport.gui.models.search_spans import fold_needle
from chatimport.gui.pages import search_actions as actions
from chatimport.gui.pages.search_context import ContextController, ContextPanel
from chatimport.gui.pages.search_delegate import SearchDelegate, utc_now
from chatimport.gui.pages.search_filters import ChatFilter, StatusStrip
from chatimport.gui.pages.search_parts import (
    QueryField,
    ResultsView,
    Skeleton,
    notice_keys,
)
from chatimport.gui.pages.search_worker import BackendFactory, SearchWorker, default_backend_factory
from chatimport.gui.pages.support import MainThreadRunner
from chatimport.gui.strings import current_language
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import bind_kit, set_role
from chatimport.gui.widgets.button import IconButton
from chatimport.gui.widgets.empty_state import EmptyState
from chatimport.gui.widgets.progress import BusyStripe
from chatimport.gui.widgets.segmented import Segmented, SegmentOption
from chatimport.search_types import DEFAULT_PAGE_SIZE, MIN_INDEXED_LENGTH, IndexState, SearchQuery

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Future

    from PySide6.QtGui import QKeyEvent

    from chatimport.gui.context import GuiContext
    from chatimport.search_types import (
        ChatChoice,
        IndexStatus,
        SearchBackend,
        SearchHit,
    )
    from chatimport.search_types import SearchPage as Page

_ = _search_strings
log = logging.getLogger(__name__)

DEBOUNCE_MS: Final = 120
POLL_MS: Final = 3000
PAGE_PADDING: Final = SPACE[8]
PERIODS: Final = ("any", "today", "week", "month", "year")
PERIOD_DAYS: Final = {"week": 7, "month": 30, "year": 365}
NOTICE, LOADING, RESULTS = range(3)

type StatusReply = tuple[IndexStatus, tuple[ChatChoice, ...]] | None


def _read_status(backend: SearchBackend | None) -> StatusReply:
    return None if backend is None else (backend.status(), backend.chats())


class SearchPage(QWidget):
    title_key = "nav.search"
    subtitle_key = "find.subtitle"

    def __init__(
        self,
        gui: GuiContext,
        parent: QWidget | None = None,
        *,
        backend_factory: BackendFactory = default_backend_factory,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        super().__init__(parent)
        self.gui = gui
        self._clock = clock
        kit = gui.kit
        self._worker = SearchWorker(lambda: gui.current.root, backend_factory)
        self._runner = MainThreadRunner(self)
        self._seq = 0
        self._query: SearchQuery | None = None
        self._state: IndexState | None = None
        self._no_backend = False
        self._status: IndexStatus | None = None
        self._chats: tuple[ChatChoice, ...] = ()
        self._period = "any"
        self._built = False
        self._advance_after_fetch = False
        self._last_snapshot_value: object = None

        self.model = SearchResultsModel()
        self.delegate = SearchDelegate(kit, clock)
        self.field = QueryField(kit)
        self.field.setMinimumWidth(kit.px(220))
        self.busy = BusyStripe(kit)
        self.chat_filter = ChatFilter(kit, self)
        self.period = Segmented(kit, self._period_options(), "any", compact=True)
        top = QHBoxLayout()
        top.addWidget(self.field, 1)
        top.addWidget(self.chat_filter.button)
        top.addWidget(self.period)

        self.count = QLabel()
        set_role(self.count, "title")
        self.hint = QLabel()
        set_role(self.hint, "muted")
        self.hint.hide()
        self.previous_button = IconButton(kit, "arrow-up", "", size="sm")
        self.next_button = IconButton(kit, "arrow-down", "", size="sm")
        self.strip = StatusStrip(kit)
        info = QHBoxLayout()
        info.addWidget(self.count)
        info.addWidget(self.previous_button)
        info.addWidget(self.next_button)
        info.addWidget(self.hint, 1)
        info.addStretch(1)
        info.addWidget(self.strip)

        self.notice = EmptyState(kit, "search", "", "")
        self.skeleton = Skeleton(kit)
        self.results = ResultsView()
        self.results.setModel(self.model)
        self.results.use_delegate(self.delegate)
        self.results.setAccessibleName(tr("nav.search"))
        self.stack = QStackedWidget()
        for widget in (self.notice, self.skeleton, self.results):
            self.stack.addWidget(widget)
        self.context = ContextPanel(kit)
        self.context.hide()
        self.ctx = ContextController(self.context, self._worker, self._runner, self._needle)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.stack)
        self.splitter.addWidget(self.context)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)

        self._column = QVBoxLayout(self)
        self._column.addLayout(top)
        self._column.addWidget(self.busy)
        self._column.addLayout(info)
        self._column.addWidget(self.splitter, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(DEBOUNCE_MS)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._connect()
        bind_kit(kit, zoom=self._restyle, language=self._retranslate)
        kit.theme.changed.connect(self.results.viewport().update)
        self.destroyed.connect(self._worker.close)
        self._restyle()
        self._retranslate()
        self._built = True

    def _connect(self) -> None:
        self.field.textChanged.connect(self._on_text)
        self.field.next_requested.connect(self.select_next)
        self.field.previous_requested.connect(self.select_previous)
        self._debounce.timeout.connect(self.run_query)
        self._poll.timeout.connect(self.refresh_status)
        self.period.selected.connect(self._on_period)
        self.chat_filter.changed.connect(self._requery)
        self.next_button.clicked.connect(self.select_next)
        self.previous_button.clicked.connect(self.select_previous)
        self.model.more_requested.connect(self._fetch_more)
        self.results.activated.connect(self._on_activated)
        self.results.doubleClicked.connect(self._on_activated)
        self.results.selectionModel().currentChanged.connect(self._on_current)
        self.context.close_requested.connect(self.close_context)
        self.context.open_requested.connect(self.open_in_telegram)
        self.context.copy_link_requested.connect(self.copy_link)
        self.context.copy_text_requested.connect(self.copy_text)
        self.gui.bridge.snapshot.connect(self._on_snapshot)
        QShortcut(QKeySequence.StandardKey.Copy, self.results, self.copy_text)

    def _needle(self) -> str:
        return self.model.needle

    def focus_search(self) -> None:
        self.field.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.field.selectAll()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape and self.ctx.is_open:
            self.close_context()
            event.accept()
            return
        super().keyPressEvent(event)

    def showEvent(self, event: object) -> None:
        super().showEvent(event)  # pyright: ignore[reportArgumentType]
        self.refresh_status()

    def hideEvent(self, event: object) -> None:
        super().hideEvent(event)  # pyright: ignore[reportArgumentType]
        self._poll.stop()

    @property
    def state(self) -> IndexState | None:
        return self._state

    @property
    def since(self) -> datetime | None:
        now = self._clock()
        if self._period == "today":
            local = now.astimezone()
            return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
        days = PERIOD_DAYS.get(self._period)
        return now - timedelta(days=days) if days is not None else None

    def _period_options(self) -> list[SegmentOption]:
        return [SegmentOption(name, tr(f"find.period.{name}")) for name in PERIODS]

    def _on_text(self, text: str) -> None:
        if not fold_needle(text):
            self._debounce.stop()
            self.run_query()
            return
        self._debounce.start()

    def _on_period(self, name: str) -> None:
        self._period = name
        self._requery()

    def _requery(self) -> None:
        if fold_needle(self.field.text()):
            self._debounce.start()

    def _blocked(self) -> bool:
        return self._no_backend or self._state in (IndexState.DISABLED, IndexState.MISSING)

    def run_query(self) -> None:
        """Start a search for the text now in the box (the debounce timer calls this)."""
        self._debounce.stop()
        self._seq += 1
        self._advance_after_fetch = False
        text = self.field.text()
        needle = fold_needle(text)
        if not needle:
            self._query = None
            self.model.clear()
            self._set_busy(False)
            self._show_notice()
            self._sync_count()
            return
        query = SearchQuery(
            text=text,
            chat_ids=self.chat_filter.selected or None,
            since=self.since,
            limit=DEFAULT_PAGE_SIZE,
        )
        self._query = query
        self.delegate.needle = text
        if self._blocked():
            self.model.clear()
            self._set_busy(False)
            self._show_notice()
            self._sync_count()
            return
        self._set_busy(True)
        if self.model.loaded == 0:
            self.stack.setCurrentIndex(LOADING)
        seq = self._seq
        future = self._worker.run(
            lambda backend: None if backend is None else backend.search(query)
        )
        self._runner.watch(future, lambda done: self._on_first_page(seq, done))

    def _on_first_page(self, seq: int, done: Future[Page | None]) -> None:
        if seq != self._seq:
            return
        self._set_busy(False)
        try:
            page = done.result()
        except Exception as error:
            log.warning("search failed: %s", type(error).__name__)
            self.model.clear()
            self._show_notice(error=True)
            self._sync_count()
            return
        if page is None:
            self._no_backend = True
            self.model.clear()
            self._show_notice()
            self._sync_count()
            self.refresh_status()
            return
        self._no_backend = False
        self.delegate.needle = page.query.text
        self.model.reset(page)
        self.results.doItemsLayout()
        if page.total == 0:
            self._show_notice()
        else:
            self.stack.setCurrentIndex(RESULTS)
        self._sync_count()

    def _fail_more(self) -> None:
        self._advance_after_fetch = False
        self.model.fetch_failed()

    def _fetch_more(self, offset: int) -> None:
        query = self._query
        if query is None:
            self._fail_more()
            return
        more = replace(query, offset=offset)
        seq = self._seq
        future = self._worker.run(lambda backend: None if backend is None else backend.search(more))
        self._runner.watch(future, lambda done: self._on_more_page(seq, done))

    def _on_more_page(self, seq: int, done: Future[Page | None]) -> None:
        if seq != self._seq:
            return
        try:
            page = done.result()
        except Exception as error:
            log.warning("loading more results failed: %s", type(error).__name__)
            self._fail_more()
            return
        before = self.model.loaded
        if page is None or not self.model.append(page):
            self._fail_more()
            return
        self._sync_count()
        if self._advance_after_fetch:
            self._advance_after_fetch = False
            if self.model.loaded > before:
                self._select_row(before)

    def _set_busy(self, busy: bool) -> None:
        self.busy.set_active(busy)

    def _show_notice(self, *, error: bool = False) -> None:
        missing = self._no_backend or self._state is IndexState.MISSING
        searching = bool(fold_needle(self.field.text()))
        icon, title, body = notice_keys(error, missing, self._state, searching)
        self.notice.set_icon(icon)
        self.notice.set_texts(tr(title), tr(body))
        self.stack.setCurrentIndex(NOTICE)

    def _sync_count(self) -> None:
        total = self.model.total
        language = current_language()
        if self._query is None or self._blocked():
            self.count.setText("")
        elif total == 0:
            self.count.setText(tr("find.count.none"))
        else:
            self.count.setText(plural(total, "find.count", n=format_count(total, language)))
        shown = self.model.loaded
        partial = 0 < shown < total
        loaded = tr("find.count.partial", shown=format_count(shown, language))
        self.count.setToolTip(loaded if partial else "")
        short = 0 < len(fold_needle(self.field.text())) < MIN_INDEXED_LENGTH
        self.hint.setText(tr("find.state.short.text") if short else "")
        self.hint.setVisible(short)
        self.previous_button.setVisible(shown > 0)
        self.next_button.setVisible(shown > 0)

    def select_next(self) -> None:
        self._step(1)

    def select_previous(self) -> None:
        self._step(-1)

    def _step(self, delta: int) -> None:
        current = self.results.currentIndex()
        row = (
            current.row() + delta
            if current.isValid()
            else (0 if delta > 0 else self.model.loaded - 1)
        )
        if row >= self.model.loaded:
            if self.model.canFetchMore():
                self._advance_after_fetch = True
                self.model.fetchMore()
            return
        if row >= 0:
            self._select_row(row)

    def _select_row(self, row: int) -> None:
        index = self.model.index(row, 0)
        if index.isValid():
            self.results.setCurrentIndex(index)
            self.results.scrollTo(index)

    def selected_hit(self) -> SearchHit | None:
        index = self.results.currentIndex()
        return self.model.hit_at(index.row()) if index.isValid() else None

    def _on_current(self, current: QModelIndex, _previous: QModelIndex) -> None:
        hit = self.model.hit_at(current.row()) if current.isValid() else None
        if hit is not None and self.ctx.is_open:
            self.ctx.load(hit)

    def _on_activated(self, index: QModelIndex) -> None:
        if index.isValid():
            self.open_context()

    def open_context(self) -> None:
        hit = self.selected_hit()
        if hit is not None and self.ctx.open(hit):
            total = max(self.splitter.width(), 1)
            self.splitter.setSizes([total * 3 // 5, total * 2 // 5])

    def close_context(self) -> None:
        self.ctx.close()
        self.results.setFocus(Qt.FocusReason.OtherFocusReason)

    def _target_hit(self) -> SearchHit | None:
        return self.ctx.target() or self.selected_hit()

    def copy_text(self) -> None:
        hit = self._target_hit()
        if hit is not None:
            actions.copy_text(self, hit)

    def copy_link(self) -> None:
        hit = self._target_hit()
        if hit is not None:
            actions.copy_link(self, hit)

    def open_in_telegram(self) -> None:
        hit = self._target_hit()
        if hit is not None:
            actions.open_link(self, hit)

    def refresh_status(self) -> None:
        future = self._worker.run(_read_status)
        self._runner.watch(future, self._on_status)

    def _on_snapshot(self, snapshot: dict[str, object]) -> None:
        value = snapshot.get("search")
        if value == self._last_snapshot_value:
            return
        self._last_snapshot_value = value
        self.refresh_status()

    def _on_status(self, done: Future[StatusReply]) -> None:
        try:
            reply = done.result()
        except Exception as error:
            log.warning("reading the search status failed: %s", type(error).__name__)
            return
        before = self._state
        if reply is None:
            self._no_backend = True
            self._status = None
            self._state = IndexState.MISSING
            self._chats = ()
        else:
            self._no_backend = False
            self._status, self._chats = reply
            self._state = self._status.state
        self._sync_status()
        self.chat_filter.set_chats(self._chats)
        wants = self._state in (IndexState.BUILDING, IndexState.READY)
        if wants and before not in (None, self._state) and fold_needle(self.field.text()):
            self.run_query()
        elif self.stack.currentIndex() == NOTICE:
            self._show_notice()
            self._sync_count()

    def _sync_status(self) -> None:
        changing = self.strip.show_state(self._state, self._status)
        if changing and self.isVisible():
            self._poll.start()
        else:
            self._poll.stop()

    def _retranslate(self) -> None:
        if self._built:
            self.period.set_options(self._period_options(), self._period)
        self.previous_button.set_tooltip(tr("find.previous"))
        self.next_button.set_tooltip(tr("find.next"))
        self.results.setAccessibleName(tr("nav.search"))
        self.model.layoutChanged.emit()
        self._sync_status()
        self.chat_filter.retranslate()
        self._sync_count()
        if self.stack.currentIndex() == NOTICE:
            self._show_notice()

    def _restyle(self) -> None:
        kit = self.gui.kit
        pad = kit.px(PAGE_PADDING)
        self._column.setContentsMargins(pad, kit.px(SPACE[6]), pad, kit.px(SPACE[5]))
        self._column.setSpacing(kit.px(SPACE[4]))
        self.chat_filter.button.setMinimumWidth(kit.px(150))
        self.results.sync_width()
