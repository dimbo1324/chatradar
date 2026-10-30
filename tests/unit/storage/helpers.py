from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chatimport.records import MessageRecord, Record
from chatimport.storage.layout import list_parts
from chatimport.storage.state import ChatState, load_state, new_state
from chatimport.storage.writer import ChunkWriter, iter_part_records, scan_part
from tests.fakes import CHAT_ID, NOW

if TYPE_CHECKING:
    from pathlib import Path


def fresh_state(chat_id: int = CHAT_ID) -> ChatState:
    return new_state(chat_id, "Example", None, NOW)


def make_writer(folder: Path, max_bytes: int = 10**9) -> ChunkWriter:
    return ChunkWriter(folder, max_bytes, clock=lambda: NOW)


def at(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def all_records(folder: Path) -> list[Record]:
    return [r for path in list_parts(folder) for r in iter_part_records(path)]


def message_ids(folder: Path) -> list[int]:
    return [r.msg_id for r in all_records(folder) if isinstance(r, MessageRecord)]


def part_names(folder: Path) -> list[str]:
    return [p.name for p in list_parts(folder)]


def assert_state_matches_files(folder: Path) -> ChatState:
    """state.json agrees with the parts: chunk accounting, byte sizes and last_id."""
    state = load_state(folder)
    assert state is not None
    parts = list_parts(folder)
    assert set(state.chunks) == {p.stem for p in parts}
    for path in parts:
        assert state.chunks[path.stem] == scan_part(path), path.name
        assert state.chunks[path.stem].bytes == path.stat().st_size
    ids = message_ids(folder)
    assert state.last_id == max(ids, default=0)
    return state


def chars(*codepoints: int) -> str:
    return "".join(map(chr, codepoints))


RU_UPPER = chars(0x41F, 0x440, 0x438, 0x432, 0x435, 0x442)
RU_LOWER = chars(0x43F, 0x440, 0x438, 0x432, 0x435, 0x442)
ZH = chars(0x4E2D, 0x6587)
JA = chars(0x65E5, 0x672C, 0x8A9E)
HE = chars(0x5E9, 0x5DC, 0x5D5, 0x5DD)
LINE_SEP = chr(0x2028)
PARA_SEP = chr(0x2029)
EMOJI = chr(0x1F600)
