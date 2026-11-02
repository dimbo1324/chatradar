"""Matching keys for search: the one function that turns text and queries into comparable form."""

from __future__ import annotations

import unicodedata
from typing import Final

from chatimport.textnorm import fold

_CYRILLIC_FIRST: Final = 0x0400
_CYRILLIC_LAST: Final = 0x052F
_YO: Final = {0x451: chr(0x435)}


def _is_cyrillic(char: str) -> bool:
    return bool(char) and _CYRILLIC_FIRST <= ord(char) <= _CYRILLIC_LAST


def clean_text(text: str) -> str:
    """Text SQLite can store: NUL is dropped and lone surrogates become a question mark."""
    return text.replace("\x00", "").encode("utf-8", "replace").decode("utf-8")


def search_key(text: str) -> str:
    """Case-folded, accent-free, yo-as-ye key with collapsed spaces.

    Combining marks are dropped from Latin and other scripts, so `cafe` finds an accented e;
    after a Cyrillic letter they are kept, so the short i with a breve stays distinct from
    plain i. Both the stored text and the typed query go through this one function.
    """
    folded = fold(clean_text(text)).translate(_YO)
    kept: list[str] = []
    base = ""
    for char in unicodedata.normalize("NFD", folded):
        if unicodedata.category(char) == "Mn":
            if _is_cyrillic(base):
                kept.append(char)
            continue
        base = char
        kept.append(char)
    return fold("".join(kept))
