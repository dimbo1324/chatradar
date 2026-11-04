"""Line-level edits of hand-written TOML files that keep comments, layout and line endings.

Only lines that begin outside multi-line strings are read as headers, keys or comments, and
lines are split on line feeds only: U+2028 and friends are legal inside TOML strings.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Final

from chatimport.storage.fileio import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_LF: Final = "\n"
_CRLF: Final = "\r\n"
_BACKSLASH: Final = "\\"
_DEL: Final = chr(0x7F)
_TABLE_RE: Final = re.compile(r"^\s*\[")
_COMMENT_RE: Final = re.compile(r"^\s*#")


def toml_string(value: str) -> str:
    """A TOML basic string; JSON escaping is valid TOML except for DEL, which TOML forbids raw."""
    return json.dumps(value, ensure_ascii=False).replace(_DEL, "\\u007f")


def split_lines(text: str) -> list[str]:
    parts = text.split(_LF)
    lines = [part + _LF for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def starts_outside_strings(lines: list[str]) -> set[int]:
    """Indexes of the lines that begin outside any multi-line string."""
    outside: set[int] = set()
    open_quote: str | None = None
    for number, line in enumerate(lines):
        if open_quote is None:
            outside.add(number)
        position = 0
        while position < len(line):
            if open_quote is not None:
                if open_quote == '"""' and line[position] == _BACKSLASH:
                    position += 2
                elif line.startswith(open_quote, position):
                    open_quote = None
                    position += 3
                else:
                    position += 1
                continue
            char = line[position]
            if char == "#":
                break
            if line.startswith(('"""', "'''"), position):
                open_quote = line[position : position + 3]
                position += 3
            elif char == '"':
                position += 1
                while position < len(line) and line[position] != '"':
                    position += 2 if line[position] == _BACKSLASH else 1
                position += 1
            elif char == "'":
                closing = line.find("'", position + 1)
                position = len(line) if closing < 0 else closing + 1
            else:
                position += 1
    return outside


class TomlDocument:
    """A TOML text as lines; every edit keeps the untouched lines byte for byte."""

    def __init__(self, text: str) -> None:
        self.newline = _CRLF if _CRLF in text else _LF
        self.lines = split_lines(text)
        self._outside = starts_outside_strings(self.lines)

    def text(self) -> str:
        return "".join(self.lines)

    def find_tables(self, header: re.Pattern[str]) -> list[int]:
        """Line numbers of the headers that match `header` (tested without the line ending)."""
        return [
            number
            for number, line in enumerate(self.lines)
            if number in self._outside and header.match(line.rstrip("\r\n"))
        ]

    def table_end(self, start: int) -> int:
        """The line number just past the table whose header is at `start`."""
        for number in range(start + 1, len(self.lines)):
            if number in self._outside and _TABLE_RE.match(self.lines[number]):
                return number
        return len(self.lines)

    def set_value(self, start: int, key: str, value: str) -> None:
        """Set `key = value` in the table at `start`: an existing value is replaced and its
        trailing comment kept; a missing key goes below the last line holding a value."""
        assignment = re.compile(rf"\s*{re.escape(key)}\s*=\s*")
        end = self.table_end(start)
        for number in range(start + 1, end):
            if number not in self._outside:
                continue
            body, ending = _split_ending(self.lines[number])
            match = assignment.match(body)
            if match is not None:
                rest = body[match.end() :]
                old_value = rest[: _comment_start(rest)].rstrip()
                tail = rest[len(old_value) :]
                self.lines[number] = f"{body[: match.end()]}{value}{tail}{ending}"
                return
        last = max(
            (number for number in range(start + 1, end) if self._holds_value(number)),
            default=start,
        )
        self._insert_after(last, f"{key} = {value}")

    def append_block(self, lines: list[str]) -> None:
        """Append a new table, separated from earlier content by one blank line."""
        if self.lines and not self.lines[-1].endswith(_LF):
            self.lines[-1] += self.newline
        if self.lines and self.lines[-1].strip():
            self.lines.append(self.newline)
        self.lines.extend(line + self.newline for line in lines)
        self._outside = starts_outside_strings(self.lines)

    def _holds_value(self, number: int) -> bool:
        line = self.lines[number]
        if not line.strip():
            return False
        return number not in self._outside or not _COMMENT_RE.match(line)

    def _insert_after(self, number: int, line: str) -> None:
        if not self.lines[number].endswith(_LF):
            self.lines[number] += self.newline
        self.lines.insert(number + 1, line + self.newline)
        self._outside = starts_outside_strings(self.lines)


def _comment_start(text: str) -> int:
    """Where a `#` comment begins on a one-line value, skipping `#` inside strings."""
    position = 0
    while position < len(text):
        char = text[position]
        if char == "#":
            return position
        if char == '"':
            position += 1
            while position < len(text) and text[position] != '"':
                position += 2 if text[position] == _BACKSLASH else 1
        elif char == "'":
            closing = text.find("'", position + 1)
            position = len(text) if closing < 0 else closing
        position += 1
    return len(text)


def _split_ending(line: str) -> tuple[str, str]:
    if line.endswith(_CRLF):
        return line[:-2], _CRLF
    if line.endswith(_LF):
        return line[:-1], _LF
    return line, ""


def write_validated(
    path: Path, text: str, validate: Callable[[str], object], *, mode: int | None = None
) -> None:
    """Validate the new text first, then replace the file atomically; on any failure the old
    file stays as it was and no temp file is left behind."""
    validate(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, text.encode("utf-8"), unique=True, mode=mode)
