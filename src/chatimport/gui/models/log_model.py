"""The log table: an append-only model with a row cap and a proxy that filters it."""

from __future__ import annotations

from enum import IntEnum
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from chatimport.gui.format import format_exact
from chatimport.gui.models.log_parser import Level, LogRecord
from chatimport.gui.strings import translate
from chatimport.textnorm import fold

if TYPE_CHECKING:
    from PySide6.QtCore import QPersistentModelIndex

    from chatimport.gui.strings import Language

type _Index = QModelIndex | QPersistentModelIndex

MAX_ROWS: Final = 10_000
RECORD_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 1
TIME_FORMAT: Final = "%m-%d %H:%M:%S"
NS: Final = "log."


class Column(IntEnum):
    TIME = 0
    LEVEL = 1
    SOURCE = 2
    MESSAGE = 3


COLUMN_KEYS: Final = {
    Column.TIME: "log.col.time",
    Column.LEVEL: "log.col.level",
    Column.SOURCE: "log.col.source",
    Column.MESSAGE: "log.col.message",
}


def local_time_text(record: LogRecord) -> str:
    return record.time.astimezone().strftime(TIME_FORMAT)


class LogModel(QAbstractTableModel):
    """Oldest first. New records are appended; beyond `MAX_ROWS` the oldest rows are dropped."""

    def __init__(self, language: Language, limit: int = MAX_ROWS) -> None:
        super().__init__()
        self._rows: list[LogRecord] = []
        self._limit = limit
        self._language: Language = language
        self._counts: dict[Level, int] = dict.fromkeys(Level, 0)

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def warnings(self) -> int:
        return self._counts[Level.WARNING]

    @property
    def errors(self) -> int:
        return self._counts[Level.ERROR] + self._counts[Level.CRITICAL]

    def set_language(self, language: Language) -> None:
        self._language = language
        if self._rows:
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(Column) - 1)
            self.dataChanged.emit(
                self.index(0, 0), self.index(len(self._rows) - 1, len(Column) - 1)
            )

    def record_at(self, row: int) -> LogRecord:
        return self._rows[row]

    def records(self) -> list[LogRecord]:
        return list(self._rows)

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(Column)

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation is Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return translate(self._language, COLUMN_KEYS[Column(section)])
        return None

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        record = self._rows[index.row()]
        column = Column(index.column())
        if role == RECORD_ROLE:
            return record
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display(record, column)
        if role == Qt.ItemDataRole.ToolTipRole and column is Column.TIME:
            return format_exact(record.time)
        if role == Qt.ItemDataRole.ToolTipRole and column is Column.SOURCE:
            return record.logger
        return None

    def _display(self, record: LogRecord, column: Column) -> str:
        if column is Column.TIME:
            return local_time_text(record)
        if column is Column.LEVEL:
            return translate(self._language, f"{NS}level.{record.level.name.lower()}")
        if column is Column.SOURCE:
            return record.source
        return record.message

    def _count(self, records: list[LogRecord], sign: int) -> None:
        for record in records:
            self._counts[record.level] += sign

    def append(self, records: list[LogRecord]) -> None:
        if not records:
            return
        records = records[-self._limit :]
        overflow = len(self._rows) + len(records) - self._limit
        if overflow > 0:
            self.beginRemoveRows(QModelIndex(), 0, overflow - 1)
            self._count(self._rows[:overflow], -1)
            del self._rows[:overflow]
            self.endRemoveRows()
        first = len(self._rows)
        self.beginInsertRows(QModelIndex(), first, first + len(records) - 1)
        self._rows.extend(records)
        self._count(records, 1)
        self.endInsertRows()

    def prepend(self, records: list[LogRecord]) -> int:
        """Insert older records on top while there is room; returns how many fit."""
        room = self._limit - len(self._rows)
        take = records[len(records) - room :] if 0 < room < len(records) else records[:room]
        if room <= 0 or not take:
            return 0
        self.beginInsertRows(QModelIndex(), 0, len(take) - 1)
        self._rows[:0] = take
        self._count(take, 1)
        self.endInsertRows()
        return len(take)

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self._counts = dict.fromkeys(Level, 0)
        self.endResetModel()


class LogFilterProxy(QSortFilterProxyModel):
    """Minimum level, a text query (every word must occur), tracebacks on/off, a logger prefix."""

    def __init__(self, model: LogModel) -> None:
        super().__init__()
        self._model = model
        self.setSourceModel(model)
        self._level = Level.DEBUG
        self._words: list[str] = []
        self._tracebacks = True
        self._prefix = ""

    @property
    def level(self) -> Level:
        return self._level

    def set_level(self, level: Level) -> None:
        self.beginFilterChange()
        self._level = level
        self.endFilterChange()

    def set_query(self, text: str) -> None:
        self.beginFilterChange()
        self._words = fold(text).split()
        self.endFilterChange()

    def set_show_tracebacks(self, show: bool) -> None:
        self.beginFilterChange()
        self._tracebacks = show
        self.endFilterChange()

    def set_logger_prefix(self, prefix: str) -> None:
        self.beginFilterChange()
        self._prefix = prefix
        self.endFilterChange()

    def accepts(self, record: LogRecord) -> bool:
        if record.level < self._level:
            return False
        if not self._tracebacks and record.has_traceback:
            return False
        if self._prefix and not record.logger.startswith(self._prefix):
            return False
        folded = record.folded
        return all(word in folded for word in self._words)

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        return self.accepts(self._model.record_at(source_row))

    def record_at(self, row: int) -> LogRecord:
        return self._model.record_at(self.mapToSource(self.index(row, 0)).row())
