"""`chatimport export-json`: one classic JSON array with every record of a chat (spec §9.1).

The default target is `<root>/_exports/<chat folder>.json`: outside the chat folder, so the
export never mixes with the service's files, and skipped as a service folder by everything
that walks the chats. `include_names=False` blanks sender names and drops the raw Telegram
object, for an export that is meant to be shared.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from chatimport.records import KIND_MESSAGE, escape_line_breaks
from chatimport.storage.fileio import atomic_writer
from chatimport.storage.layout import SERVICE_PREFIX
from chatimport.storage.reader import iter_records

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.records import Record

EXPORTS_DIR: Final = f"{SERVICE_PREFIX}exports"
_NAME_FIELDS: Final = ("sender_name", "sender_username")


def default_export_path(folder: Path) -> Path:
    return folder.parent / EXPORTS_DIR / f"{folder.name}.json"


def _export_dict(record: Record, *, include_names: bool) -> dict[str, Any]:
    data = record.to_dict()
    if not include_names and data.get("kind") == KIND_MESSAGE:
        data.update(dict.fromkeys(_NAME_FIELDS))
        data.pop("raw", None)
    return data


def export_chat_json(folder: Path, out: Path | None = None, *, include_names: bool = True) -> Path:
    """Stream the records in order into `out` (default `default_export_path(folder)`)."""
    target = out if out is not None else default_export_path(folder)
    target.parent.mkdir(parents=True, exist_ok=True)
    with atomic_writer(target, unique=True) as handle:
        handle.write(b"[")
        first = True
        for record in iter_records(folder):
            handle.write(b"\n" if first else b",\n")
            text = json.dumps(_export_dict(record, include_names=include_names), ensure_ascii=False)
            handle.write(escape_line_breaks(text).encode("utf-8"))
            first = False
        handle.write(b"]\n" if first else b"\n]\n")
    return target
