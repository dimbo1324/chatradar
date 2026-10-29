"""The library of tracked chats (`chats.toml`): parsing, diffing, watching and safe editing."""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from chatimport.ports import ChatImportError

_ENTRY_KEYS = frozenset({"ref", "name", "enabled"})
_HEADER_RE = re.compile(r"^\s*\[\[\s*chat\s*\]\]\s*(#.*)?$")
_TABLE_RE = re.compile(r"^\s*\[")
_KEY_RE = re.compile(r"^\s*[A-Za-z0-9_-]+\s*=")
_ENABLED_RE = re.compile(r"^(\s*enabled\s*=\s*)(?:true|false)(.*)$", re.DOTALL)


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
        needle = name_or_ref.strip()
        for entry in self.entries:
            if entry.key == needle:
                return entry
        folded = needle.casefold()
        for entry in self.entries:
            if entry.name is not None and entry.name.casefold() == folded:
                return entry
        return None


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


def _parse_entry(index: int, raw: object) -> ChatEntry:
    if not isinstance(raw, dict):
        raise LibraryError(f"chat entry #{index}: expected a table")
    table = cast("dict[str, Any]", raw)
    ref_value = table.get("ref")
    label = f"chat entry #{index}"
    if isinstance(ref_value, str) and ref_value.strip():
        label = f"chat entry #{index} ({ref_value.strip()})"
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
        if entry.key in seen:
            raise LibraryError(f"chat entry #{index}: duplicate ref {entry.key!r}")
        seen.add(entry.key)
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
        self._signature = signature
        self._seen = True
        try:
            new = load_library(self.path)
        except LibraryError as error:
            self.last_error = str(error)
            return None
        self.last_error = None
        change = diff_libraries(self.current, new)
        self.current = new
        return None if change.is_empty else change


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _write_validated(path: Path, text: str) -> None:
    parse_library(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp.unlink()
        raise


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
    if any(entry.key == clean_ref for entry in existing.entries):
        raise LibraryError(f"{clean_ref!r} is already in the library")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = [f"[[chat]]{newline}", f"ref = {_toml_string(clean_ref)}{newline}"]
    if clean_name is not None:
        lines.append(f"name = {_toml_string(clean_name)}{newline}")
    block = "".join(lines)
    if text and not text.endswith("\n"):
        text += newline
    if text.strip():
        text += newline
    _write_validated(path, text + block)


def set_enabled(path: Path, name_or_ref: str, enabled: bool) -> None:
    text = _read_for_edit(path)
    library = parse_library(text)
    target = library.find(name_or_ref)
    if target is None:
        raise LibraryError(f"no library entry matches {name_or_ref.strip()!r}")
    index = library.entries.index(target)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    headers = [number for number, line in enumerate(lines) if _HEADER_RE.match(line.rstrip("\r\n"))]
    if index >= len(headers):
        raise LibraryError(f"cannot locate the block of {target.key!r} in {path}")
    start = headers[index]
    end = len(lines)
    for number in range(start + 1, len(lines)):
        if _TABLE_RE.match(lines[number]):
            end = number
            break
    value = "true" if enabled else "false"
    last_key = start
    for number in range(start + 1, end):
        raw = lines[number]
        match = _ENABLED_RE.match(raw)
        if match is not None:
            lines[number] = f"{match.group(1)}{value}{match.group(2)}"
            break
        if _KEY_RE.match(raw):
            last_key = number
    else:
        if not lines[last_key].endswith("\n"):
            lines[last_key] += newline
        lines.insert(last_key + 1, f"enabled = {value}{newline}")
    _write_validated(path, "".join(lines))
