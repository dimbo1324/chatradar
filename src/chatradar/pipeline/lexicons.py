"""Text folding and phrase matching shared by the rule stages and the lexicon.

The word lists themselves live in `pipeline/lexicon.py` (the `Lexicon` value) and, at run
time, in the database; this module only knows how to compare text with them.
"""

from __future__ import annotations

import re
import unicodedata

_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)


def fold(text: str) -> str:
    """Case-folded, accents and diacritics removed, punctuation and emoji as single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SEPARATORS.sub(" ", bare).strip()


def contains_phrase(folded_text: str, entries: frozenset[str]) -> bool:
    """Whether an entry occurs in folded text starting at a word boundary (stems match)."""
    padded = f" {folded_text}"
    return any(f" {entry}" in padded for entry in entries)
