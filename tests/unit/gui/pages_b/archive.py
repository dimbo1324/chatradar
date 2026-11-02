"""Builds a small ChatImport folder with the real storage writer."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import new_state
from chatimport.storage.writer import ChunkWriter
from tests.fakes import NOW, msg

if TYPE_CHECKING:
    from pathlib import Path

ALPHA_ID = -1001000000001
BETA_ID = -1001000000002


def build_chat(
    root: Path, chat_id: int, title: str, days: list[int], *, media: bool = False
) -> Path:
    folder = root / chat_folder_name(title, chat_id)
    writer = ChunkWriter(folder, 1, lambda: NOW)
    state = writer.update_state(new_state(chat_id, title, None, NOW))
    for number, day in enumerate(days, start=1):
        date = datetime(2026, 9, day, 10, 0, 0, tzinfo=UTC)
        state = writer.append(state, [msg(number, chat_id=chat_id, date=date)])
    if media:
        (folder / "media").mkdir()
        (folder / "media" / "1.bin").write_bytes(b"x" * 100)
    return folder


def build_archive(root: Path) -> None:
    build_chat(root, ALPHA_ID, "Alpha", [1, 2, 3, 4])
    build_chat(root, BETA_ID, "Beta", [5, 6], media=True)
    (root / "_status.json").write_text("{}", encoding="utf-8")
