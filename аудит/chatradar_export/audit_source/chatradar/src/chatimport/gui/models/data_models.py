"""Table models of the Data page: usage per chat, the clean-up preview and integrity issues.

All three are replaced wholesale (`set_*`), since their data arrives in one piece from a
worker thread; they hold plain values and format through the current language on demand.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Final, cast

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from chatimport.gui.format import format_bytes, format_count
from chatimport.gui.i18n import tr
from chatimport.gui.locales import data as _data_strings
from chatimport.gui.strings import current_language

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from chatimport.trim import ChatTrimPreview
    from chatimport.usage import ChatUsage

_ = _data_strings
type Index = QModelIndex | QPersistentModelIndex

SHARE_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 1
MEDIA_SHARE_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 2
TONE_ROLE: Final = int(Qt.ItemDataRole.UserRole) + 3
RIGHT: Final = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT: Final = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
SEVERITY_TONES: Final = {"error": "danger", "warning": "warning", "info": "info"}


class _Base(QAbstractTableModel):
    COLUMN_KEYS: tuple[str, ...] = ()
    RIGHT_COLUMNS: frozenset[int] = frozenset()

    def columnCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self.COLUMN_KEYS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,  # pyright: ignore[reportArgumentType]
    ) -> Any:
        if orientation != Qt.Orientation.Horizontal or not 0 <= section < len(self.COLUMN_KEYS):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return tr(self.COLUMN_KEYS[section])
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if section in self.RIGHT_COLUMNS else LEFT
        return None

    def retranslate(self) -> None:
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        if self.rowCount():
            self.dataChanged.emit(
                self.index(0, 0), self.index(self.rowCount() - 1, self.columnCount() - 1)
            )


class UsageColumn(IntEnum):
    CHAT = 0
    SIZE = 1
    SHARE = 2
    MESSAGES = 3
    PARTS = 4


class UsageModel(_Base):
    COLUMN_KEYS = (
        "data.storage.col.chat",
        "data.storage.col.size",
        "data.storage.col.share",
        "data.storage.col.messages",
        "data.storage.col.parts",
    )
    RIGHT_COLUMNS = frozenset({UsageColumn.SIZE, UsageColumn.MESSAGES, UsageColumn.PARTS})

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ChatUsage] = []
        self._largest = 1

    def set_usage(self, chats: Sequence[ChatUsage]) -> None:
        self.beginResetModel()
        self._rows = sorted(chats, key=lambda chat: chat.total_bytes, reverse=True)
        self._largest = max((chat.total_bytes for chat in self._rows), default=0) or 1
        self.endResetModel()

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self._rows)

    @staticmethod
    def title_of(chat: ChatUsage) -> str:
        return chat.title or tr("data.unreadable_chat", folder=chat.folder.name)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pyright: ignore[reportArgumentType]
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        chat = self._rows[index.row()]
        column = index.column()
        language = current_language()
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if column in self.RIGHT_COLUMNS else LEFT
        if role == SHARE_ROLE:
            return chat.total_bytes / self._largest
        if role == MEDIA_SHARE_ROLE:
            return chat.media_bytes / chat.total_bytes if chat.total_bytes else 0.0
        if role == Qt.ItemDataRole.ToolTipRole and column == UsageColumn.CHAT:
            return str(chat.folder)
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == UsageColumn.CHAT:
            return self.title_of(chat)
        if column == UsageColumn.SIZE:
            return format_bytes(chat.total_bytes, language)
        if column == UsageColumn.MESSAGES:
            return "-" if chat.records is None else format_count(chat.records, language)
        if column == UsageColumn.PARTS:
            return format_count(chat.parts, language)
        return None


@dataclass(frozen=True, slots=True)
class IssueRow:
    severity: str
    folder: str
    message: str


class PreviewColumn(IntEnum):
    CHAT = 0
    RECORDS = 1
    SIZE = 2
    OLDEST = 3


class PreviewModel(_Base):
    COLUMN_KEYS = (
        "data.cleanup.col.chat",
        "data.cleanup.col.records",
        "data.cleanup.col.size",
        "data.cleanup.col.oldest",
    )
    RIGHT_COLUMNS = frozenset({PreviewColumn.RECORDS, PreviewColumn.SIZE})

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[ChatTrimPreview] = []

    def set_preview(self, chats: Sequence[ChatTrimPreview]) -> None:
        self.beginResetModel()
        self._rows = sorted(chats, key=lambda chat: chat.bytes_freed, reverse=True)
        self.endResetModel()

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pyright: ignore[reportArgumentType]
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        chat = self._rows[index.row()]
        column = index.column()
        language = current_language()
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return RIGHT if column in self.RIGHT_COLUMNS else LEFT
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == PreviewColumn.CHAT:
            return chat.title
        if column == PreviewColumn.RECORDS:
            share = f"{format_count(chat.records_deleted, language)} / "
            return share + format_count(chat.records_total, language)
        if column == PreviewColumn.SIZE:
            return format_bytes(chat.bytes_freed, language) if chat.records_deleted else "-"
        if chat.oldest_after is None:
            return tr("data.cleanup.oldest_none") if chat.records_deleted else "-"
        return f"{chat.oldest_after.astimezone():%Y-%m-%d}"


class IssueColumn(IntEnum):
    SEVERITY = 0
    FOLDER = 1
    MESSAGE = 2


class IssuesModel(_Base):
    COLUMN_KEYS = (
        "data.integrity.col.severity",
        "data.integrity.col.folder",
        "data.integrity.col.message",
    )

    def __init__(self) -> None:
        super().__init__()
        self._rows: list[IssueRow] = []

    def set_issues(self, rows: Sequence[IssueRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent: Index = QModelIndex()) -> int:  # noqa: B008 - Qt signature
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:  # pyright: ignore[reportArgumentType]
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        column = index.column()
        if role == TONE_ROLE:
            return SEVERITY_TONES.get(row.severity, "neutral")
        if role == Qt.ItemDataRole.ToolTipRole and column == IssueColumn.MESSAGE:
            return row.message
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if column == IssueColumn.SEVERITY:
            key = f"data.integrity.severity.{row.severity}"
            return tr(key) if row.severity in SEVERITY_TONES else row.severity
        return row.folder if column == IssueColumn.FOLDER else row.message


def parse_issues(data: Mapping[str, Any]) -> list[IssueRow]:
    """Issue rows from a `check` command result's data; malformed entries are skipped."""
    raw: object = data.get("issues")
    rows: list[IssueRow] = []
    if not isinstance(raw, list):
        return rows
    for item in cast("list[object]", raw):
        if isinstance(item, dict):
            values = cast("dict[str, object]", item)
            rows.append(
                IssueRow(
                    str(values.get("severity", "")),
                    str(values.get("folder", "")),
                    str(values.get("message", "")),
                )
            )
    return rows
