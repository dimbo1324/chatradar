"""Word lists for the rule stages, read from `chatradar/resources/lexicons/*.txt`.

One entry per line; blank lines and lines starting with `#` are ignored. Entries are folded
with `fold` once at load time, so callers compare folded text with folded entries.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cache
from importlib.resources import files

_SEPARATORS = re.compile(r"[\W_]+", re.UNICODE)

GRATITUDE = "gratitude"
QUESTIONS = "questions"
QUESTION_PHRASES = "question_phrases"
SPAM_OFFERS = "spam_offers"
SPAM_CONTACTS = "spam_contacts"


def fold(text: str) -> str:
    """Case-folded, accents and diacritics removed, punctuation and emoji as single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    bare = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _SEPARATORS.sub(" ", bare).strip()


@cache
def raw_entries(name: str) -> frozenset[str]:
    """The lexicon's entries as written (trimmed), for symbol entries such as "+1"."""
    resource = files("chatradar").joinpath("resources", "lexicons", f"{name}.txt")
    lines = resource.read_text(encoding="utf-8").splitlines()
    return frozenset(
        stripped for line in lines if (stripped := line.strip()) and not stripped.startswith("#")
    )


@cache
def folded_entries(name: str) -> frozenset[str]:
    return frozenset(folded for entry in raw_entries(name) if (folded := fold(entry)))


def contains_phrase(folded_text: str, entries: frozenset[str]) -> bool:
    """Whether an entry occurs in folded text starting at a word boundary (stems match)."""
    padded = f" {folded_text}"
    return any(f" {entry}" in padded for entry in entries)
