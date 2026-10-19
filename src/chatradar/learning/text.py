"""Tokens and n-grams for mining, on `fold`-compatible surface forms.

Privacy: text around a link, a mention, an e-mail or a long digit run (a phone number) is cut
out before folding, so no n-gram can contain or span one. The cut pieces are never counted.
"""

from __future__ import annotations

import re

from chatradar.pipeline.lexicons import fold

_UNSAFE = re.compile(r"\S*(?:@|http|www\.|t\.me/)\S*|\S*\d{6,}\S*", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\d{6,}")
MAX_TERM_CHARS = 200


def segments(text: str) -> list[list[str]]:
    """Folded tokens of the safe stretches of `text`; an unsafe token ends a stretch."""
    result: list[list[str]] = []
    last = 0
    for match in _UNSAFE.finditer(text):
        tokens = fold(text[last : match.start()]).split()
        if tokens:
            result.append(tokens)
        last = match.end()
    tokens = fold(text[last:]).split()
    if tokens:
        result.append(tokens)
    return result


def leading_tokens(text: str) -> list[str]:
    """Folded tokens from the start of `text` up to the first unsafe token."""
    match = _UNSAFE.search(text)
    return fold(text[: match.start()] if match else text).split()


def ngrams(tokens: list[str], max_n: int, min_n: int = 1) -> set[str]:
    """Distinct n-grams of orders `min_n..max_n` as space-joined strings."""
    found: set[str] = set()
    for n in range(min_n, max_n + 1):
        for start in range(len(tokens) - n + 1):
            found.add(" ".join(tokens[start : start + n]))
    return found


def message_ngrams(text: str, max_n: int) -> set[str]:
    """Distinct safe n-grams of the whole text; none spans an unsafe token."""
    found: set[str] = set()
    for tokens in segments(text):
        found |= ngrams(tokens, max_n)
    return {term for term in found if is_safe_term(term)}


def is_safe_term(term: str) -> bool:
    """The privacy guards applied to every proposed term."""
    return (
        len(term) > 1
        and len(term) <= MAX_TERM_CHARS
        and "@" not in term
        and "http" not in term
        and _DIGIT_RUN.search(term) is None
    )


def is_unsafe_text(text: str) -> bool:
    """Whether the text contains a link, a mention or a long digit run."""
    return _UNSAFE.search(text) is not None
