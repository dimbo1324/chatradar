"""Words that mark a "write me privately" phrase, in folded form (Cyrillic as escapes).

An n-gram of spam messages containing one of them is a `spam_contacts` candidate; any other
spam n-gram is a `spam_offers` candidate.
"""

from __future__ import annotations

CONTACT_WORDS: frozenset[str] = frozenset(
    {
        "\u043b\u0441",  # ls (direct messages)
        "dm",
        "pm",
        "inbox",
        "privado",
    }
)
"""Whole tokens."""

CONTACT_PREFIXES: tuple[str, ...] = (
    "\u043b\u0438\u0447\u043a",  # lichk- (lichka, lichku, lichke)
    "privad",
)
"""Token stems; a token starting with one of them is a contact word."""


def is_contact_token(token: str) -> bool:
    return token in CONTACT_WORDS or token.startswith(CONTACT_PREFIXES)


def has_contact_word(term: str) -> bool:
    return any(is_contact_token(token) for token in term.split())
