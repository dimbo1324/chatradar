"""The raw store: append-only JSONL files under `data/raw/`, the source of truth.

Layout: `<root>/<source>/<chat_id>/<UTC timestamp>-<counter>.jsonl`, one file per chat
per `append` call. File names sort in write order, so reading them by name replays the
history of every chat in the order it was fetched.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
from collections import defaultdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import ValidationError

from chatradar.domain.models import ChatInfo, RawRecord, Source
from chatradar.logs import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator, Sequence
    from pathlib import Path

log = get_logger(__name__)

_SUFFIX = ".jsonl"
_CHAT_FILE = "chat.json"


class JsonlRawStore:
    """`RawStore` over a directory of JSONL files. Single writer (the worker)."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._counter = itertools.count()

    async def append(self, records: Sequence[RawRecord]) -> int:
        if not records:
            return 0
        groups: dict[tuple[Source, str], list[RawRecord]] = defaultdict(list)
        for record in records:
            groups[(record.source, record.chat_id)].append(record)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        for (source, chat_id), group in groups.items():
            path = (
                self.root / source.value / chat_id / f"{stamp}-{next(self._counter):06d}{_SUFFIX}"
            )
            await asyncio.to_thread(_write_lines, path, [r.model_dump_json() for r in group])
        return len(records)

    async def read(
        self, source: Source | None = None, chat_id: str | None = None
    ) -> AsyncIterator[RawRecord]:
        for path in await asyncio.to_thread(self._files, source, chat_id):
            lines = await asyncio.to_thread(path.read_text, encoding="utf-8")
            for record in _parse_lines(path, lines):
                yield record

    async def save_chats(self, chats: Sequence[ChatInfo]) -> None:
        """Keep chat metadata next to its records, so a rebuild restores titles and links."""
        for chat in chats:
            path = self.root / chat.source.value / chat.chat_id / _CHAT_FILE
            await asyncio.to_thread(_replace_file, path, chat.model_dump_json())

    async def load_chats(self) -> list[ChatInfo]:
        paths = await asyncio.to_thread(lambda: sorted(self.root.glob(f"*/*/{_CHAT_FILE}")))
        return [
            ChatInfo.model_validate_json(await asyncio.to_thread(path.read_text, encoding="utf-8"))
            for path in paths
        ]

    def _files(self, source: Source | None, chat_id: str | None) -> list[Path]:
        sources = [source] if source is not None else list(Source)
        files: list[Path] = []
        for src in sources:
            source_dir = self.root / src.value
            if not source_dir.is_dir():
                continue
            chat_dirs = (
                [source_dir / chat_id]
                if chat_id is not None
                else sorted(p for p in source_dir.iterdir() if p.is_dir())
            )
            for chat_dir in chat_dirs:
                if chat_dir.is_dir():
                    files.extend(sorted(chat_dir.glob(f"*{_SUFFIX}")))
        return files


def _write_lines(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.writelines(f"{line}\n" for line in lines)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def _parse_lines(path: Path, content: str) -> Iterator[RawRecord]:
    lines = content.split("\n")
    complete = content.endswith("\n")
    if complete:
        lines.pop()
    last = len(lines) - 1
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            yield RawRecord.model_validate(payload)
        except (json.JSONDecodeError, ValidationError):
            if number == last and not complete:
                log.warning("raw.truncated_line", path=path.name, line=number + 1)
                continue
            raise
