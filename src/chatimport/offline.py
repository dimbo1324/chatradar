"""Helpers for CLI commands that run without the service (the CLI holds the instance lock)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from chatimport.library import LibraryError, load_library
from chatimport.ports import ChatImportError
from chatimport.runtime import ChatRegistry, ChatStatus, SystemClock
from chatimport.storage.layout import chat_folder_name, iter_chat_folders
from chatimport.storage.state import ChatState, load_state, save_state
from chatimport.trim import Trimmer, TrimReport

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from chatimport.app import ServiceContext
    from chatimport.library import ChatEntry
    from chatimport.ports import ChatEvent

_MIB = 1024 * 1024
_NUMBER_RE = re.compile(r"-?\d+")
_TME_RE = re.compile(r"^(?:https?://)?(?:www\.)?t\.me/([A-Za-z0-9_]+)/?$")


class OfflineController:
    """A `ChatController` for a folder with no worker behind it."""

    def __init__(self, folder: Path, state: ChatState) -> None:
        self._folder = folder
        self._initial = state
        self._lock = asyncio.Lock()

    @property
    def chat_id(self) -> int:
        return self._initial.chat_id

    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def submit(self, event: ChatEvent) -> None:
        return None

    def pause(self) -> None:
        return None

    def resume(self) -> None:
        return None

    def pause_backfill(self) -> None:
        return None

    def resume_backfill(self) -> None:
        return None

    def request_refetch(self) -> None:
        return None

    def request_recheck(self, days: int | None = None) -> None:
        return None

    def status(self) -> ChatStatus:
        state = load_state(self._folder) or self._initial
        return ChatStatus(
            chat_id=state.chat_id,
            title=state.title,
            phase=state.phase,
            last_id=state.last_id,
            backfill_done=state.backfill.done,
            oldest_date=None,
            records=sum(info.records for info in state.chunks.values()),
            paused=False,
        )

    async def stop(self) -> None:
        return None


def offline_registry(root: Path) -> ChatRegistry:
    registry = ChatRegistry()
    for folder in iter_chat_folders(root):
        state = load_state(folder)
        if state is not None:
            registry.add(OfflineController(folder, state))
    return registry


async def offline_trim(ctx: ServiceContext, pct: int, chat: int | None) -> TrimReport:
    trimmer = Trimmer(
        ctx.root,
        offline_registry(ctx.root),
        clock=SystemClock(),
        max_chunk_bytes=ctx.config.output.max_chunk_mb * _MIB,
    )
    return await trimmer.trim_percent(pct, chat)


def lower_floor_state(folder: Path, now: datetime) -> bool:
    """Reopen the tail backfill below the floor; False when the chat has no state."""
    state = load_state(folder)
    if state is None:
        return False
    oldest = max(state.backfill.oldest_done_id, state.floor_id)
    save_state(
        folder,
        replace(
            state,
            floor_id=0,
            floor_reason=None,
            backfill=replace(state.backfill, done=False, oldest_done_id=oldest),
            updated_at=now,
        ),
    )
    return True


def lower_floor(root: Path, chat_id: int | None) -> list[int]:
    now = SystemClock().now()
    lowered: list[int] = []
    for folder in iter_chat_folders(root):
        state = load_state(folder)
        if state is None or (chat_id is not None and state.chat_id != chat_id):
            continue
        if lower_floor_state(folder, now):
            lowered.append(state.chat_id)
    return lowered


@dataclass(frozen=True, slots=True)
class _Known:
    chat_id: int
    folder_name: str
    title: str
    username: str | None


def _known_chats(root: Path) -> list[_Known]:
    known: list[_Known] = []
    for folder in iter_chat_folders(root):
        state = load_state(folder)
        if state is not None:
            known.append(_Known(state.chat_id, folder.name, state.title, state.username))
    return known


def _ref_username(ref: str) -> str | None:
    text = ref.strip()
    if text.startswith("@"):
        return text[1:].casefold()
    match = _TME_RE.match(text)
    if match is not None and match.group(1) != "joinchat":
        return match.group(1).casefold()
    return None


def _entry_matches(entry: ChatEntry, chat: _Known) -> bool:
    ref = entry.key
    if _NUMBER_RE.fullmatch(ref):
        return int(ref) == chat.chat_id
    username = _ref_username(ref)
    if username is not None:
        return chat.username is not None and chat.username.casefold() == username
    if entry.name is not None and chat_folder_name(entry.name, chat.chat_id) == chat.folder_name:
        return True
    return chat.title.casefold() == ref.casefold()


def resolve_chat_selector(ctx: ServiceContext, text: str) -> int:
    """Map a chat id, `@username`, folder name, title, library name or ref to a chat id."""
    needle = text.strip()
    if not needle:
        raise ChatImportError("the chat selector is empty")
    if _NUMBER_RE.fullmatch(needle):
        return int(needle)
    folded = needle.casefold()
    username = folded[1:] if folded.startswith("@") else folded
    known = _known_chats(ctx.root)
    hits = {
        chat.chat_id
        for chat in known
        if folded in (chat.folder_name.casefold(), chat.title.casefold())
        or (chat.username is not None and chat.username.casefold() == username)
    }
    try:
        entry = load_library(ctx.library_file).find(needle)
    except LibraryError:
        entry = None
    if entry is not None:
        hits.update(chat.chat_id for chat in known if _entry_matches(entry, chat))
        if not hits and _NUMBER_RE.fullmatch(entry.key):
            hits.add(int(entry.key))
    if not hits:
        raise ChatImportError(f"no known chat matches {needle!r}")
    if len(hits) > 1:
        raise ChatImportError(f"{needle!r} matches several chats; use the numeric chat id")
    return next(iter(hits))
