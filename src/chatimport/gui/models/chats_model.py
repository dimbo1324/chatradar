"""The chats table: a model updated in place from snapshots, and the filter/sort proxy over it.

The model is never reset on a new snapshot: rows are matched by `chat_id`, changed rows emit
`dataChanged`, new ones are inserted, vanished ones removed. That keeps the selection, the scroll
position and the sort order while the numbers move. Relative times are not stored: `tick()` asks
the view to repaint the time-dependent cells from the shared clock.
"""

from __future__ import annotations

import math
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
)

from chatimport.gui.format import format_count
from chatimport.gui.models.presentation import (
    age_seconds,
    freshness_of,
    history_chip,
    history_tooltip,
    last_message_text,
    last_message_tooltip,
    span_text,
    status_chip,
    status_kind,
)
from chatimport.gui.strings import current_language, translate
from chatimport.runtime import BackfillState
from chatimport.textnorm import fold

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from chatimport.gui.format import Freshness, FreshnessThresholds
    from chatimport.gui.models.snapshot import ChatRow

ROW_ROLE: Final = Qt.ItemDataRole.UserRole + 1
SORT_ROLE: Final = Qt.ItemDataRole.UserRole + 2
INFINITY: Final = math.inf

_AnyIndex = QModelIndex | QPersistentModelIndex


class Column(IntEnum):
    CHAT = 0
    STATUS = 1
    HISTORY = 2
    LAST_MESSAGE = 3
    MESSAGES = 4
    SPAN = 5


_HEADERS: Final = ("chat", "status", "history", "last", "messages", "span")
_STATUS_RANK: Final = {"error": 0, "no_access": 1, "starting": 2, "live": 3, "paused": 4}
_HISTORY_RANK: Final = {
    BackfillState.RUNNING: 0,
    BackfillState.RETRYING: 1,
    BackfillState.WAITING: 2,
    BackfillState.DISK_STOPPED: 3,
    BackfillState.PAUSED: 4,
    BackfillState.IDLE: 5,
    BackfillState.DONE: 6,
    BackfillState.NO_ACCESS: 7,
}


