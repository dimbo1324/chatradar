"""Pure checks for the two Telegram API credentials; an error is a translatable string key."""

from __future__ import annotations

import re
from typing import Final

API_HASH_LENGTH: Final = 32
API_ID_ERROR: Final = "settings.tg.err.api_id"
API_HASH_ERROR: Final = "settings.tg.err.api_hash"
_HASH: Final = re.compile(rf"[0-9a-fA-F]{{{API_HASH_LENGTH}}}")


def validate_api_id(text: str) -> str | None:
    """None for a positive whole number written with ASCII digits, else the error key."""
    value = text.strip()
    if value.isascii() and value.isdigit() and int(value) > 0:
        return None
    return API_ID_ERROR


def validate_api_hash(text: str) -> str | None:
    """None for exactly 32 hexadecimal characters, else the error key."""
    return None if _HASH.fullmatch(text.strip()) else API_HASH_ERROR
