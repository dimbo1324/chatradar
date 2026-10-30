"""The library of tracked chats (`chats.toml`): parsing, diffing, watching and safe editing."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from chatimport.ports import ChatImportError
from chatimport.refs import display_ref, parse_ref
from chatimport.textnorm import fold
from chatimport.toml_edit import TomlDocument, toml_string, write_validated

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

__all__ = [
    "ChatEntry",
    "Library",
    "LibraryChange",
    "LibraryError",
    "LibraryWatcher",
    "add_entry",
    "diff_libraries",
    "display_ref",
    "identity_of",
    "load_library",
    "parse_library",
    "set_enabled",
]

_ENTRY_KEYS: Final = frozenset({"ref", "name", "enabled"})
_HEADER_RE: Final = re.compile(r"^\s*\[\[\s*chat\s*\]\]\s*(#.*)?$")


class LibraryError(ChatImportError):
    """The library file is broken or invalid."""


@dataclass(frozen=True, slots=True)
class ChatEntry:
    ref: str
    name: str | None = None
    enabled: bool = True

    @property
    def key(self) -> str:
        return self.ref.strip()


@dataclass(frozen=True)
class Library:
    entries: tuple[ChatEntry, ...] = ()

    def enabled_entries(self) -> tuple[ChatEntry, ...]:
        return tuple(entry for entry in self.entries if entry.enabled)

    def find(self, name_or_ref: str) -> ChatEntry | None:
        """By ref (exact, then the same chat or the same text in any case or Unicode form),
        then by name ignoring case and Unicode form."""
        needle = name_or_ref.strip()
        if not needle:
            return None
        identity = identity_of(needle)
        folded = fold(needle)
        return (
            self._first(lambda entry: entry.key == needle)
            or self._first(
                lambda entry: identity_of(entry.ref) == identity or fold(entry.ref) == folded
            )
            or self._first(lambda entry: entry.name is not None and fold(entry.name) == folded)
        )

    def _first(self, test: Callable[[ChatEntry], bool]) -> ChatEntry | None:
        return next((entry for entry in self.entries if test(entry)), None)


@dataclass(frozen=True)
class LibraryChange:
    added: tuple[ChatEntry, ...] = ()
    removed: tuple[ChatEntry, ...] = ()
    disabled: tuple[ChatEntry, ...] = ()
    enabled: tuple[ChatEntry, ...] = ()
    renamed: tuple[ChatEntry, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.disabled or self.enabled or self.renamed)


def identity_of(ref: str) -> str:
    """Refs naming the same chat (`@Name`, `t.me/name`, `https://telegram.me/NAME?x=1`) share
    one identity."""
    return parse_ref(ref).identity


def _parse_entry(index: int, raw: object) -> ChatEntry:
    if not isinstance(raw, dict):
        raise LibraryError(f"chat entry #{index}: expected a table")
    table = cast("dict[str, Any]", raw)
    ref_value = table.get("ref")
    label = f"chat entry #{index}"
    if isinstance(ref_value, str) and ref_value.strip():
        label = f"chat entry #{index} ({display_ref(ref_value)})"
    unknown = sorted(set(table) - _ENTRY_KEYS)
    if unknown:
        raise LibraryError(f"{label}: unknown key(s) {', '.join(unknown)}")
    if not isinstance(ref_value, str) or not ref_value.strip():
        raise LibraryError(f"{label}: 'ref' must be a non-empty string")
    name_value = table.get("name")
    name: str | None = None
    if name_value is not None:
        if not isinstance(name_value, str) or not name_value.strip():
            raise LibraryError(f"{label}: 'name' must be a non-empty string")
        name = name_value.strip()
    enabled_value = table.get("enabled", True)
    if not isinstance(enabled_value, bool):
        raise LibraryError(f"{label}: 'enabled' must be true or false")
    return ChatEntry(ref=ref_value.strip(), name=name, enabled=enabled_value)


def parse_library(text: str) -> Library:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise LibraryError(f"invalid TOML: {error}") from error
    unknown = sorted(set(data) - {"chat"})
    if unknown:
        raise LibraryError(f"unknown top-level key(s) {', '.join(unknown)}")
    raw_chats: object = data.get("chat", [])
    if not isinstance(raw_chats, list):
        raise LibraryError("'chat' must be an array of tables ([[chat]])")
    entries: list[ChatEntry] = []
    seen: set[str] = set()
    for index, raw in enumerate(cast("list[object]", raw_chats), start=1):
        entry = _parse_entry(index, raw)
        identity = identity_of(entry.ref)
        if identity in seen:
            raise LibraryError(f"chat entry #{index}: duplicate ref {display_ref(entry.key)!r}")
        seen.add(identity)
        entries.append(entry)
    return Library(entries=tuple(entries))


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except OSError as error:
        raise LibraryError(f"cannot read {path}: {error}") from error
    except UnicodeDecodeError as error:
        raise LibraryError(f"{path} is not valid UTF-8: {error}") from error


def load_library(path: Path) -> Library:
    if not path.exists():
        return Library()
    return parse_library(_read_text(path))


def diff_libraries(old: Library, new: Library) -> LibraryChange:
    old_by_key = {entry.key: entry for entry in old.entries}
    new_by_key = {entry.key: entry for entry in new.entries}
    added: list[ChatEntry] = []
    removed: list[ChatEntry] = []
    disabled: list[ChatEntry] = []
    enabled: list[ChatEntry] = []
    renamed: list[ChatEntry] = []
    for key, entry in new_by_key.items():
        before = old_by_key.get(key)
        if before is None:
            if entry.enabled:
                added.append(entry)
            continue
        if before.enabled and not entry.enabled:
            disabled.append(entry)
        elif entry.enabled and not before.enabled:
            enabled.append(entry)
        if before.name != entry.name:
            renamed.append(entry)
    for key, entry in old_by_key.items():
        if key not in new_by_key and entry.enabled:
            removed.append(entry)
    return LibraryChange(
        added=tuple(added),
        removed=tuple(removed),
        disabled=tuple(disabled),
        enabled=tuple(enabled),
        renamed=tuple(renamed),
    )


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise LibraryError(f"cannot stat {path}: {error}") from error
    return (stat.st_mtime_ns, stat.st_size)


class LibraryWatcher:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.current: Library = Library()
        self.last_error: str | None = None
        self._signature: tuple[int, int] | None = None
        self._seen = False

    def load_initial(self) -> Library:
        try:
            self._signature = _signature(self.path)
            self._seen = True
            self.current = load_library(self.path)
        except LibraryError as error:
            self.last_error = str(error)
            raise
        self.last_error = None
        return self.current

    def check(self) -> LibraryChange | None:
        try:
            signature = _signature(self.path)
        except LibraryError as error:
            self.last_error = str(error)
            return None
        if self._seen and signature == self._signature:
            return None
        vanished = signature is None and self._signature is not None
        self._signature = signature
        self._seen = True
        if vanished:
            self.last_error = f"{self.path} disappeared; keeping the last known entries"
            return None
        try:
            new = load_library(self.path)
        except LibraryError as error:
            self.last_error = str(error)
            return None
        self.last_error = None
        change = diff_libraries(self.current, new)
        self.current = new
        return None if change.is_empty else change


def _read_for_edit(path: Path) -> str:
    return _read_text(path) if path.exists() else ""


def add_entry(path: Path, ref: str, name: str | None = None) -> None:
    clean_ref = ref.strip()
    if not clean_ref:
        raise LibraryError("ref must not be empty")
    clean_name = name.strip() if name is not None else None
    if name is not None and not clean_name:
        raise LibraryError("name must not be empty")
    text = _read_for_edit(path)
    existing = parse_library(text)
    if any(identity_of(entry.ref) == identity_of(clean_ref) for entry in existing.entries):
        raise LibraryError(f"{display_ref(clean_ref)!r} is already in the library")
    block = ["[[chat]]", f"ref = {toml_string(clean_ref)}"]
    if clean_name is not None:
        block.append(f"name = {toml_string(clean_name)}")
    document = TomlDocument(text)
    document.append_block(block)
    write_validated(path, document.text(), parse_library)


def set_enabled(path: Path, name_or_ref: str, enabled: bool) -> None:
    text = _read_for_edit(path)
    library = parse_library(text)
    target = library.find(name_or_ref)
    if target is None:
        raise LibraryError(f"no library entry matches {display_ref(name_or_ref)!r}")
    index = library.entries.index(target)
    document = TomlDocument(text)
    headers = document.find_tables(_HEADER_RE)
    if index >= len(headers):
        raise LibraryError(f"cannot locate the block of {display_ref(target.key)!r} in {path}")
    document.set_value(headers[index], "enabled", "true" if enabled else "false")
    write_validated(path, document.text(), parse_library)
