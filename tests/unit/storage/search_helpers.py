from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from chatimport.search_index import SearchIndex, open_reader, open_writer
from chatimport.search_indexer import IndexBuilder, StepResult
from chatimport.search_types import SearchBackend, SearchPage, SearchQuery
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import ChatState, new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import CHAT_ID, NOW

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.records import Record

OTHER_CHAT = -1009876543210


def utc(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


class Archive:
    """One real chat folder written through `ChunkWriter`, like the service writes it."""

    def __init__(
        self,
        root: Path,
        chat_id: int = CHAT_ID,
        title: str = "Chat",
        max_bytes: int = 10**9,
    ) -> None:
        self.root = root
        self.chat_id = chat_id
        self.folder = root / chat_folder_name(title, chat_id)
        self.writer = ChunkWriter(self.folder, max_bytes, clock=lambda: NOW)
        self.state: ChatState = new_state(chat_id, title, None, NOW)

    def add(self, *records: Record) -> ChatState:
        self.state = self.writer.append(self.state, list(records))
        return self.state

    def part(self, name: str) -> Path:
        return self.folder / name


class Rig:
    """A writer, a builder over `root`, and read-only access, all closed by `close()`."""

    def __init__(self, root: Path, batch: int = 2000) -> None:
        self.root = root
        self.index: SearchIndex = open_writer(root)
        self.builder = IndexBuilder(self.index, root, lambda: NOW, batch)
        self._reader: SearchBackend | None = None

    @property
    def reader(self) -> SearchBackend:
        if self._reader is None:
            opened = open_reader(self.root)
            assert opened is not None
            self._reader = opened
        return self._reader

    def run(self, limit: int = 1000) -> list[StepResult]:
        results: list[StepResult] = []
        for _ in range(limit):
            result = self.builder.step()
            results.append(result)
            if not result.more:
                return results
        raise AssertionError("the builder never finished")

    def find(
        self,
        text: str,
        *,
        chat_ids: frozenset[int] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> SearchPage:
        return self.reader.search(SearchQuery(text, chat_ids, since, until, limit, offset))

    def ids(self, text: str, **kwargs: Any) -> list[int]:
        return [hit.msg_id for hit in self.find(text, **kwargs).hits]

    def close(self) -> None:
        if self._reader is not None:
            self._reader.close()
        self.index.close()
