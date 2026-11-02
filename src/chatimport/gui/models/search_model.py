"""The result list: pages of hits pulled lazily as the view scrolls.

`reset` takes the first page and learns the real total; `canFetchMore`/`fetchMore` then ask the
owner (through `more_requested`) for the next offset, and `append` takes the answer. A page
whose query or offset no longer fits is refused, so a late answer of an older search can never
land in the list.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt, Signal

from chatimport.gui.format import format_exact

if TYPE_CHECKING:
    from chatimport.search_types import SearchHit, SearchPage, SearchQuery

HIT_ROLE: Final = Qt.ItemDataRole.UserRole + 1

type _Index = QModelIndex | QPersistentModelIndex


def same_search(a: SearchQuery, b: SearchQuery) -> bool:
    return replace(a, offset=0) == replace(b, offset=0)


class SearchResultsModel(QAbstractListModel):
    more_requested = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._hits: list[SearchHit] = []
        self._total = 0
        self._query: SearchQuery | None = None
        self._fetching = False

    @property
    def total(self) -> int:
        return self._total

    @property
    def loaded(self) -> int:
        return len(self._hits)

    @property
    def fetching(self) -> bool:
        return self._fetching

    @property
    def needle(self) -> str:
        return self._query.text if self._query is not None else ""

    def hit_at(self, row: int) -> SearchHit | None:
        return self._hits[row] if 0 <= row < len(self._hits) else None

    def rowCount(self, parent: _Index = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._hits)

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> object:
        hit = self.hit_at(index.row()) if index.isValid() else None
        if hit is None:
            return None
        if role == HIT_ROLE:
            return hit
        if role == Qt.ItemDataRole.DisplayRole:
            return hit.text
        if role == Qt.ItemDataRole.ToolTipRole:
            return format_exact(hit.date)
        return None

    def canFetchMore(self, parent: _Index = QModelIndex()) -> bool:  # noqa: B008
        return not parent.isValid() and not self._fetching and len(self._hits) < self._total

    def fetchMore(self, parent: _Index = QModelIndex()) -> None:  # noqa: B008
        if not self.canFetchMore(parent):
            return
        self._fetching = True
        self.more_requested.emit(len(self._hits))

    def reset(self, page: SearchPage) -> None:
        self.beginResetModel()
        self._hits = list(page.hits)
        self._total = page.total
        self._query = page.query
        self._fetching = False
        self.endResetModel()

    def clear(self) -> None:
        self.beginResetModel()
        self._hits = []
        self._total = 0
        self._query = None
        self._fetching = False
        self.endResetModel()

    def append(self, page: SearchPage) -> bool:
        """Add a later page; refused (False) unless it continues exactly the current list."""
        query = self._query
        if query is None or not same_search(query, page.query):
            return False
        if page.query.offset != len(self._hits):
            return False
        self._fetching = False
        if not page.hits:
            self._total = len(self._hits)
            return True
        first = len(self._hits)
        self.beginInsertRows(QModelIndex(), first, first + len(page.hits) - 1)
        self._hits.extend(page.hits)
        self._total = max(page.total, len(self._hits))
        self.endInsertRows()
        return True

    def fetch_failed(self) -> None:
        self._fetching = False
