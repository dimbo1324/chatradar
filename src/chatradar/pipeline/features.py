"""Pure text features shared by the noise and enrich stages. No I/O apart from the
seed lexicon and the language models, both loaded once."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import cache
from typing import TYPE_CHECKING

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

from chatradar.domain.lexicon import LexiconKind
from chatradar.pipeline.lexicon import Lexicon
from chatradar.pipeline.lexicons import contains_phrase, fold

if TYPE_CHECKING:
    from chatradar.domain.models import Message

type ChronoKey = tuple[datetime, int, str]
"""Orders a chat's messages by date, then by id with numeric ids in numeric order."""

LANG_UNKNOWN = "unknown"
LANG_MIXED = "mixed"
LANG_MIN_CHARS = 20
"""Shorter texts (without links and mentions) are too short to tell the language."""
LANG_MIN_MARGIN = 0.3
"""When the two most likely languages are closer than this, the text is `mixed`."""
SCRIPT_MIXED_SHARE = 0.25
"""Cyrillic and Latin letters each above this share of all letters → `mixed`."""

_URL = re.compile(r"(?:https?://|www\.|(?<![\w.])t\.me/)[^\s<>\"'«»]+", re.IGNORECASE)
_URL_TRAILING = ".,;:!?)]}»\"'"
_MENTION = re.compile(r"(?<![\w@.])@[A-Za-z][A-Za-z0-9_]{3,31}\b")
_SENTENCE_BREAK = re.compile(r"[.!?¡¿…\n]+")
_EMOJI_PARTS = frozenset({"So", "Sk", "Mn", "Me", "Cf"})


def chrono_key(msg: Message) -> ChronoKey:
    return (msg.date, len(msg.msg_id), msg.msg_id)


def extract_urls(text: str) -> list[str]:
    """Links in order of appearance, without duplicates and trailing punctuation."""
    seen: dict[str, None] = {}
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(_URL_TRAILING)
        if url:
            seen.setdefault(url, None)
    return list(seen)


def has_mention(text: str) -> bool:
    """An @username (Telegram: 4 to 32 characters, a letter first); e-mail addresses do not
    count."""
    return _MENTION.search(_URL.sub(" ", text)) is not None


def strip_links_and_mentions(text: str) -> str:
    return _MENTION.sub(" ", _URL.sub(" ", text)).strip()


def looks_like_question(text: str, lexicon: Lexicon | None = None) -> bool:
    """A question mark outside links, a request for help anywhere, or a sentence opening
    with a question word. The words come from `lexicon` (the seed lists by default)."""
    lexicon = lexicon or Lexicon.from_seed()
    plain = _URL.sub(" ", text)
    if "?" in plain or "¿" in plain:
        return True
    if contains_phrase(fold(plain), lexicon.folded(LexiconKind.QUESTION_PHRASES)):
        return True
    starters = lexicon.folded(LexiconKind.QUESTIONS)
    for sentence in _SENTENCE_BREAK.split(plain):
        words = fold(sentence)
        if any(words == s or words.startswith(f"{s} ") for s in starters):
            return True
    return False


def is_emoji_only(text: str) -> bool:
    """Emoji (with their joiners and modifiers), optionally with spaces and punctuation."""
    has_symbol = False
    for ch in text:
        category = unicodedata.category(ch)
        if category == "So":
            has_symbol = True
        elif category not in _EMOJI_PARTS and not ch.isspace() and not category.startswith("P"):
            return False
    return has_symbol


@cache
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(
        Language.RUSSIAN, Language.SPANISH, Language.ENGLISH
    ).build()


def detect_language(text: str) -> str:
    """`ru`, `es`, `en`, `mixed` or `unknown`."""
    plain = strip_links_and_mentions(text)
    letters = [ch for ch in plain if ch.isalpha()]
    if len(plain) < LANG_MIN_CHARS or not letters:
        return LANG_UNKNOWN
    cyrillic = sum(1 for ch in letters if unicodedata.name(ch, "").startswith("CYRILLIC"))
    latin = sum(1 for ch in letters if unicodedata.name(ch, "").startswith("LATIN"))
    if min(cyrillic, latin) / len(letters) > SCRIPT_MIXED_SHARE:
        return LANG_MIXED
    ranked = _detector().compute_language_confidence_values(plain)
    if not ranked or ranked[0].value <= 0:
        return LANG_UNKNOWN
    second = ranked[1].value if len(ranked) > 1 else 0.0
    if ranked[0].value - second < LANG_MIN_MARGIN:
        return LANG_MIXED
    return ranked[0].language.iso_code_639_1.name.lower()
