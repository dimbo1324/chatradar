"""The one parser of library refs (`@name`, `t.me` links, invites, ids, exact titles).

Pure and Telethon-free: the library, the offline selector and the Telegram resolver all read a
ref through `parse_ref`, so they agree on which refs name the same chat.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

CHANNEL_ID_BASE: Final = 10**12
INVITE_VISIBLE_CHARS: Final = 3

_URL: Final = re.compile(r"^(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(.+)$", re.IGNORECASE)
_USERNAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
_NUMBER: Final = re.compile(r"^-?\d+$")


class RefKind(StrEnum):
    PUBLIC = "public"
    INVITE = "invite"
    NUMERIC = "numeric"
    TITLE = "title"


@dataclass(frozen=True, slots=True)
class ParsedRef:
    kind: RefKind
    value: str
    number: int | None = None

    @property
    def identity(self) -> str:
        """Equal for refs that name the same chat: usernames ignore case, ids are numbers,
        titles are compared in NFC so composed and decomposed accents agree."""
        match self.kind:
            case RefKind.PUBLIC:
                return "@" + self.value.casefold()
            case RefKind.INVITE:
                return "invite:" + self.value
            case RefKind.NUMERIC:
                return str(self.number)
            case _:
                return unicodedata.normalize("NFC", self.value)

    @property
    def username(self) -> str | None:
        """The case-folded username of a public ref, else None."""
        return self.value.casefold() if self.kind is RefKind.PUBLIC else None


def parse_ref(ref: str) -> ParsedRef:
    text = ref.strip()
    url = _URL.match(text)
    if url:
        return _parse_path(url.group(1), text)
    if text.startswith("@") and _USERNAME.match(text[1:]):
        return ParsedRef(RefKind.PUBLIC, text[1:])
    if _NUMBER.match(text):
        return ParsedRef(RefKind.NUMERIC, text, int(text))
    return ParsedRef(RefKind.TITLE, text)


def _parse_path(path: str, original: str) -> ParsedRef:
    segments = path.split("?", 1)[0].split("#", 1)[0].strip("/").split("/")
    first = segments[0]
    if first.startswith("+") and len(first) > 1:
        return ParsedRef(RefKind.INVITE, first[1:])
    if first.lower() == "joinchat":
        if len(segments) > 1 and segments[1]:
            return ParsedRef(RefKind.INVITE, segments[1])
        return ParsedRef(RefKind.TITLE, original)
    if first == "c" and len(segments) > 1 and segments[1].isdigit():
        return ParsedRef(RefKind.NUMERIC, segments[1], -(CHANNEL_ID_BASE + int(segments[1])))
    if _USERNAME.match(first):
        return ParsedRef(RefKind.PUBLIC, first)
    return ParsedRef(RefKind.TITLE, original)


def display_ref(ref: str, *, digest: bool = False) -> str:
    """The ref as it may be shown or stored outside `chats.toml`: an invite link is a secret
    join token, so only its first characters are kept; `digest` adds a short hash that tells
    two invites apart without revealing either."""
    parsed = parse_ref(ref)
    if parsed.kind is not RefKind.INVITE:
        return ref.strip()
    shown = f"t.me/+{parsed.value[:INVITE_VISIBLE_CHARS]}..."
    if digest:
        shown += "#" + hashlib.sha256(parsed.value.encode()).hexdigest()[:6]
    return shown