class ChatsTableModel(QAbstractTableModel):
    def __init__(
        self,
        clock: Callable[[], datetime],
        thresholds: Callable[[int], FreshnessThresholds],
        *,
        absolute_time: bool = False,
    ) -> None:
        super().__init__()
        self._clock = clock
        self._thresholds = thresholds
        self._rows: list[ChatRow] = []
        self._absolute = absolute_time

    @property
    def absolute_time(self) -> bool:
        return self._absolute

    def set_absolute_time(self, absolute: bool) -> None:
        if absolute != self._absolute:
            self._absolute = absolute
            self._touch_column(Column.LAST_MESSAGE)

    def now(self) -> datetime:
        return self._clock()

    def row_at(self, row: int) -> ChatRow:
        return self._rows[row]

    def chat_ids(self) -> list[int]:
        return [row.chat_id for row in self._rows]

    def set_rows(self, rows: Sequence[ChatRow]) -> None:
        incoming = {row.chat_id: row for row in rows}
        for position in range(len(self._rows) - 1, -1, -1):
            if self._rows[position].chat_id not in incoming:
                self.beginRemoveRows(QModelIndex(), position, position)
                del self._rows[position]
                self.endRemoveRows()
        known = {row.chat_id for row in self._rows}
        for position, current in enumerate(self._rows):
            fresh = incoming[current.chat_id]
            if fresh != current:
                self._rows[position] = fresh
                self.dataChanged.emit(
                    self.index(position, 0), self.index(position, len(Column) - 1)
                )
        added = [row for row in rows if row.chat_id not in known]
        if added:
            start = len(self._rows)
            self.beginInsertRows(QModelIndex(), start, start + len(added) - 1)
            self._rows.extend(added)
            self.endInsertRows()

    def tick(self) -> None:
        """Repaint what depends on the clock: the age and the retry countdown."""
        self._touch_column(Column.LAST_MESSAGE)
        retrying = [
            i for i, row in enumerate(self._rows) if row.backfill.state is BackfillState.RETRYING
        ]
        for position in retrying:
            index = self.index(position, Column.HISTORY)
            self.dataChanged.emit(index, index)

    def retranslate(self) -> None:
        if self._rows:
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, len(Column) - 1)
            )
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(Column) - 1)

    def _touch_column(self, column: Column) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0, column), self.index(len(self._rows) - 1, column))

    def rowCount(self, parent: _AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _AnyIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(Column)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(_HEADERS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return translate(current_language(), f"chats.col.{_HEADERS[section]}")
        if role == Qt.ItemDataRole.ToolTipRole and section == Column.LAST_MESSAGE:
            return translate(current_language(), "chats.col.last_tip")
        if role == Qt.ItemDataRole.TextAlignmentRole and section == Column.MESSAGES:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def data(self, index: _AnyIndex, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = Column(index.column())
        if role == ROW_ROLE:
            return row
        if role == SORT_ROLE:
            return self.sort_value(row, column)
        language = current_language()
        now = self._clock()
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(row, column, now)
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(row, column, now)
        if role == Qt.ItemDataRole.TextAlignmentRole and column is Column.MESSAGES:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{row.title}: {history_chip(row, language).text}"
        return None

    def _display(self, row: ChatRow, column: Column, now: datetime) -> str:
        language = current_language()
        match column:
            case Column.CHAT:
                return row.title
            case Column.STATUS:
                return status_chip(row, language).text
            case Column.HISTORY:
                return history_chip(row, language).text
            case Column.LAST_MESSAGE:
                return last_message_text(row, now, self._absolute, language)
            case Column.MESSAGES:
                return format_count(row.records, language)
            case _:
                return span_text(row)

    def _tooltip(self, row: ChatRow, column: Column, now: datetime) -> str | None:
        language = current_language()
        if column is Column.LAST_MESSAGE:
            return last_message_tooltip(row, now, language)
        if column is Column.HISTORY:
            return history_tooltip(row, now, language)
        if column is Column.CHAT:
            return f"{row.title}\n{row.chat_id}"
        return None

    def freshness(self, row: ChatRow) -> Freshness:
        return freshness_of(row, self._clock(), self._thresholds(row.chat_id))

    @staticmethod
    def sort_value(row: ChatRow, column: Column) -> object:
        match column:
            case Column.CHAT:
                return fold(row.title)
            case Column.STATUS:
                return float(_STATUS_RANK[status_kind(row)])
            case Column.HISTORY:
                rank = float(_HISTORY_RANK[row.backfill.state])
                return rank * 10 - (row.backfill.progress or 0.0)
            case Column.LAST_MESSAGE:
                return INFINITY if row.newest_date is None else -row.newest_date.timestamp()
            case Column.MESSAGES:
                return float(row.records)
            case _:
                return INFINITY if row.oldest_date is None else row.oldest_date.timestamp()


class FilterMode(StrEnum):
    ALL = "all"
    RUNNING = "running"
    WAITING = "waiting"
    PAUSED = "paused"
    PROBLEMS = "problems"
    SILENT_1H = "silent_1h"
    SILENT_1D = "silent_1d"
    SILENT_7D = "silent_7d"


SILENT_SECONDS: Final = {
    FilterMode.SILENT_1H: 3_600,
    FilterMode.SILENT_1D: 86_400,
    FilterMode.SILENT_7D: 7 * 86_400,
}


def matches_mode(row: ChatRow, mode: FilterMode, now: datetime) -> bool:
    state = row.backfill.state
    if mode is FilterMode.ALL:
        return True
    if mode is FilterMode.RUNNING:
        return state is BackfillState.RUNNING
    if mode is FilterMode.WAITING:
        return state in (BackfillState.WAITING, BackfillState.RETRYING)
    if mode is FilterMode.PAUSED:
        return row.is_paused or state is BackfillState.PAUSED
    if mode is FilterMode.PROBLEMS:
        return row.has_problem or state is BackfillState.DISK_STOPPED
    age = age_seconds(row, now)
    return age is None or age >= SILENT_SECONDS[mode]


class ChatsFilterProxy(QSortFilterProxyModel):
    def __init__(self, source: ChatsTableModel, clock: Callable[[], datetime]) -> None:
        super().__init__()
        self._clock = clock
        self._query = ""
        self._mode = FilterMode.ALL
        self.setSourceModel(source)
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    @property
    def mode(self) -> FilterMode:
        return self._mode

    def set_query(self, text: str) -> None:
        folded = fold(text)
        if folded != self._query:
            self._query = folded
            self._refilter()

    def set_mode(self, mode: FilterMode) -> None:
        if mode is not self._mode:
            self._mode = mode
            self._refilter()

    def refresh_time(self) -> None:
        if self._mode in SILENT_SECONDS:
            self._refilter()

    def _refilter(self) -> None:
        self.beginFilterChange()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row: int, source_parent: _AnyIndex) -> bool:
        model = self.sourceModel()
        if not isinstance(model, ChatsTableModel):
            return True
        row = model.row_at(source_row)
        if (
            self._query
            and self._query not in fold(row.title)
            and self._query not in str(row.chat_id)
        ):
            return False
        return matches_mode(row, self._mode, self._clock())
