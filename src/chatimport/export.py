"""`chatimport export-json`: one classic JSON array with every record of a chat (spec §9.1)."""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING

from chatimport.storage.writer import iter_records

if TYPE_CHECKING:
    from pathlib import Path


def export_chat_json(folder: Path, out: Path | None = None) -> Path:
    """Stream the records in order into `out` (default `<folder>/<folder name>.json`)."""
    target = out if out is not None else folder / f"{folder.name}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("[")
            first = True
            for record in iter_records(folder):
                handle.write("\n" if first else ",\n")
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
                first = False
            handle.write("]\n" if first else "\n]\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise
    return target
