"""The combined archive file: every chat's records in one file sorted by time.

The file is a derived copy, rebuilt from the stored parts and replaced atomically in
`<root>/_exports/`; per-chat files stay the source of truth. Chats are merged with a streamed
k-way merge on (date, chat_id, msg_id). A month of one chat whose lines are already in key
order streams with constant memory; a month that is not (edit and delete records land by
their own date, between messages) is sorted in memory as compact lines, one month of one chat
at a time. Like `export-json` it reads parts without the instance lock.
"""

from __future__ import annotations

import heapq
import json
import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, cast

from chatimport.config import MERGED_FORMATS
from chatimport.export import EXPORTS_DIR, export_dict
from chatimport.records import (
    KIND_DELETE,
    KIND_EDIT,
    KIND_MEDIA_SAVED,
    escape_line_breaks,
    format_dt,
    json_line_bytes,
    parse_dt,
    record_event_date,
    record_sort_id,
)
from chatimport.storage.fileio import atomic_write_bytes, atomic_writer, unlink_file
from chatimport.storage.layout import iter_chat_folders, list_parts
from chatimport.storage.reader import iter_part_records
from chatimport.storage.state import StateUnreadable, load_state

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime
    from pathlib import Path

    from chatimport.records import Record

log = logging.getLogger(__name__)

FORMATS: Final = MERGED_FORMATS
BASE_NAME: Final = "all_chats"
META_NAME: Final = f"_{BASE_NAME}.meta.json"
META_VERSION: Final = 1
_KIND_RANK: Final = {KIND_EDIT: 1, KIND_DELETE: 2, KIND_MEDIA_SAVED: 3}

type Key = tuple[datetime, int, int, int]
type Keyed = tuple[Key, Record]
type Signature = dict[str, list[int]]


@dataclass(frozen=True, slots=True)
class MergedResult:
    path: Path
    chats: int
    records: int
    bytes: int
    built_at: datetime
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "chats": self.chats,
            "records": self.records,
            "bytes": self.bytes,
            "built_at": format_dt(self.built_at),
            "skipped": self.skipped,
        }


def exports_dir(root: Path) -> Path:
    return root / EXPORTS_DIR


def merged_path(root: Path, fmt: str) -> Path:
    return exports_dir(root) / f"{BASE_NAME}.{fmt}"


def _check_format(fmt: str) -> None:
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of {', '.join(FORMATS)}")


def _sort_key(record: Record) -> Key:
    return (
        record_event_date(record),
        record.chat_id,
        record_sort_id(record),
        _KIND_RANK.get(record.kind, 0),
    )


def _chat_id_of(folder: Path) -> str:
    tail = folder.name.rpartition("_")[2]
    return tail if tail.lstrip("-").isdigit() else "unknown"


def _safe_part(path: Path, chat: str) -> Iterator[Record]:
    try:
        yield from iter_part_records(path)
    except OSError:
        log.warning("part vanished or unreadable during the combined build", extra={"chat": chat})


def _months(folder: Path) -> Iterator[list[Path]]:
    month: str | None = None
    group: list[Path] = []
    for part in list_parts(folder):
        key = part.name[:7]
        if month is not None and key != month:
            yield group
            group = []
        month = key
        group.append(part)
    if group:
        yield group


def _month_in_order(parts: list[Path], chat: str) -> bool:
    previous: Key | None = None
    for part in parts:
        for record in _safe_part(part, chat):
            key = _sort_key(record)
            if previous is not None and key < previous:
                return False
            previous = key
    return True


def _month_records(parts: list[Path], chat: str) -> Iterator[Keyed]:
    for part in parts:
        for record in _safe_part(part, chat):
            yield _sort_key(record), record


def _chat_stream(folder: Path) -> Iterator[Keyed]:
    chat = _chat_id_of(folder)
    try:
        months = list(_months(folder))
    except OSError:
        months = []
    if not months:
        if not folder.is_dir():
            log.warning("chat folder vanished during the combined build", extra={"chat": chat})
        return
    for parts in months:
        if _month_in_order(parts, chat):
            yield from _month_records(parts, chat)
        else:
            yield from sorted(_month_records(parts, chat), key=_first)


def _first(item: Keyed) -> Key:
    return item[0]


def _title(folder: Path) -> str:
    try:
        state = load_state(folder)
    except StateUnreadable:
        return folder.name
    return state.title if state is not None and state.title else folder.name


