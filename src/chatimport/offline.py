"""Helpers for CLI commands that run without the service (the CLI holds the instance lock)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from chatimport.library import LibraryError, load_library
from chatimport.ports import ChatImportError
from chatimport.refs import RefKind, parse_ref
from chatimport.runtime import ChatRegistry, SystemClock
from chatimport.storage.layout import iter_chat_folders, slugify
from chatimport.storage.state import ChatState, StateUnreadable, load_state, save_state
from chatimport.textnorm import fold
from chatimport.trim import Trimmer, TrimReport

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

    from chatimport.app import ServiceContext
    from chatimport.library import ChatEntry

log = logging.getLogger(__name__)

_NUMBER_RE: Final = re.compile(r"-?\d+")
_FALLBACK_SLUG: Final = slugify("")


async def offline_trim(ctx: ServiceContext, pct: int, chat: int | None) -> TrimReport:
    """Trim with no service running: the trimmer finds every chat folder under the root by
    itself, so it gets an empty registry."""
    trimmer = Trimmer(
        ctx.root,
        ChatRegistry(),
        clock=SystemClock(),
        max_chunk_bytes=ctx.config.output.max_chunk_bytes,
    )
    return await trimmer.trim_percent(pct, chat)


def _reopen_below_floor(folder: Path, state: ChatState, now: datetime) -> None:
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


def lower_floor_state(folder: Path, now: datetime) -> bool:
    """Reopen the tail backfill below the floor; False when the chat has no state.

    Raises `StateUnreadable` when `state.json` exists but cannot be read right now."""
    state = load_state(folder)
    if state is None:
        return False
    _reopen_below_floor(folder, state, now)
    return True


def lower_floor(root: Path, chat_id: int | None) -> list[int]:
    now = SystemClock().now()
    lowered: list[int] = []
    for folder in iter_chat_folders(root):
        try:
            state = load_state(folder)
        except StateUnreadable:
            log.warning("skipped a chat whose state is unreadable", extra={"folder": folder.name})
            continue
        if state is None or (chat_id is not None and state.chat_id != chat_id):
            continue
        _reopen_below_floor(folder, state, now)
        lowered.append(state.chat_id)
    return lowered


@dataclass(frozen=True, slots=True)
class _Known:
    chat_id: int
    folder_name: str
    title: str
    username: str | None


@dataclass(frozen=True, slots=True)
class _Scan:
    known: list[_Known]
    unreadable: list[str]


def _scan(root: Path) -> _Scan:
    known: list[_Known] = []
    unreadable: list[str] = []
    for folder in iter_chat_folders(root):
        try:
            state = load_state(folder)
        except StateUnreadable:
            unreadable.append(folder.name)
            continue
        if state is not None:
            known.append(_Known(state.chat_id, folder.name, state.title, state.username))
    return _Scan(known, unreadable)


def _folder_matches_name(name: str, chat: _Known) -> bool:
    """The folder was named after this library name. A name without letters slugs to the
    generic fallback, which says nothing about which chat it is."""
    slug = slugify(name)
    return slug != _FALLBACK_SLUG and chat.folder_name == f"{slug}_{chat.chat_id}"


def _entry_matches(entry: ChatEntry, chat: _Known) -> bool:
    parsed = parse_ref(entry.key)
    if parsed.kind is RefKind.NUMERIC:
        return parsed.number == chat.chat_id
    if parsed.kind is RefKind.PUBLIC:
        return chat.username is not None and chat.username.casefold() == parsed.username
    if entry.name is not None and _folder_matches_name(entry.name, chat):
        return True
    return parsed.kind is RefKind.TITLE and fold(chat.title) == fold(parsed.value)


def resolve_chat_selector(ctx: ServiceContext, text: str) -> int:
    """Map a chat id, `@username`, folder name, title, library name or ref to a chat id."""
    needle = text.strip()
    if not needle:
        raise ChatImportError("the chat selector is empty")
    if _NUMBER_RE.fullmatch(needle):
        return int(needle)
    folded = fold(needle)
    username = folded.removeprefix("@")
    scan = _scan(ctx.root)
    hits = {
        chat.chat_id
        for chat in scan.known
        if folded in (fold(chat.folder_name), fold(chat.title))
        or (chat.username is not None and chat.username.casefold() == username)
    }
    try:
        entry = load_library(ctx.library_file).find(needle)
    except LibraryError:
        entry = None
    if entry is not None:
        hits.update(chat.chat_id for chat in scan.known if _entry_matches(entry, chat))
        parsed = parse_ref(entry.key)
        if not hits and parsed.kind is RefKind.NUMERIC and parsed.number is not None:
            hits.add(parsed.number)
    if scan.unreadable:
        log.warning(
            "chat folders are unreadable right now", extra={"folders": len(scan.unreadable)}
        )
        raise ChatImportError(
            f"{len(scan.unreadable)} chat folder(s) cannot be read right now "
            f"({', '.join(scan.unreadable)}); retry, or use the numeric chat id"
        )
    if not hits:
        raise ChatImportError(f"no known chat matches {needle!r}")
    if len(hits) > 1:
        raise ChatImportError(f"{needle!r} matches several chats; use the numeric chat id")
    return next(iter(hits))
