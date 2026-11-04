"""One chat folder as an object: find it, read and save its state, write its parts.

Every method is synchronous and file-only, so a caller may run it through
`asyncio.to_thread`. The caller holds the chat's lock for the whole call; each method resolves
the folder once, so all files of one operation land in the same folder.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chatimport.ports import ChatImportError
from chatimport.records import MessageRecord
from chatimport.storage.layout import find_chat_folder
from chatimport.storage.reader import iter_part_records
from chatimport.storage.recover import recover_chat
from chatimport.storage.state import load_state
from chatimport.storage.writer import ChunkWriter

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path

    from chatimport.ports import Clock
    from chatimport.records import Record
    from chatimport.storage.state import ChatState


class StateGone(ChatImportError):
    """The chat's `state.json` (or its whole folder) disappeared."""


class ChatStore:
    def __init__(
        self,
        root: Path,
        chat_id: int,
        default_name: str,
        *,
        max_chunk_bytes: int,
        clock: Clock,
    ) -> None:
        self.root = root
        self.chat_id = chat_id
        self.default_name = default_name
        self.max_chunk_bytes = max_chunk_bytes
        self._clock = clock
        self._folder: Path | None = None

    @property
    def folder(self) -> Path:
        """The folder found by the last `resolve_folder()`; no disk access."""
        return self._folder if self._folder is not None else self.root / self.default_name

    def resolve_folder(self) -> Path:
        """The chat's folder: the cached one while it exists, else the folder whose state
        names this chat, else `<root>/<default_name>` (created by the first write)."""
        cached = self._folder
        if cached is not None and cached.is_dir():
            return cached
        found = find_chat_folder(self.root, self.chat_id)
        self._folder = found if found is not None else self.root / self.default_name
        return self._folder

    def writer(self, folder: Path | None = None) -> ChunkWriter:
        return ChunkWriter(folder or self.resolve_folder(), self.max_chunk_bytes, self._clock.now)

    def load(self) -> ChatState | None:
        return load_state(self.resolve_folder())

    def require(self) -> ChatState:
        state = self.load()
        if state is None:
            raise StateGone(f"state of chat {self.chat_id} is gone")
        return state

    def save(self, state: ChatState) -> ChatState:
        return self.writer().update_state(state)

    def append(self, state: ChatState, records: Sequence[Record]) -> ChatState:
        return self.writer().append(state, records)

    def write_month(
        self, state: ChatState, month: str, records: Sequence[MessageRecord]
    ) -> ChatState:
        return self.writer().write_month(state, month, records)

    def merge_month(
        self, state: ChatState, month: str, messages: Sequence[MessageRecord]
    ) -> ChatState:
        return self.writer().merge_month(state, month, messages)

    def recover(self, *, title: str | None = None) -> ChatState:
        return recover_chat(
            self.resolve_folder(),
            now=self._clock.now(),
            fallback_chat_id=self.chat_id,
            fallback_title=title,
        )

    def oldest_message_date(self, state: ChatState) -> datetime | None:
        """Date of the first message in the oldest listed part; unreadable parts are skipped."""
        folder = self.resolve_folder()
        for key in sorted(state.chunks):
            try:
                for record in iter_part_records(folder / f"{key}.jsonl"):
                    if isinstance(record, MessageRecord):
                        return record.date
            except OSError:
                continue
        return None