def _object(record: Record, folder: str, title: str, *, include_names: bool) -> dict[str, Any]:
    data = export_dict(record, include_names=include_names)
    data["chat_title"] = title
    data["chat_folder"] = folder
    return data


def _signature_of(folder: Path) -> list[int]:
    try:
        state = load_state(folder)
    except StateUnreadable:
        state = None
    if state is not None:
        return [state.last_id, state.total_records, sum(c.bytes for c in state.chunks.values())]
    size = 0
    for part in list_parts(folder):
        try:
            size += part.stat().st_size
        except OSError:
            continue
    return [0, 0, size]


def current_signature(root: Path) -> Signature:
    return {folder.name: _signature_of(folder) for folder in iter_chat_folders(root)}


def read_meta(root: Path) -> dict[str, Any] | None:
    try:
        loaded: object = json.loads((exports_dir(root) / META_NAME).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(loaded, dict):
        return None
    meta = cast("dict[str, Any]", loaded)
    return meta if meta.get("v") == META_VERSION else None


def last_result(root: Path) -> MergedResult | None:
    meta = read_meta(root)
    if meta is None:
        return None
    try:
        return MergedResult(
            path=merged_path(root, str(meta["format"])),
            chats=int(meta["chats"]),
            records=int(meta["records"]),
            bytes=int(meta["bytes"]),
            built_at=parse_dt(str(meta["built_at"])),
        )
    except KeyError, TypeError, ValueError:
        return None


def _up_to_date(root: Path, fmt: str, include_names: bool, signature: Signature) -> bool:
    meta = read_meta(root)
    if meta is None or not merged_path(root, fmt).is_file():
        return False
    return (
        meta.get("format") == fmt
        and meta.get("include_names") == include_names
        and meta.get("signature") == signature
    )


def _write(root: Path, folders: list[Path], fmt: str, *, include_names: bool) -> tuple[int, int]:
    titles = {folder.name: _title(folder) for folder in folders}
    streams = [_tagged(folder, titles[folder.name]) for folder in folders]
    target = merged_path(root, fmt)
    records = 0
    size = 0
    with atomic_writer(target, unique=True) as handle:
        if fmt == "json":
            handle.write(b"[")
            size += 1
        for _key, record, folder_name, title in heapq.merge(*streams, key=_head):
            data = _object(record, folder_name, title, include_names=include_names)
            if fmt == "json":
                text = escape_line_breaks(json.dumps(data, ensure_ascii=False))
                chunk = (b"\n" if records == 0 else b",\n") + text.encode("utf-8")
            else:
                chunk = json_line_bytes(data)
            handle.write(chunk)
            size += len(chunk)
            records += 1
        if fmt == "json":
            tail = b"]\n" if records == 0 else b"\n]\n"
            handle.write(tail)
            size += len(tail)
    return records, size


type Tagged = tuple[Key, Record, str, str]


def _tagged(folder: Path, title: str) -> Iterator[Tagged]:
    for key, record in _chat_stream(folder):
        yield key, record, folder.name, title


def _head(item: Tagged) -> Key:
    return item[0]


def build_merged(
    root: Path,
    *,
    now: datetime,
    fmt: str = "json",
    include_names: bool = False,
    force: bool = False,
) -> MergedResult:
    """Rebuild `<root>/_exports/all_chats.<fmt>`; skipped when no chat changed since the last
    build with the same options (unless `force`). A failed build leaves the old file."""
    _check_format(fmt)
    signature = current_signature(root)
    if not force and _up_to_date(root, fmt, include_names, signature):
        previous = last_result(root)
        if previous is not None:
            return replace(previous, skipped=True)
    folders = list(iter_chat_folders(root))
    exports_dir(root).mkdir(parents=True, exist_ok=True)
    records, size = _write(root, folders, fmt, include_names=include_names)
    other = merged_path(root, next(name for name in FORMATS if name != fmt))
    unlink_file(other, missing_ok=True)
    meta = {
        "v": META_VERSION,
        "built_at": format_dt(now),
        "format": fmt,
        "include_names": include_names,
        "chats": len(folders),
        "records": records,
        "bytes": size,
        "signature": signature,
    }
    atomic_write_bytes(
        exports_dir(root) / META_NAME,
        json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8") + b"\n",
        unique=True,
    )
    return MergedResult(merged_path(root, fmt), len(folders), records, size, now)
