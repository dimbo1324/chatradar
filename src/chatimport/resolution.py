"""Library entries to chats: resolving them, and the book of which entries are running,
which wait for a retry, and which errors the status file shows."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, NamedTuple, Protocol

from chatimport.ports import ChatImportError, ResolvedChat, ResolveStatus, SessionRevoked
from chatimport.runtime import TrackedChat
from chatimport.storage.layout import chat_folder_name
from chatimport.telegram.resolve import RefKind, parse_ref

if TYPE_CHECKING:
    from collections.abc import Iterable

    from chatimport.library import ChatEntry, Library
    from chatimport.ports import TelegramGateway

log = logging.getLogger(__name__)

RETRYABLE: Final = (ResolveStatus.NEED_TO_JOIN, ResolveStatus.NOT_FOUND)
LIBRARY_ERROR: Final = "library"


class ResolvedEntry(NamedTuple):
    entry: ChatEntry
    resolved: ResolvedChat

    @property
    def found(self) -> bool:
        return self.resolved.status is ResolveStatus.FOUND and self.resolved.chat_id is not None


async def resolve_entries(
    gateway: TelegramGateway, entries: Iterable[ChatEntry]
) -> list[ResolvedEntry]:
    results: list[ResolvedEntry] = []
    for entry in entries:
        try:
            resolved = await gateway.resolve(entry.key)
        except SessionRevoked:
            raise
        except ChatImportError as error:
            resolved = ResolvedChat(entry.key, ResolveStatus.NOT_FOUND, detail=type(error).__name__)
        results.append(ResolvedEntry(entry, resolved))
    return results


async def resolve_library(gateway: TelegramGateway, library: Library) -> list[ResolvedEntry]:
    return await resolve_entries(gateway, library.enabled_entries())


async def select_for_once(
    gateway: TelegramGateway, library: Library, chat: str
) -> list[ResolvedEntry]:
    """The entries `run --once --chat X` syncs: by ref or name, else by chat id or username."""
    entry = library.find(chat)
    if entry is not None:
        return await resolve_entries(gateway, [entry])
    needle = chat.strip().casefold()
    username = needle.removeprefix("@")
    matched = [
        item
        for item in await resolve_library(gateway, library)
        if str(item.resolved.chat_id) == needle
        or (item.resolved.username is not None and item.resolved.username.casefold() == username)
    ]
    if not matched:
        raise ChatImportError(f"no library chat matches {chat.strip()!r}")
    return matched


def tracked_chat(entry: ChatEntry, resolved: ResolvedChat) -> TrackedChat:
    if resolved.chat_id is None:
        raise ChatImportError("the library entry is not resolved to a chat")
    title = resolved.title or entry.name or str(resolved.chat_id)
    return TrackedChat(
        chat_id=resolved.chat_id,
        title=title,
        username=resolved.username,
        folder_name=chat_folder_name(entry.name or title, resolved.chat_id),
    )


def display_ref(ref: str) -> str:
    """The ref as status files and toasts may show it: an invite link is a secret join token,
    so only its first characters and a short digest (to tell two invites apart) remain."""
    parsed = parse_ref(ref)
    if parsed.kind is not RefKind.INVITE:
        return ref.strip()
    digest = hashlib.sha256(parsed.value.encode()).hexdigest()[:6]
    return f"t.me/+{parsed.value[:3]}...#{digest}"


def resolve_error_key(entry: ChatEntry) -> str:
    return f"resolve:{display_ref(entry.key)}"


class ErrorSink(Protocol):
    def add_error(self, key: str, text: str) -> None: ...

    def clear_error(self, key: str) -> None: ...


class ErrorBook:
    """Service-level errors (library, resolving) that outlive a runtime restart; the attached
    sink (the status writer of the current runtime) always mirrors them."""

    def __init__(self) -> None:
        self._errors: dict[str, str] = {}
        self._sink: ErrorSink | None = None

    def attach(self, sink: ErrorSink | None) -> None:
        self._sink = sink
        if sink is not None:
            for key, text in self._errors.items():
                sink.add_error(key, text)

    def set(self, key: str, text: str) -> None:
        self._errors[key] = text
        if self._sink is not None:
            self._sink.add_error(key, text)

    def clear(self, key: str) -> None:
        self._errors.pop(key, None)
        if self._sink is not None:
            self._sink.clear_error(key)

    def items(self) -> dict[str, str]:
        return dict(self._errors)


@dataclass(frozen=True, slots=True)
class Absorbed:
    found: list[ResolvedEntry]
    failed: int
    total: int


class ActiveChats:
    """Which library entries run (keyed by `entry.key`) and which wait to be resolved again.
    Two entries may name one chat; it stops only when the last of them goes."""

    def __init__(self, errors: ErrorBook) -> None:
        self.errors = errors
        self._active: dict[str, ResolvedEntry] = {}
        self._unresolved: dict[str, ChatEntry] = {}

    def __len__(self) -> int:
        return len(self._active)

    def entries(self) -> list[ResolvedEntry]:
        return list(self._active.values())

    @property
    def has_unresolved(self) -> bool:
        return bool(self._unresolved)

    def absorb(self, results: Iterable[ResolvedEntry]) -> Absorbed:
        found: list[ResolvedEntry] = []
        failed = total = 0
        for item in results:
            total += 1
            entry, resolved = item
            key = resolve_error_key(entry)
            if item.found:
                self.errors.clear(key)
                self._unresolved.pop(entry.key, None)
                self._active[entry.key] = item
                found.append(item)
                continue
            failed += 1
            detail = f" ({resolved.detail})" if resolved.detail else ""
            self.errors.set(key, f"{display_ref(entry.key)}: {resolved.status.value}{detail}")
            if resolved.status in RETRYABLE:
                self._unresolved[entry.key] = entry
            log.warning("library entry unresolved: %s", resolved.status.value)
        return Absorbed(found, failed, total)

    def release(self, entry: ChatEntry) -> int | None:
        """Forget the entry; the chat id to stop, unless another entry still uses that chat."""
        self._unresolved.pop(entry.key, None)
        self.errors.clear(resolve_error_key(entry))
        item = self._active.pop(entry.key, None)
        if item is None or item.resolved.chat_id is None:
            return None
        chat_id = item.resolved.chat_id
        if any(other.resolved.chat_id == chat_id for other in self._active.values()):
            return None
        return chat_id

    def retry_candidates(self, library: Library) -> list[ChatEntry]:
        """Unresolved entries still enabled in `library`; the waiting list starts over."""
        entries = [
            entry
            for entry in self._unresolved.values()
            if (current := library.find(entry.key)) is not None and current.enabled
        ]
        self._unresolved.clear()
        return entries
