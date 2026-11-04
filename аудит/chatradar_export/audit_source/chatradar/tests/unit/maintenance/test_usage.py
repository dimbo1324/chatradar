# pyright: reportPrivateUsage=false
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from chatimport import usage
from chatimport.storage.layout import STATE_FILE
from chatimport.storage.state import StateUnreadable
from chatimport.usage import ArchiveUsage, ChatUsage, archive_usage
from tests.unit.maintenance.helpers import build_chat, mmsg

if TYPE_CHECKING:
    from collections.abc import Iterator

    import pytest


def part_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.glob("*.jsonl"))


def test_sizes_are_split_into_parts_media_and_other(tmp_path: Path) -> None:
    chat = build_chat(tmp_path, -1001, [[mmsg(1, chat_id=-1001)], [mmsg(2, chat_id=-1001)]])
    (chat.folder / "media" / "2026-09").mkdir(parents=True)
    (chat.folder / "media" / "2026-09" / "a.bin").write_bytes(b"x" * 10)
    (chat.folder / "extra").mkdir()
    (chat.folder / "extra" / "b.bin").write_bytes(b"y" * 5)
    (chat.folder / "notes.txt").write_bytes(b"z" * 3)
    (tmp_path / "_status.json").write_bytes(b"s" * 7)
    (tmp_path / "_exports").mkdir()
    (tmp_path / "_exports" / "e.json").write_bytes(b"e" * 4)

    result = archive_usage(tmp_path)

    (only,) = result.chats
    assert (only.chat_id, only.title, only.parts, only.records) == (-1001, "Chat", 2, 2)
    assert only.jsonl_bytes == part_bytes(chat.folder)
    assert only.media_bytes == 10
    assert only.total_bytes == only.jsonl_bytes + 10
    assert result.jsonl_total == only.jsonl_bytes
    assert result.media_total == 10
    state_size = (chat.folder / STATE_FILE).stat().st_size
    assert result.service_files_total == 7 + 4 + 5 + 3 + state_size
    assert result.total_bytes == result.jsonl_total + 10 + result.service_files_total
    assert result.free_bytes is not None


def test_folder_without_state_keeps_sizes_but_no_identity(tmp_path: Path) -> None:
    chat = build_chat(tmp_path, -1001, [[mmsg(1, chat_id=-1001)]])
    (chat.folder / STATE_FILE).unlink()

    (only,) = archive_usage(tmp_path).chats

    assert (only.chat_id, only.title, only.records) == (None, None, None)
    assert only.parts == 1


def test_empty_folder_without_state_is_not_a_chat(tmp_path: Path) -> None:
    (tmp_path / "stray").mkdir()
    assert archive_usage(tmp_path).chats == ()


def test_folder_with_a_broken_state_file_is_listed(tmp_path: Path) -> None:
    folder = tmp_path / "stray"
    folder.mkdir()
    (folder / STATE_FILE).write_bytes(b"{broken")
    (only,) = archive_usage(tmp_path).chats
    assert only.chat_id is None
    assert only.parts == 0


def test_unreadable_state_is_listed_without_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat = build_chat(tmp_path, -1001, [[mmsg(1, chat_id=-1001)]])

    def refuse(folder: Path) -> None:
        raise StateUnreadable(folder, OSError("busy"))

    monkeypatch.setattr(usage, "load_state", refuse)
    (only,) = archive_usage(tmp_path).chats
    assert only.folder == chat.folder
    assert (only.chat_id, only.title, only.records) == (None, None, None)
    assert only.parts == 1


def test_missing_root_is_an_empty_archive_and_free_space_comes_from_a_parent(
    tmp_path: Path,
) -> None:
    result = archive_usage(tmp_path / "nowhere" / "deeper")
    assert result == ArchiveUsage((), 0, 0, 0, result.free_bytes)
    assert result.free_bytes is not None


def test_free_bytes_is_none_when_the_disk_cannot_be_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: Path) -> None:
        raise OSError("no disk")

    monkeypatch.setattr(usage.shutil, "disk_usage", refuse)
    assert usage._free_bytes(tmp_path) is None


def test_chat_usage_total() -> None:
    chat = ChatUsage(1, "t", Path("x"), 3, 4, 1, 2)
    assert chat.total_bytes == 7


class Entry:
    def __init__(
        self,
        name: str,
        *,
        is_dir: bool = False,
        junction: bool = False,
        size: int = 0,
        stat_error: bool = False,
    ) -> None:
        self.name = name
        self.path = f"root/{name}"
        self._is_dir = is_dir
        self._junction = junction
        self._size = size
        self._stat_error = stat_error

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        return self._is_dir

    def is_junction(self) -> bool:
        return self._junction

    def stat(self, *, follow_symlinks: bool = True) -> Any:
        if self._stat_error:
            raise OSError("gone")
        return SimpleNamespace(st_size=self._size)


class Listing:
    def __init__(self, entries: list[Entry] | None) -> None:
        self._entries = entries

    def __enter__(self) -> Iterator[Entry]:
        if self._entries is None:
            raise OSError("vanished")
        return iter(self._entries)

    def __exit__(self, *exc: object) -> None:
        return None


def fake_scandir(monkeypatch: pytest.MonkeyPatch, tree: dict[str, list[Entry] | None]) -> None:
    def scandir(path: str) -> Listing:
        return Listing(tree.get(str(path).replace(os.sep, "/")))

    monkeypatch.setattr(usage.os, "scandir", scandir)


def test_tree_bytes_counts_files_follows_folders_and_skips_the_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scandir(
        monkeypatch,
        {
            "root": [
                Entry("a", size=5),
                Entry("sub", is_dir=True),
                Entry("link", is_dir=True, junction=True, size=2),
                Entry("bad", stat_error=True),
                Entry("gone", is_dir=True),
            ],
            "root/sub": [Entry("b", size=11)],
            "root/gone": None,
        },
    )
    assert usage._tree_bytes("root") == 5 + 11 + 2


def test_measure_folder_survives_vanishing_entries_and_folders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scandir(
        monkeypatch,
        {
            "root": [
                Entry("media", is_dir=True),
                Entry("other", is_dir=True),
                Entry("x.jsonl", size=3),
                Entry("2026-09_001.jsonl", size=4),
                Entry("bad.jsonl", stat_error=True),
            ],
            "root/media": [Entry("m", size=6)],
            "root/other": [Entry("o", size=8)],
        },
    )
    sizes = usage._measure_folder(Path("root"))
    assert (sizes.jsonl, sizes.parts, sizes.media, sizes.other) == (4, 1, 6, 8 + 3)
    fake_scandir(monkeypatch, {})
    empty = usage._measure_folder(Path("root"))
    assert (empty.jsonl, empty.media, empty.other, empty.parts) == (0, 0, 0, 0)


def test_service_files_ignore_chat_folders_and_unreadable_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scandir(
        monkeypatch,
        {
            "root": [
                Entry("chat_1", is_dir=True, size=100),
                Entry("_status.json", size=2),
                Entry("_exports", is_dir=True),
                Entry("_bad", stat_error=True),
            ],
            "root/_exports": [Entry("e", size=9)],
        },
    )
    assert usage._service_files_bytes(Path("root")) == 11
    fake_scandir(monkeypatch, {})
    assert usage._service_files_bytes(Path("root")) == 0
