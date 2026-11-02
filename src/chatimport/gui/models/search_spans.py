"""Where a query matches inside a stored message, computed for the original text.

The index compares folded text (case, accents and yo/ye ignored). Folding can change lengths
(the German sharp s becomes `ss`, a combining accent disappears), so the text is folded one
character at a time and an index map points every folded character back to the original one.
`find_spans` therefore returns spans that are valid for the text exactly as stored. The breve
of the Russian short i is kept, so that letter never matches the plain i.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from html import escape
from typing import Final

ELLIPSIS: Final = "…"
LEAD_CHARS: Final = 48
SNAP_CHARS: Final = 14
DEFAULT_LIMIT: Final = 320
_FLATTEN: Final = re.compile(r"[\r\n\t\v\f\u2028\u2029]")

type Span = tuple[int, int]


def _fold_char(char: str) -> str:
    if char.isspace():
        return " "
    if char in "\u0439\u0419":
        return "\u0439"
    bare = "".join(
        piece for piece in unicodedata.normalize("NFD", char) if unicodedata.category(piece) != "Mn"
    )
    return unicodedata.normalize("NFC", bare).casefold()


def _fold_with_map(text: str) -> tuple[str, list[int]]:
    folded: list[str] = []
    origin: list[int] = []
    for position, char in enumerate(text):
        piece = _fold_char(char)
        if piece == " " and (not folded or folded[-1] == " "):
            continue
        for part in piece:
            folded.append(part)
            origin.append(position)
    return "".join(folded), origin


def fold_needle(needle: str) -> str:
    folded, _origin = _fold_with_map(needle)
    return folded.strip()


def _merge(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _end_of_marks(text: str, end: int) -> int:
    while end < len(text) and unicodedata.category(text[end]) == "Mn":
        end += 1
    return end


def find_spans(text: str, needle: str) -> list[Span]:
    """Every `(start, end)` of `text` that the folded `needle` matches; sorted and merged."""
    wanted = fold_needle(needle)
    if not wanted:
        return []
    folded, origin = _fold_with_map(text)
    spans: list[Span] = []
    at = folded.find(wanted)
    while at != -1:
        last = at + len(wanted) - 1
        spans.append((origin[at], _end_of_marks(text, origin[last] + 1)))
        at = folded.find(wanted, at + 1)
    return _merge(spans)


@dataclass(frozen=True, slots=True)
class Snippet:
    text: str
    spans: tuple[Span, ...]
    truncated: bool


def _snap_start(text: str, start: int) -> int:
    if start == 0:
        return 0
    window = text[start : start + SNAP_CHARS]
    gap = window.find(" ")
    return start + gap + 1 if gap != -1 else start


def _snap_end(text: str, start: int, end: int) -> int:
    if end >= len(text):
        return len(text)
    floor = max(end - SNAP_CHARS, start + 1)
    gap = text.rfind(" ", floor, end)
    return gap if gap != -1 else end


@lru_cache(maxsize=1024)
def snippet(text: str, needle: str, limit: int = DEFAULT_LIMIT) -> Snippet:
    """The text flattened to one line (1:1, so spans stay valid) and cut around the first match.

    A cut end is marked with an ellipsis; the spans are shifted into the returned text.
    """
    flat = _FLATTEN.sub(" ", text)
    spans = find_spans(flat, needle)
    if len(flat) <= limit:
        return Snippet(flat, tuple(spans), False)
    first = spans[0][0] if spans else 0
    start = _snap_start(flat, max(first - LEAD_CHARS, 0))
    end = _snap_end(flat, start, min(start + limit, len(flat)))
    head = ELLIPSIS if start > 0 else ""
    tail = ELLIPSIS if end < len(flat) else ""
    shift = len(head) - start
    kept = tuple(
        (max(a, start) + shift, min(b, end) + shift) for a, b in spans if b > start and a < end
    )
    return Snippet(head + flat[start:end] + tail, kept, True)


def highlight_html(text: str, spans: list[Span], color: str) -> str:
    """`text` as safe HTML with the spans on a `color` background; newlines become breaks."""
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(escape(text[cursor:start]))
        out.append(f'<span style="background-color:{color}">{escape(text[start:end])}</span>')
        cursor = end
    out.append(escape(text[cursor:]))
    return "".join(out).replace("\n", "<br>")
