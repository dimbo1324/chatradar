"""Pure text and identity helpers shared by every mapper and stage."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import UTC, datetime

_TRAILING_SPACE = re.compile(r"[ \t\u00a0]+(?=\n)")
_BLANK_LINES = re.compile(r"\n{3,}")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def normalize_text(raw: str) -> str:
    """NFC, unified newlines, no trailing spaces, at most one blank line in a row, trimmed."""
    text = unicodedata.normalize("NFC", raw).replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    return _BLANK_LINES.sub("\n\n", text).strip()


def content_hash(*, text_raw: str, media_type: str, reply_to: str | None) -> str:
    """Hash of the fields whose change means "the message was edited"."""
    material = "\x1f".join([text_raw, media_type, reply_to or ""])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def fingerprint(text: str) -> str:
    """Hash of the text ignoring case, punctuation and spacing — for duplicate detection."""
    folded = _NON_WORD.sub(" ", unicodedata.normalize("NFKC", text).casefold()).strip()
    return hashlib.sha1(folded.encode("utf-8"), usedforsecurity=False).hexdigest()


def message_link(chat_id: str, msg_id: str, username: str | None = None) -> str | None:
    """t.me link: public chats by username, private supergroups by the id without -100."""
    if username:
        return f"https://t.me/{username.lstrip('@')}/{msg_id}"
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{msg_id}"
    return None


def ensure_utc(value: datetime) -> datetime:
    """Naive datetimes are taken as UTC; aware ones are converted to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def thread_id_for(chat_id: str, root_msg_id: str) -> str:
    return f"{chat_id}:{root_msg_id}"
