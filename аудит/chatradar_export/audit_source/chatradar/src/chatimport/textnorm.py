"""Text keys that behave the same for Cyrillic, Spanish and English input.

`fold` compares what a person typed with what Telegram or a file holds; `transliterate` turns
a title into ASCII letters for folder names.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

_SPACES: Final = re.compile(r"\s+")

_RUSSIAN_ALPHABET: Final = (
    "a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
    "r", "s", "t", "u", "f", "kh", "ts", "ch", "sh", "shch", "-", "y", "-", "e", "yu", "ya",
)  # fmt: skip
"""Latin for U+0430 (a) through U+044F (ya) in order; `-` marks the silent hard and soft signs."""

_EXTRA_LETTERS: Final = {
    0x451: "yo",  # Russian yo
    0x456: "i",  # Ukrainian and Belarusian i
    0x457: "yi",  # Ukrainian yi
    0x454: "ye",  # Ukrainian ye
    0x491: "g",  # Ukrainian ghe with upturn
    0x45E: "u",  # Belarusian short u
    0xDF: "ss",  # German sharp s
    0xF8: "o",  # o with stroke
    0x142: "l",  # l with stroke
    0xE6: "ae",
    0x153: "oe",
    0x111: "d",  # d with stroke
    0xFE: "th",  # thorn
    0xF0: "d",  # eth
}


def _table() -> dict[int, str]:
    lower: dict[int, str] = {
        0x430 + offset: ("" if latin == "-" else latin)
        for offset, latin in enumerate(_RUSSIAN_ALPHABET)
    }
    lower.update(_EXTRA_LETTERS)
    table = dict(lower)
    for code, latin in lower.items():
        upper = chr(code).upper()
        if len(upper) == 1 and upper != chr(code):
            table[ord(upper)] = latin.capitalize()
    return table


_TRANSLIT: Final = _table()


def fold(text: str) -> str:
    """NFC, case-folded, whitespace collapsed and trimmed: the key for matching user input."""
    return _SPACES.sub(" ", unicodedata.normalize("NFC", text).casefold()).strip()


def transliterate(text: str) -> str:
    """Cyrillic to Latin, then accents and other European letters to plain ASCII."""
    latin = unicodedata.normalize("NFC", text).translate(_TRANSLIT)
    return unicodedata.normalize("NFKD", latin).encode("ascii", "ignore").decode("ascii")
