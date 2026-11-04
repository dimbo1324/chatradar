"""How much disk the archive uses, per chat: sizes from `stat` only, no part is decoded.

Built to run in a worker thread: it never takes a lock, tolerates folders and files that vanish
while it walks, and reads `state.json` (small) only for the title and the record count.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.storage.layout import (
    MEDIA_DIR,
    SERVICE_PREFIX,
    STATE_FILE,
    iter_chat_folders,
    parse_part_name,
)
from chatimport.storage.state import StateUnreadable, load_state

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["ArchiveUsage", "ChatUsage", "archive_usage"]

_PARTS_SUFFIX: Final = ".jsonl"


@dataclass(frozen=True, slots=True)
class ChatUsage:
    """One chat folder; `chat_id`, `title` and `records` are None when its state is unreadable."""

    chat_id: int | None
    title: str | None
    folder: Path
    jsonl_bytes: int
    media_bytes: int
    parts: int
    records: int | None

    @property
    def total_bytes(self) -> int:
        return self.jsonl_bytes + self.media_bytes


@dataclass(frozen=True, slots=True)
class ArchiveUsage:
    chats: tuple[ChatUsage, ...]
    jsonl_total: int
    media_total: int
    service_files_total: int
    free_bytes: int | None

    @property
    def total_bytes(self) -> int:
        return self.jsonl_total + self.media_total + self.service_files_total


def _tree_bytes(path: str) -> int:
    """Total size of every file under `path`; links are counted as links, never followed."""
    total = 0
    stack = [path]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                            stack.append(entry.path)
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class _Sizes:
    __slots__ = ("jsonl", "media", "other", "parts")

    def __init__(self) -> None:
        self.jsonl = 0
        self.media = 0
        self.other = 0
        self.parts = 0


def _measure_folder(folder: Path) -> _Sizes:
    sizes = _Sizes()
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if entry.name == MEDIA_DIR:
                            sizes.media += _tree_bytes(entry.path)
                        else:
                            sizes.other += _tree_bytes(entry.path)
                        continue
                    size = entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
                if entry.name.endswith(_PARTS_SUFFIX) and parse_part_name(entry.name) is not None:
                    sizes.jsonl += size
                    sizes.parts += 1
                else:
                    sizes.other += size
    except OSError:
        pass
    return sizes


def _chat_usage(folder: Path, sizes: _Sizes) -> ChatUsage | None:
    try:
        state = load_state(folder)
    except StateUnreadable:
        return ChatUsage(None, None, folder, sizes.jsonl, sizes.media, sizes.parts, None)
    if state is None:
        if sizes.parts == 0 and not (folder / STATE_FILE).exists():
            return None
        return ChatUsage(None, None, folder, sizes.jsonl, sizes.media, sizes.parts, None)
    return ChatUsage(
        state.chat_id,
        state.title,
        folder,
        sizes.jsonl,
        sizes.media,
        sizes.parts,
        state.total_records,
    )


def _service_files_bytes(root: Path) -> int:
    total = 0
    try:
        with os.scandir(root) as entries:
            for entry in entries:
                if not entry.name.startswith(SERVICE_PREFIX):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        total += _tree_bytes(entry.path)
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        pass
    return total


def _free_bytes(root: Path) -> int | None:
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return None


def archive_usage(root: Path) -> ArchiveUsage:
    chats: list[ChatUsage] = []
    other = _service_files_bytes(root)
    for folder in iter_chat_folders(root):
        sizes = _measure_folder(folder)
        other += sizes.other
        usage = _chat_usage(folder, sizes)
        if usage is not None:
            chats.append(usage)
    return ArchiveUsage(
        chats=tuple(chats),
        jsonl_total=sum(chat.jsonl_bytes for chat in chats),
        media_total=sum(chat.media_bytes for chat in chats),
        service_files_total=other,
        free_bytes=_free_bytes(root),
    )
