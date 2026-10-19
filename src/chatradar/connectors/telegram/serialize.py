"""Turn Telethon's `Message.to_dict()` into plain JSON values for the raw store."""

from __future__ import annotations

import base64
from datetime import datetime
from typing import cast

from chatradar.domain.text import ensure_utc

type Json = bool | int | float | str | list[Json] | dict[str, Json] | None


def to_jsonable(obj: object) -> Json:
    """datetime → ISO 8601 UTC, bytes → base64, containers recursively, the rest as str."""
    if obj is None or isinstance(obj, bool | int | float | str):
        return obj
    if isinstance(obj, datetime):
        return ensure_utc(obj).isoformat()
    if isinstance(obj, bytes | bytearray):
        return base64.b64encode(bytes(obj)).decode("ascii")
    if isinstance(obj, dict):
        return {
            str(key): to_jsonable(value) for key, value in cast("dict[object, object]", obj).items()
        }
    if isinstance(obj, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in cast("list[object]", obj)]
    return str(obj)
